"""Ricerca del chatbot: confronto delle parole e scelta degli articoli pertinenti."""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from home.chatbot_service import ChatbotService, Termine, normalizza
from home.models import Articolo


class TermineTests(SimpleTestCase):
    def test_parola_intera_corta(self):
        t = Termine('arte')
        self.assertEqual(t.conta(normalizza("Una mostra d'arte")), 1)
        self.assertEqual(t.conta(normalizza('Da parte del Comune')), 0)

    def test_plurali_e_accenti(self):
        self.assertEqual(Termine('incidenti').conta(normalizza('Un incidente in via Roma')), 1)
        self.assertEqual(Termine('sanita').conta(normalizza('La sanità pubblica')), 1)

    def test_nome_spezzato_da_html(self):
        testo = normalizza('<p>Addio ad Alex <strong>Bernardi</strong>, regista</p>')
        self.assertEqual(Termine('alex bernardi').conta(testo), 1)
        self.assertEqual(Termine('bernardi').conta(normalizza('San Bernardino')), 0)

    def test_sinonimi_e_parole_vuote(self):
        self.assertEqual(Termine('sindaco|sindaca').conta(normalizza('la sindaca Paola')), 1)
        self.assertFalse(Termine('della').valido)

    def test_link_ignorati(self):
        testo = normalizza('<a href="https://x.it/aimag-hera">leggi</a> e [qui](https://x.it/aimag)')
        self.assertEqual(Termine('aimag').conta(testo), 0)


class RicercaTests(TestCase):
    def _articolo(self, titolo, contenuto, giorni_fa=1, **extra):
        return Articolo.objects.create(
            titolo=titolo, contenuto=contenuto, sommario=contenuto[:100], approvato=True,
            data_pubblicazione=timezone.now() - timedelta(days=giorni_fa), **extra)

    def setUp(self):
        self.servizio = ChatbotService.__new__(ChatbotService)

    def test_tiene_solo_chi_copre_tutti_i_termini(self):
        tutti = self._articolo('Funerale di Mario Santi', 'Oggi il funerale di Mario Santi in Duomo.')
        self._articolo('Funerale in Duomo', 'Un funerale molto partecipato.')
        self._articolo('Ognissanti', 'La festa di tutti i santi.')
        risultati = self.servizio._search_articles({'keywords': ['funerale', 'santi']})
        self.assertEqual(risultati, [tutti])

    def test_nessun_rumore_se_manca_il_nome(self):
        self._articolo('Addio a un grande attore', 'La morte del noto attore.')
        risultati = self.servizio._search_articles({'keywords': ['alex bernardi', 'morte']})
        self.assertEqual(risultati, [])
        self.assertEqual(self.servizio.termini_mancanti, ['alex bernardi'])

    def test_titolo_prima_del_testo(self):
        nel_testo = self._articolo('Consiglio comunale', 'Si è parlato anche di Aimag.', giorni_fa=1)
        nel_titolo = self._articolo('Aimag, i conti del 2026', 'Il bilancio di Aimag.', giorni_fa=30)
        risultati = self.servizio._search_articles({'keywords': ['aimag']})
        self.assertEqual(risultati, [nel_titolo, nel_testo])

    def test_eventi_per_data_evento_e_programmati_esclusi(self):
        domani = timezone.localdate() + timedelta(days=1)
        evento = self._articolo('Concerto in piazza', 'Musica dal vivo.', data_evento=domani)
        self._articolo('Articolo programmato', 'Concerto.', giorni_fa=-2)
        intent = {'keywords': ['eventi'], 'data_da': domani.isoformat(), 'data_a': domani.isoformat(),
                  'campo_data': 'evento'}
        self.assertEqual(self.servizio._search_articles(intent), [evento])
        self.assertEqual(self.servizio._search_articles({'keywords': ['concerto']}), [evento])

    def test_vecchio_timeframe_weekend_eventi_guarda_avanti(self):
        da, a = self.servizio._range_da_timeframe('weekend', futuro=True)
        self.assertGreaterEqual(da, timezone.localdate())
        self.assertIn(a.weekday(), (5, 6))
