"""
Servizio chatbot per Ombra del Portico
Analizza le richieste degli utenti e restituisce articoli pertinenti
"""

import logging
import re
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q
import anthropic
from django.conf import settings

from .models import Articolo
from .api_usage_tracker import APIUsageTracker

logger = logging.getLogger(__name__)


class ChatbotService:
    """Servizio per gestire le conversazioni del chatbot"""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def process_message(self, user_message, conversation_history=None):
        """
        Processa un messaggio dell'utente e restituisce una risposta

        Args:
            user_message: Il messaggio dell'utente
            conversation_history: Lista di messaggi precedenti (opzionale)

        Returns:
            dict con response (testo risposta) e articles (lista articoli)
        """
        try:
            # Analizza l'intento dell'utente usando Claude
            intent = self._analyze_intent(user_message)

            logger.info(f"Chatbot intent: {intent}")

            # Cerca articoli in base all'intento
            articles = self._search_articles(intent)

            # Genera risposta
            response = self._generate_response(intent, articles, user_message)

            # Per le domande, restituisci solo gli articoli effettivamente analizzati dall'AI
            articles_to_return = articles
            if intent.get('request_type') == 'question' and articles:
                articles_to_read = min(intent.get('articles_needed', 3), len(articles))
                articles_to_return = articles[:articles_to_read]
                logger.info(f"Question type: restituiti {len(articles_to_return)} articoli analizzati su {len(articles)} trovati")

            return {
                'response': response,
                'articles': [self._serialize_article(a) for a in articles_to_return],
                'intent': intent
            }

        except Exception as e:
            logger.error(f"Errore chatbot: {e}", exc_info=True)
            return {
                'response': "Mi dispiace, si è verificato un errore. Riprova più tardi.",
                'articles': [],
                'intent': {}
            }

    def _analyze_intent(self, user_message):
        """
        Usa Claude per analizzare l'intento dell'utente
        Estrae: keywords, timeframe, categoria, tipo di richiesta
        """

        system_prompt = """Sei un assistente che analizza richieste su un sito di notizie locali (Carpi, Italia).
Devi estrarre informazioni strutturate dalle richieste degli utenti.

IMPORTANTE:
- NON includere "carpi" nelle keywords (è ridondante, tutto il sito parla di Carpi)
- NON includere articoli, preposizioni o congiunzioni (il, lo, la, al, alla, del, della, di, da, a, e, o)
- Correggi errori di battitura evidenti (es. "sivurezza" -> "sicurezza")
- Usa categoria SOLO per richieste generiche ("ultime notizie di sport")
- Per ricerche specifiche (es. "rugby") NON usare categoria, usa solo keywords
- DOMANDE APERTE (chi/cosa/quando/dove/perché): usa request_type "question"
- Per domande su RELAZIONI tra entità (es. "cosa è successo tra X e Y"), usa articles_needed: 10
- Per domande semplici su fatti specifici, usa articles_needed: 1-3
- Per domande generiche o complesse, usa articles_needed: 5-10

Restituisci SOLO un JSON valido con questa struttura:
{
    "keywords": ["parola1", "parola2"],
    "timeframe": "oggi|ieri|weekend|lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica|settimana|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|mese|null",
    "categoria": "Sport|Cronaca|Cultura & Eventi|Attualità|Politica|null",
    "entity": "nome persona/organizzazione se menzionata|null",
    "request_type": "search|latest|help|greeting|question",
    "articles_needed": 1-10 (solo per question, numero articoli da analizzare)
}

Esempi:
- "Trovami articoli su Aimag" -> {"keywords": ["aimag"], "timeframe": null, "categoria": null, "entity": "Aimag", "request_type": "search", "articles_needed": 0}
- "Cosa è successo tra Aimag e Hera?" -> {"keywords": ["aimag", "hera"], "timeframe": null, "categoria": null, "entity": null, "request_type": "question", "articles_needed": 10}
- "Chi è il sindaco di Campogalliano?" -> {"keywords": ["sindaco", "campogalliano"], "timeframe": null, "categoria": null, "entity": "sindaco", "request_type": "question", "articles_needed": 3}
- "Eventi del weekend" -> {"keywords": ["eventi"], "timeframe": "weekend", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Eventi di ieri" -> {"keywords": ["eventi"], "timeframe": "ieri", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Cosa è successo lunedì?" -> {"keywords": [], "timeframe": "lunedi", "categoria": null, "entity": null, "request_type": "question", "articles_needed": 5}
- "Notizie di ottobre" -> {"keywords": [], "timeframe": "ottobre", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Cosa è successo questa settimana?" -> {"keywords": [], "timeframe": "settimana", "categoria": null, "entity": null, "request_type": "question", "articles_needed": 8}
- "Ultime notizie di sport" -> {"keywords": [], "timeframe": null, "categoria": "Sport", "entity": null, "request_type": "latest", "articles_needed": 0}
- "Rugby" -> {"keywords": ["rugby"], "timeframe": null, "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
"""

        try:
            message = self.client.messages.create(
                model="claude-3-5-haiku-20241022",  # Modello veloce ed economico
                max_tokens=500,
                temperature=0.1,  # Bassa temperatura per risposte più deterministiche
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": user_message
                }]
            )

            # Traccia utilizzo API
            APIUsageTracker.track_anthropic(
                operation='chatbot_intent_analysis',
                model='claude-3-5-haiku-20241022',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            # Estrai il JSON dalla risposta
            response_text = message.content[0].text.strip()

            # Rimuovi markdown code blocks se presenti
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json?\s*|\s*```$', '', response_text, flags=re.MULTILINE)

            intent = json.loads(response_text)

            logger.info(f"Intent estratto da '{user_message}': {intent}")
            logger.info(f"Keywords estratte: {intent.get('keywords', [])}")
            return intent

        except Exception as e:
            logger.error(f"Errore analisi intent: {e}", exc_info=True)
            # Fallback: analisi semplice basata su regex
            return self._simple_intent_analysis(user_message)

    def _simple_intent_analysis(self, message):
        """Fallback: analisi semplice senza AI"""
        message_lower = message.lower()

        intent = {
            'keywords': [],
            'timeframe': None,
            'categoria': None,
            'entity': None,
            'request_type': 'search'
        }

        # Timeframe
        if any(word in message_lower for word in ['oggi', 'stasera']):
            intent['timeframe'] = 'oggi'
        elif 'ieri' in message_lower:
            intent['timeframe'] = 'ieri'
        elif any(word in message_lower for word in ['weekend', 'fine settimana']):
            intent['timeframe'] = 'weekend'
        elif any(word in message_lower for word in ['settimana', 'ultimi giorni']):
            intent['timeframe'] = 'settimana'

        # Giorni della settimana
        giorni = ['lunedì', 'lunedi', 'martedì', 'martedi', 'mercoledì', 'mercoledi',
                 'giovedì', 'giovedi', 'venerdì', 'venerdi', 'sabato', 'domenica']
        giorni_normalized = {'lunedì': 'lunedi', 'martedì': 'martedi', 'mercoledì': 'mercoledi',
                            'giovedì': 'giovedi', 'venerdì': 'venerdi'}
        for giorno in giorni:
            if giorno in message_lower:
                intent['timeframe'] = giorni_normalized.get(giorno, giorno)
                break

        # Mesi
        mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
               'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
        for mese in mesi:
            if mese in message_lower:
                intent['timeframe'] = mese
                break

        # Categorie
        if any(word in message_lower for word in ['sport', 'calcio', 'partita']):
            intent['categoria'] = 'Sport'
        elif any(word in message_lower for word in ['evento', 'eventi', 'cosa fare', 'cultura', 'teatro', 'mostra']):
            intent['categoria'] = 'Cultura & Eventi'

        # Keywords: estrai parole significative
        words = re.findall(r'\w+', message_lower)
        stopwords = ['il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'una', 'di', 'da', 'in', 'con',
                     'su', 'per', 'tra', 'fra', 'a', 'e', 'o', 'che', 'cosa', 'trovami',
                     'mostrami', 'cerca', 'articoli', 'notizie', 'mi', 'ti']
        intent['keywords'] = [w for w in words if w not in stopwords and len(w) > 3]

        return intent

    def _search_articles(self, intent):
        """
        Cerca articoli in base all'intento
        """
        logger.info(f"_search_articles chiamato con intent: {intent}")
        logger.info(f"Keywords ricevute per ricerca: {intent.get('keywords', [])}")
        query = Articolo.objects.filter(approvato=True)

        # Filtro temporale
        if intent.get('timeframe'):
            now = timezone.now()
            timeframe = intent['timeframe']

            if timeframe == 'oggi':
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(data_pubblicazione__gte=start_date)

            elif timeframe == 'ieri':
                yesterday = now - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(data_pubblicazione__gte=start_date, data_pubblicazione__lt=end_date)

            elif timeframe == 'weekend':
                # Weekend: sabato (5) e domenica (6) dell'ultima settimana
                days_since_saturday = (now.weekday() - 5) % 7
                if now.weekday() == 6:  # Oggi è domenica
                    saturday = now - timedelta(days=1)
                elif now.weekday() < 5:  # Lunedì-Venerdì: weekend passato
                    saturday = now - timedelta(days=days_since_saturday + 7)
                else:  # Sabato: questo weekend
                    saturday = now
                start_date = saturday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date + timedelta(days=2)
                query = query.filter(data_pubblicazione__gte=start_date, data_pubblicazione__lt=end_date)
                logger.info(f"Filtro weekend: {start_date} - {end_date}")

            elif timeframe in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']:
                # Mappa giorni della settimana a numeri (lunedì=0, domenica=6)
                giorni_map = {'lunedi': 0, 'martedi': 1, 'mercoledi': 2, 'giovedi': 3,
                             'venerdi': 4, 'sabato': 5, 'domenica': 6}
                target_weekday = giorni_map[timeframe]
                current_weekday = now.weekday()

                # Calcola quanti giorni fa era quel giorno della settimana
                if current_weekday >= target_weekday:
                    days_ago = current_weekday - target_weekday
                else:
                    days_ago = 7 - (target_weekday - current_weekday)

                target_date = now - timedelta(days=days_ago)
                start_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date + timedelta(days=1)
                query = query.filter(data_pubblicazione__gte=start_date, data_pubblicazione__lt=end_date)
                logger.info(f"Filtro {timeframe}: {start_date} - {end_date}")

            elif timeframe in ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                              'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']:
                # Mappa mesi a numeri
                mesi_map = {'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5,
                           'giugno': 6, 'luglio': 7, 'agosto': 8, 'settembre': 9,
                           'ottobre': 10, 'novembre': 11, 'dicembre': 12}
                target_month = mesi_map[timeframe]

                # Se il mese è nel futuro, usa l'anno scorso
                if target_month > now.month:
                    year = now.year - 1
                else:
                    year = now.year

                # Primo giorno del mese
                start_date = datetime(year, target_month, 1)
                # Primo giorno del mese successivo
                if target_month == 12:
                    end_date = datetime(year + 1, 1, 1)
                else:
                    end_date = datetime(year, target_month + 1, 1)

                # Converti a timezone-aware
                start_date = timezone.make_aware(start_date)
                end_date = timezone.make_aware(end_date)

                query = query.filter(data_pubblicazione__gte=start_date, data_pubblicazione__lt=end_date)
                logger.info(f"Filtro {timeframe} {year}: {start_date} - {end_date}")

            elif timeframe == 'settimana':
                start_date = now - timedelta(days=7)
                query = query.filter(data_pubblicazione__gte=start_date)

            elif timeframe == 'mese':
                start_date = now - timedelta(days=30)
                query = query.filter(data_pubblicazione__gte=start_date)

        # Filtro categoria
        if intent.get('categoria'):
            query = query.filter(categoria__iexact=intent['categoria'])

        # Filtro keywords
        keywords = intent.get('keywords', [])

        # LOGICA SPECIALE: se keyword è "eventi" o "cultura" con timeframe, usa data_evento
        if keywords in [['eventi'], ['cultura']] and intent.get('timeframe'):
            timeframe = intent['timeframe']
            # Categoria unificata: "Cultura & Eventi"
            categoria = 'Cultura & Eventi'
            logger.info(f"Keyword '{keywords[0]}' con timeframe: cerco in categoria {categoria} usando data_evento")

            # Cerca articoli Cultura & Eventi con data_evento nel range temporale
            # Riapplica i filtri temporali ma su data_evento invece di data_pubblicazione
            query_eventi = Articolo.objects.filter(approvato=True, categoria__iexact=categoria)

            # Calcola date range (come sopra ma per data_evento)
            now = timezone.now()
            start_date = None
            end_date = None

            if timeframe == 'oggi':
                start_date = now.date()
                end_date = start_date
            elif timeframe == 'ieri':
                yesterday = now - timedelta(days=1)
                start_date = yesterday.date()
                end_date = start_date
            elif timeframe == 'weekend':
                days_since_saturday = (now.weekday() - 5) % 7
                if now.weekday() == 6:
                    saturday = now - timedelta(days=1)
                elif now.weekday() < 5:
                    saturday = now - timedelta(days=days_since_saturday + 7)
                else:
                    saturday = now
                start_date = saturday.date()
                end_date = (saturday + timedelta(days=1)).date()
            elif timeframe in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']:
                giorni_map = {'lunedi': 0, 'martedi': 1, 'mercoledi': 2, 'giovedi': 3,
                             'venerdi': 4, 'sabato': 5, 'domenica': 6}
                target_weekday = giorni_map[timeframe]
                current_weekday = now.weekday()
                if current_weekday >= target_weekday:
                    days_ago = current_weekday - target_weekday
                else:
                    days_ago = 7 - (target_weekday - current_weekday)
                target_date = now - timedelta(days=days_ago)
                start_date = target_date.date()
                end_date = start_date
            elif timeframe in ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                              'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']:
                mesi_map = {'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5,
                           'giugno': 6, 'luglio': 7, 'agosto': 8, 'settembre': 9,
                           'ottobre': 10, 'novembre': 11, 'dicembre': 12}
                target_month = mesi_map[timeframe]
                if target_month > now.month:
                    year = now.year - 1
                else:
                    year = now.year
                from datetime import date
                start_date = date(year, target_month, 1)
                if target_month == 12:
                    end_date = date(year, 12, 31)
                else:
                    end_date = date(year, target_month + 1, 1) - timedelta(days=1)
            elif timeframe == 'settimana':
                start_date = (now - timedelta(days=7)).date()
                end_date = now.date()
            elif timeframe == 'mese':
                start_date = (now - timedelta(days=30)).date()
                end_date = now.date()

            if start_date and end_date:
                if start_date == end_date:
                    query_eventi = query_eventi.filter(data_evento=start_date)
                else:
                    query_eventi = query_eventi.filter(data_evento__gte=start_date, data_evento__lte=end_date)
                articles_eventi = list(query_eventi.order_by('data_evento'))
                logger.info(f"Trovati {len(articles_eventi)} articoli {categoria} con data_evento tra {start_date} e {end_date}")
                if articles_eventi:
                    return articles_eventi
                logger.info(f"Nessun articolo {categoria} con data_evento, continuo con ricerca standard")
        if keywords:
            # Prova prima con AND (articoli che contengono TUTTE le parole)
            # Usa regex con word boundary per cercare parole intere
            query_and = query
            for keyword in keywords:
                # \b = word boundary, cerca solo parole intere
                regex_pattern = rf'\b{keyword}\b'
                # AND: ogni keyword deve essere presente in titolo o contenuto
                keyword_query = Q(titolo__iregex=regex_pattern) | Q(contenuto__iregex=regex_pattern)
                query_and = query_and.filter(keyword_query)

            # Converti in lista per contare
            articles_and = list(query_and.order_by('-data_pubblicazione'))

            if articles_and:
                # Trovati risultati con AND
                logger.info(f"Filtro keywords applicato (AND): {keywords} - {len(articles_and)} articoli")
                # Ordina per rilevanza: prima articoli con keyword nel titolo, poi per data
                articles_list = self._sort_by_relevance(articles_and, keywords)
            else:
                # Nessun risultato con AND, riprova con OR
                logger.info(f"AND non ha trovato risultati, provo con OR: {keywords}")
                keyword_query_or = Q()
                for keyword in keywords:
                    regex_pattern = rf'\b{keyword}\b'
                    keyword_query_or |= Q(titolo__iregex=regex_pattern) | Q(contenuto__iregex=regex_pattern)
                query_or = query.filter(keyword_query_or)
                articles_or = list(query_or.order_by('-data_pubblicazione'))
                logger.info(f"Filtro keywords applicato (OR fallback): {keywords} - {len(articles_or)} articoli")
                # Ordina per rilevanza anche con OR
                articles_list = self._sort_by_relevance(articles_or, keywords)
        else:
            # Nessuna keyword, usa query base
            articles_list = list(query.order_by('-data_pubblicazione'))

        logger.info(f"Trovati {len(articles_list)} articoli per intent: {intent}")

        return articles_list

    def _strip_links_from_content(self, content):
        """
        Rimuove link markdown e HTML dal contenuto per evitare match su URL
        """
        import re
        # Rimuovi link markdown [testo](url) mantenendo solo il testo
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
        # Rimuovi tag HTML <a href="...">testo</a> mantenendo solo il testo
        content = re.sub(r'<a[^>]*>([^<]*)</a>', r'\1', content, flags=re.IGNORECASE)
        # Rimuovi altri tag HTML
        content = re.sub(r'<[^>]+>', '', content)
        return content

    def _sort_by_relevance(self, articles, keywords):
        """
        Ordina articoli per rilevanza:
        1. Articoli con TUTTE le keywords nel titolo (priorità massima)
        2. Articoli con ALMENO UNA keyword nel titolo
        3. Articoli con keywords nel contenuto VISIBILE (esclude link)
        Dentro ogni gruppo, ordina per data pubblicazione (più recente prima)
        """
        if not keywords or not articles:
            return articles

        title_all = []  # Tutte le keywords nel titolo
        title_some = []  # Almeno una keyword nel titolo
        content_only = []  # Keywords nel contenuto visibile

        for article in articles:
            title_lower = article.titolo.lower()
            # Rimuovi link dal contenuto prima di cercare
            clean_content = self._strip_links_from_content(article.contenuto)
            content_lower = clean_content.lower()

            # Conta quante keywords sono nel titolo
            keywords_in_title = sum(1 for kw in keywords if kw.lower() in title_lower)

            if keywords_in_title == len(keywords):
                title_all.append(article)
            elif keywords_in_title > 0:
                title_some.append(article)
            else:
                # Verifica se le keywords sono nel contenuto PULITO (senza link)
                keywords_in_clean_content = sum(1 for kw in keywords if kw.lower() in content_lower)
                if keywords_in_clean_content > 0:
                    content_only.append(article)
                else:
                    logger.debug(f"Escluso '{article.titolo[:50]}...' - keyword solo in link")

        # Ordina ogni gruppo per data pubblicazione
        title_all.sort(key=lambda a: a.data_pubblicazione, reverse=True)
        title_some.sort(key=lambda a: a.data_pubblicazione, reverse=True)
        content_only.sort(key=lambda a: a.data_pubblicazione, reverse=True)

        # Combina i gruppi
        result = title_all + title_some + content_only

        logger.info(f"Rilevanza: {len(title_all)} con tutte keywords in titolo, "
                   f"{len(title_some)} con alcune in titolo, {len(content_only)} nel contenuto visibile")

        return result

    def _generate_response(self, intent, articles, user_message):
        """
        Genera una risposta testuale in base ai risultati
        """
        request_type = intent.get('request_type', 'search')

        # Gestisci richieste speciali (chi siamo, contatti, ecc.)
        user_message_lower = user_message.lower()
        if any(phrase in user_message_lower for phrase in ['chi siamo', 'chi sei', 'cosa fai', 'informazioni sul sito']):
            return ("Ombra del Portico è il portale di notizie di Carpi.\n\nPer saperne di più su di noi, visita la pagina [Chi Siamo](/about/)")

        if any(phrase in user_message_lower for phrase in ['contatti', 'contattare', 'email', 'scrivere']):
            return ("📧 **Contatti**\n\nPer contattare Ombra del Portico:\n\n**Email:** info@ombradelportico.it\n\nSaremo felici di rispondere alle tue domande!")

        # Gestisci saluti
        if request_type == 'greeting':
            return ("Ciao! Sono l'assistente virtuale di Ombra del Portico.\n\n"
                   "Posso aiutarti a cercare tra gli articoli pubblicati sul sito. "
                   "Fai una domanda o chiedi di un argomento specifico e ti mostrerò tutti gli articoli pertinenti.\n\n"
                   "Esempi:\n"
                   "• \"Cosa è successo questa settimana a Carpi?\"\n"
                   "• \"Ultime notizie di sport\"\n"
                   "• \"Articoli su Aimag\"\n"
                   "• \"Eventi del weekend\"")

        # Gestisci richieste di aiuto
        if request_type == 'help':
            return ("Posso aiutarti a trovare articoli su Ombra del Portico!\n\n"
                   "Esempi di ricerca:\n"
                   "• \"Ultime notizie di sport\"\n"
                   "• \"Cosa è successo ieri a Carpi\"\n"
                   "• \"Eventi questo weekend\"\n"
                   "• \"Articoli su Aimag\"\n\n"
                   "Cosa vuoi cercare?")

        # Nessun risultato
        if not articles:
            keywords_text = ", ".join(intent.get('keywords', [])) if intent.get('keywords') else "questa ricerca"
            return f"Non ho trovato articoli recenti su {keywords_text}. Prova a riformulare la domanda o cerca un altro argomento."

        # Risultati trovati - risposta con presentazione articoli
        count = len(articles)

        # Per domande, genera breve introduzione con AI
        if request_type == 'question':
            return self._generate_brief_intro(user_message, articles, intent)

        # Per ricerche normali, risposta standard
        # Costruisci risposta
        if intent.get('timeframe') == 'oggi':
            response = f"Ho trovato {count} articol{'o' if count == 1 else 'i'} di oggi"
        elif intent.get('timeframe') == 'ieri':
            response = f"Ho trovato {count} articol{'o' if count == 1 else 'i'} di ieri"
        else:
            response = f"Ho trovato {count} articol{'o' if count == 1 else 'i'}"

        if intent.get('keywords'):
            keywords_text = ", ".join(intent['keywords'][:3])  # Max 3 keywords
            response += f" su {keywords_text}"

        if intent.get('categoria'):
            response += f" nella categoria {intent['categoria']}"

        response += ":"

        return response

    def _generate_brief_intro(self, question, articles, intent):
        """
        Genera una breve introduzione (1-2 frasi) che presenta gli articoli trovati
        Stringata, senza scuse o giustificazioni
        """
        count = len(articles)
        articles_to_read = min(intent.get('articles_needed', 3), len(articles))

        # Prepara contesto dai primi articoli (titolo + contenuto completo)
        context_parts = []
        for article in articles[:articles_to_read]:
            context_parts.append(f"Titolo: {article.titolo}\n\nContenuto:\n{article.contenuto}")

        context = "\n---\n".join(context_parts)

        system_prompt = """Sei un assistente che presenta brevemente articoli di notizie.

ISTRUZIONI:
- Scrivi 1-2 frasi massimo che introducono gli articoli trovati
- Sii diretto e stringato
- NON scusarti o giustificarti
- NON dire "ho trovato" o "ecco cosa ho trovato"
- Presenta direttamente il tema degli articoli
- Usa tono informativo e professionale

Esempio:
Domanda: "Cosa è successo tra Aimag e Hera?"
Risposta: "Gli articoli riguardano la fusione tra Aimag e Hera, con aggiornamenti sui tempi e le modalità dell'operazione."

Domanda: "Cosa è successo ieri in corso Cabassi?"
Risposta: "Un episodio di cronaca ha coinvolto corso Cabassi ieri, con intervento delle forze dell'ordine."""

        try:
            message = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=150,
                temperature=0.3,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"Domanda: {question}\n\nArticoli:\n{context}\n\nIntroduzione breve (1-2 frasi):"
                }]
            )

            # Traccia utilizzo API
            APIUsageTracker.track_anthropic(
                operation='chatbot_brief_intro',
                model='claude-3-5-haiku-20241022',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            intro = message.content[0].text.strip()
            return intro

        except Exception as e:
            logger.error(f"Errore generazione intro: {e}", exc_info=True)
            # Fallback: risposta standard
            if intent.get('keywords'):
                keywords_text = ", ".join(intent['keywords'][:2])
                return f"Ecco {count} articol{'o' if count == 1 else 'i'} su {keywords_text}:"
            return f"Ecco {count} articol{'o' if count == 1 else 'i'} che potrebbero interessarti:"

    def _answer_question(self, question, articles, intent):
        """
        Genera una risposta intelligente a una domanda usando il contenuto degli articoli
        """
        # Determina quanti articoli leggere (default 3, max 10)
        articles_to_read = min(intent.get('articles_needed', 3), len(articles), 10)

        if articles_to_read == 0:
            return "Non ho trovato informazioni sufficienti per rispondere alla tua domanda."

        # Prepara il contesto dagli articoli
        context_parts = []
        sources = []

        for i, article in enumerate(articles[:articles_to_read]):
            context_parts.append(f"""
Articolo {i+1}: {article.titolo}
Data: {article.data_pubblicazione.strftime('%d/%m/%Y')}
Categoria: {article.categoria}

Contenuto:
{article.contenuto}
""")
            sources.append(f"[{article.titolo}](/articolo/{article.slug}/)")

        context = "\n---\n".join(context_parts)

        # Genera risposta con Claude
        system_prompt = """Sei un assistente che risponde a domande basandoti ESCLUSIVAMENTE sulle informazioni contenute negli articoli forniti.

REGOLE IMPORTANTI:
- Rispondi SOLO se trovi la risposta negli articoli
- Se la risposta non è negli articoli, dillo chiaramente
- Sii conciso e preciso (massimo 2-3 frasi)
- Usa un tono informale e amichevole
- NON inventare informazioni
- Cita sempre la fonte alla fine della risposta"""

        try:
            message = self.client.messages.create(
                model="claude-3-5-haiku-20241022",  # Stesso modello dell'intent
                max_tokens=500,
                temperature=0.3,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"""Domanda: {question}

Articoli disponibili:
{context}

Rispondi alla domanda in modo conciso."""
                }]
            )

            # Traccia utilizzo API
            APIUsageTracker.track_anthropic(
                operation='chatbot_question_answering',
                model='claude-3-5-haiku-20241022',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            answer = message.content[0].text.strip()

            # Aggiungi fonte se non già presente
            if articles_to_read == 1 and not any(src in answer for src in sources):
                answer += f"\n\n📰 Fonte: {sources[0]}"
            elif articles_to_read > 1:
                answer += f"\n\n📰 Fonti consultate: {articles_to_read} articoli"

            return answer

        except Exception as e:
            logger.error(f"Errore generazione risposta: {e}", exc_info=True)
            return f"Ho trovato {articles_to_read} articol{'o' if articles_to_read == 1 else 'i'} rilevant{'e' if articles_to_read == 1 else 'i'}, ma ho avuto difficoltà a elaborare la risposta. Prova a riformulare la domanda."

    def _serialize_article(self, article):
        """Serializza un articolo per la risposta JSON"""
        return {
            'id': article.id,
            'slug': article.slug,
            'titolo': article.titolo,
            'sommario': article.sommario[:200] + '...' if len(article.sommario) > 200 else article.sommario,
            'categoria': article.categoria,
            'data_pubblicazione': article.data_pubblicazione.isoformat(),
            'foto': article.foto if article.foto else None,
            'url': f'/articolo/{article.slug}/'
        }
