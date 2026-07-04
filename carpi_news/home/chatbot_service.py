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

    # Modello Claude usato quando provider='anthropic'
    ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"

    # Numero massimo di articoli restituiti al frontend (evita di passarne migliaia)
    MAX_ARTICLES_DISPLAY = 10

    def __init__(self):
        # Client Anthropic sempre disponibile (default + fallback)
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        # Selezione provider (POC OpenRouter). Default 'anthropic' = comportamento invariato.
        self.provider = getattr(settings, 'CHATBOT_PROVIDER', 'anthropic')
        self.or_client = None
        self.model = self.ANTHROPIC_MODEL

        if self.provider == 'openrouter':
            or_key = getattr(settings, 'OPENROUTER_API_KEY', '')
            if or_key:
                from openai import OpenAI
                self.or_client = OpenAI(
                    base_url=getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'),
                    api_key=or_key,
                    default_headers={
                        'HTTP-Referer': 'https://ombradelportico.it',
                        'X-Title': 'Ombra del Portico',
                    },
                )
                self.model = getattr(settings, 'OPENROUTER_CHATBOT_MODEL', 'deepseek/deepseek-chat')
                logger.info(f"Chatbot: provider OpenRouter attivo, modello {self.model}")
            else:
                # Provider richiesto ma chiave assente: torna ad Anthropic per sicurezza
                logger.warning("CHATBOT_PROVIDER=openrouter ma OPENROUTER_API_KEY assente: uso Anthropic")
                self.provider = 'anthropic'

    def _chat(self, system_prompt, user_content, max_tokens, temperature, operation):
        """
        Chiamata LLM astratta sul provider attivo.

        Ritorna il testo della risposta (già .strip()) e traccia l'utilizzo.
        Con provider='anthropic' il comportamento è identico al codice originale.
        Eventuali eccezioni sono propagate ai chiamanti (che hanno già i loro fallback).
        """
        if self.provider == 'openrouter' and self.or_client is not None:
            response = self.or_client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            text = (response.choices[0].message.content or "").strip()
            usage = getattr(response, 'usage', None)
            APIUsageTracker.track_openrouter(
                operation=operation,
                model=self.model,
                input_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                output_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                success=True,
            )
            return text

        # Default: Anthropic
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        APIUsageTracker.track_anthropic(
            operation=operation,
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            success=True,
        )
        return message.content[0].text.strip()

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

            # Rete di sicurezza: domande fattuali a volte classificate male come 'search'
            intent = self._coerce_question_intent(user_message, intent)

            logger.info(f"Chatbot intent: {intent}")

            # Cerca articoli in base all'intento
            articles = self._search_articles(intent)

            # Genera risposta
            response = self._generate_response(intent, articles, user_message)

            # Risposte informative (saluti, aiuto, meta) non mostrano articoli
            if intent.get('request_type') in ('greeting', 'help'):
                articles_to_return = []
            else:
                # Limita SEMPRE gli articoli restituiti al frontend (evita payload da migliaia di articoli)
                articles_to_return = articles[:self.MAX_ARTICLES_DISPLAY]
                if intent.get('request_type') == 'question' and articles:
                    # Per le domande, restituisci solo gli articoli effettivamente analizzati dall'AI
                    articles_to_read = min(intent.get('articles_needed', 3), len(articles), self.MAX_ARTICLES_DISPLAY)
                    articles_to_return = articles[:articles_to_read]
                    logger.info(f"Question type: restituiti {len(articles_to_return)} articoli analizzati su {len(articles)} trovati")
                elif len(articles) > self.MAX_ARTICLES_DISPLAY:
                    logger.info(f"Ricerca: {len(articles)} articoli trovati, restituiti primi {self.MAX_ARTICLES_DISPLAY}")

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

    # Parole interrogative che identificano una domanda fattuale
    _QUESTION_STARTERS = (
        'chi', 'quando', 'dove', 'perché', 'perche', 'quanto', 'quanti',
        'quante', 'quanta', 'quale', 'quali', 'come', "cos'è", 'cosa', 'che',
    )
    # Frasi che sembrano domande ma sono in realtà ricerche di eventi/attività
    _QUESTION_EXCLUSIONS = ('cosa fare', 'che fare', 'cosa c', 'cosa succede stasera')
    # Frasi meta/informative sul bot o sul sito -> vanno trattate come 'help'
    # (non si risponde pescando dagli articoli)
    _INFO_PHRASES = (
        'cosa puoi fare', 'cosa sai fare', 'come funzioni', 'a cosa servi',
        'come ti uso', 'come posso usarti', 'chi siamo', 'chi sei', 'cosa fai',
        'informazioni sul sito', 'contatti', 'contattare',
    )

    def _coerce_question_intent(self, message, intent):
        """Forza request_type='question' quando il messaggio è chiaramente una domanda
        ma l'AI l'ha classificato diversamente (es. 'Chi è il sindaco di Carpi').
        """
        try:
            if not isinstance(intent, dict):
                return intent
            m = (message or '').strip().lower()
            if not m:
                return intent
            # Frasi meta/informative ("cosa puoi fare", "chi siamo", "contatti") -> help
            if any(p in m for p in self._INFO_PHRASES):
                intent['request_type'] = 'help'
                return intent
            # Frasi-evento ("cosa fare stasera"): sono ricerche di eventi, non domande
            if any(m.startswith(x) for x in self._QUESTION_EXCLUSIONS):
                if intent.get('request_type') == 'question':
                    intent['request_type'] = 'search'
                return intent
            if intent.get('request_type') == 'question':
                return intent
            first_word = m.split()[0]
            looks_like_question = m.endswith('?') or first_word in self._QUESTION_STARTERS
            if looks_like_question:
                intent['request_type'] = 'question'
                if not intent.get('articles_needed') or intent.get('articles_needed', 0) < 1:
                    intent['articles_needed'] = 5
                logger.info(f"Intent forzato a 'question' da euristica per: '{message}'")
        except Exception as e:
            logger.warning(f"Errore in _coerce_question_intent: {e}")
        return intent

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
- Usa categoria SOLO per richieste esplicitamente generiche senza argomento specifico ("ultime notizie di sport", "ultime notizie di cultura")
- Per ricerche con argomenti specifici (es. "rugby", "teatro", "ragazzi irresistibili") NON usare categoria, usa SOLO keywords
- Se l'utente menziona qualcosa di specifico (nome, evento, argomento), categoria DEVE essere null
- DOMANDE APERTE (chi/cosa/quando/dove/perché): usa request_type "question"
- Per domande su RELAZIONI tra entità (es. "cosa è successo tra X e Y"), usa articles_needed: 10
- Per domande semplici su fatti specifici, usa articles_needed: 1-3
- Per domande generiche o complesse, usa articles_needed: 5-10
- NOMI DI LUOGHI COMPOSTI: "San Marino", "San Prospero", "San Pietro" ecc. NON separare, tieni come keywords: ["san marino"], ["san prospero"]
- NOMI E COGNOMI: se entity è un nome persona, aggiungi anche come singola keyword (es. entity: "Eola Papazzoni" -> keywords: ["eola papazzoni", "polisportiva"])
- DERIVATI: per "San Marino" cerca anche "san marinese", "marinese"; per "San Prospero" cerca anche "san prosperese"

