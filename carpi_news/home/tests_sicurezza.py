"""Limiti del chatbot e blocco degli indirizzi interni nei link scaricati dalle fonti."""
import json
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from home import views
from home.url_sicuri import UrlNonConsentito, controlla_url, get_pubblico


class ControllaUrlTests(SimpleTestCase):
    def test_indirizzi_interni_rifiutati(self):
        for url in [
            'http://127.0.0.1:8000/admin/',
            'http://localhost/',
            'http://10.0.0.5/',
            'http://192.168.1.1/',
            'http://169.254.169.254/latest/meta-data/',
            'http://[::1]/',
            'http://0.0.0.0/',
            'file:///etc/passwd',
            'ftp://8.8.8.8/',
        ]:
            with self.subTest(url=url), self.assertRaises(UrlNonConsentito):
                controlla_url(url)

    def test_indirizzo_pubblico_accettato(self):
        controlla_url('https://8.8.8.8/pagina')

    def test_redirect_verso_interno_bloccato(self):
        redirect = Mock(is_redirect=True, headers={'Location': 'http://127.0.0.1:8000/admin/'})
        with patch('home.url_sicuri.requests.get', return_value=redirect) as get:
            with self.assertRaises(UrlNonConsentito):
                get_pubblico('https://8.8.8.8/vai')
        self.assertEqual(get.call_count, 1)
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_contenuto_tagliato(self):
        risposta = Mock(is_redirect=False, headers={})
        risposta.iter_content.return_value = iter([b'x' * 600, b'y' * 600])
        with patch('home.url_sicuri.requests.get', return_value=risposta):
            r = get_pubblico('https://8.8.8.8/', max_bytes=1000)
        self.assertEqual(len(r._content), 1000)

    def test_link_interno_nella_fonte_non_scaricato(self):
        from home.universal_news_monitor import scarica_pagine_linkate
        with patch('home.url_sicuri.requests.get') as get:
            pagine = scarica_pagine_linkate('<a href="http://127.0.0.1:8000/admin/">pagina dedicata</a>')
        self.assertEqual(pagine, [])
        get.assert_not_called()


class ChatbotLimitiTests(TestCase):
    def setUp(self):
        cache.clear()
        servizio = patch('home.views.ChatbotService')
        self.servizio = servizio.start()
        self.addCleanup(servizio.stop)
        self.servizio.return_value.process_message.return_value = {
            'response': 'ok', 'articles': [], 'intent': {}}

    def _chiedi(self, messaggio='ciao', ip='1.2.3.4'):
        return self.client.post('/api/chatbot/', data=json.dumps({'message': messaggio}),
                                content_type='application/json', secure=True, HTTP_X_FORWARDED_FOR=ip)

    def test_messaggio_troppo_lungo(self):
        r = self._chiedi('a' * (views.CHATBOT_MAX_CARATTERI + 1))
        self.assertEqual(r.status_code, 400)
        self.assertIn('response', r.json())
        self.servizio.return_value.process_message.assert_not_called()

    def test_limite_orario_per_ip(self):
        for _ in range(views.CHATBOT_RICHIESTE_ORA):
            self.assertEqual(self._chiedi().status_code, 200)
        r = self._chiedi()
        self.assertEqual(r.status_code, 429)
        self.assertIn('response', r.json())
        # un altro visitatore non e' bloccato
        self.assertEqual(self._chiedi(ip='5.6.7.8').status_code, 200)

    def test_ip_falsificato_in_testa_non_aggira_il_limite(self):
        # Apache aggiunge l'IP vero in coda: cambiare il primo valore non deve dare domande nuove
        for i in range(views.CHATBOT_RICHIESTE_ORA):
            self._chiedi(ip=f'9.9.9.{i}, 1.2.3.4')
        self.assertEqual(self._chiedi(ip='9.9.9.200, 1.2.3.4').status_code, 429)

    def test_json_non_oggetto(self):
        r = self.client.post('/api/chatbot/', data='[1,2]', content_type='application/json', secure=True)
        self.assertEqual(r.status_code, 400)