Restituisci SOLO un JSON valido con questa struttura:
{
    "keywords": ["parola1", "parola2"],
    "timeframe": "oggi|domani|ieri|weekend|lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica|settimana|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|mese|null",
    "categoria": "Sport|Cronaca|Cultura & Eventi|Attualità|Politica|null",
    "entity": "nome persona/organizzazione se menzionata|null",
    "request_type": "search|latest|help|greeting|question",
    "articles_needed": 1-10 (solo per question, numero articoli da analizzare)
}

Esempi:
- "Trovami articoli su Aimag" -> {"keywords": ["aimag"], "timeframe": null, "categoria": null, "entity": "Aimag", "request_type": "search", "articles_needed": 0}
- "eola papazzoni san marino" -> {"keywords": ["eola papazzoni", "san marinese"], "timeframe": null, "categoria": null, "entity": "Eola Papazzoni", "request_type": "search", "articles_needed": 0}
- "i ragazzi irresistibili a teatro" -> {"keywords": ["ragazzi", "irresistibili", "teatro"], "timeframe": null, "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Cosa è successo tra Aimag e Hera?" -> {"keywords": ["aimag", "hera"], "timeframe": null, "categoria": null, "entity": null, "request_type": "question", "articles_needed": 10}
- "Chi è il sindaco di Campogalliano?" -> {"keywords": ["sindaco", "campogalliano"], "timeframe": null, "categoria": null, "entity": "sindaco", "request_type": "question", "articles_needed": 3}
- "Eventi di domani" -> {"keywords": ["eventi"], "timeframe": "domani", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Eventi del weekend" -> {"keywords": ["eventi"], "timeframe": "weekend", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Eventi di ieri" -> {"keywords": ["eventi"], "timeframe": "ieri", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Cosa è successo lunedì?" -> {"keywords": [], "timeframe": "lunedi", "categoria": null, "entity": null, "request_type": "question", "articles_needed": 5}
- "Notizie di ottobre" -> {"keywords": [], "timeframe": "ottobre", "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Cosa è successo questa settimana?" -> {"keywords": [], "timeframe": "settimana", "categoria": null, "entity": null, "request_type": "question", "articles_needed": 8}
- "Ultime notizie di sport" -> {"keywords": [], "timeframe": null, "categoria": "Sport", "entity": null, "request_type": "latest", "articles_needed": 0}
- "Ultime notizie di cultura" -> {"keywords": [], "timeframe": null, "categoria": "Cultura & Eventi", "entity": null, "request_type": "latest", "articles_needed": 0}
- "Rugby" -> {"keywords": ["rugby"], "timeframe": null, "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Teatro a Carpi" -> {"keywords": ["teatro"], "timeframe": null, "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Mario Rossi San Prospero" -> {"keywords": ["mario rossi", "san prosperese"], "timeframe": null, "categoria": null, "entity": "Mario Rossi", "request_type": "search", "articles_needed": 0}
"""

        try:
            # Bassa temperatura per risposte più deterministiche (JSON)
            response_text = self._chat(
                system_prompt=system_prompt,
                user_content=user_message,
                max_tokens=500,
                temperature=0.1,
                operation='chatbot_intent_analysis',
            )

            # Rimuovi markdown code blocks se presenti
            response_text = response_text.strip()
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json?\s*|\s*```$', '', response_text, flags=re.MULTILINE).strip()

            # Parser robusto: se il modello aggiunge testo attorno al JSON,
            # estrai comunque il primo oggetto {...} invece di cadere sul fallback regex
            try:
                intent = json.loads(response_text)
            except json.JSONDecodeError:
                match = re.search(r'\{.*\}', response_text, flags=re.DOTALL)
                if not match:
                    raise
                intent = json.loads(match.group(0))

            logger.info(f"Intent estratto da '{user_message}': {intent}")
            logger.info(f"Keywords estratte: {intent.get('keywords', [])}")
            return intent

        except Exception as e:
            # Fallback gestito (es. il modello non ha restituito JSON valido): analisi regex semplice
            logger.warning(f"Analisi intent AI non riuscita, uso fallback semplice: {e}")
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
        elif 'domani' in message_lower:
            intent['timeframe'] = 'domani'
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
        from django.db.models import Q
        query = Articolo.objects.filter(
            Q(is_pubbliredazionale=False, approvato=True) |
            Q(is_pubbliredazionale=True, approvato=True, payment_status='completed')
        )

        # Filtro temporale
        if intent.get('timeframe'):
            now = timezone.now()
            timeframe = intent['timeframe']

            if timeframe == 'oggi':
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(data_pubblicazione__gte=start_date)

            elif timeframe == 'domani':
                tomorrow = now + timedelta(days=1)
                start_date = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = (tomorrow + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(data_pubblicazione__gte=start_date, data_pubblicazione__lt=end_date)

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
            from django.db.models import Q
            query_eventi = Articolo.objects.filter(
                Q(is_pubbliredazionale=False, approvato=True) |
                Q(is_pubbliredazionale=True, approvato=True, payment_status='completed'),
                categoria__iexact=categoria
            )

            # Calcola date range (come sopra ma per data_evento)
            now = timezone.now()
            start_date = None
            end_date = None

            if timeframe == 'oggi':
                start_date = now.date()
                end_date = start_date
            elif timeframe == 'domani':
                tomorrow = now + timedelta(days=1)
                start_date = tomorrow.date()
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
            # Usa icontains per compatibilità PostgreSQL (iregex con \b non funziona)
            query_and = query
            for keyword in keywords:
                # AND: ogni keyword deve essere presente in titolo o contenuto
                keyword_query = Q(titolo__icontains=keyword) | Q(contenuto__icontains=keyword)
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
                    keyword_query_or |= Q(titolo__icontains=keyword) | Q(contenuto__icontains=keyword)
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

        # Per domande, genera una vera risposta basata sul contenuto degli articoli
        if request_type == 'question':
            return self._answer_question(user_message, articles, intent)

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
            intro = self._chat(
                system_prompt=system_prompt,
                user_content=f"Domanda: {question}\n\nArticoli:\n{context}\n\nIntroduzione breve (1-2 frasi):",
                max_tokens=150,
                temperature=0.3,
                operation='chatbot_brief_intro',
            )
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
- NON aggiungere righe "Fonte:" né riferimenti tipo "Articolo 1": le fonti vengono aggiunte automaticamente dal sistema dopo la tua risposta"""

        try:
            answer = self._chat(
                system_prompt=system_prompt,
                user_content=f"""Domanda: {question}

Articoli disponibili:
{context}

Rispondi alla domanda in modo conciso.""",
                max_tokens=500,
                temperature=0.3,
                operation='chatbot_question_answering',
            )

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
