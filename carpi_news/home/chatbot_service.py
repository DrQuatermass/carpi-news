"""
Servizio chatbot per Ombra del Portico
Analizza le richieste degli utenti e restituisce articoli pertinenti

Flusso: l'AI legge la richiesta (con data di oggi e ultimi messaggi della chat) e la traduce
in parole chiave, intervallo di date e tipo di richiesta; la ricerca prende dal database gli
articoli che contengono almeno un termine, poi li ordina in Python per pertinenza sul testo
senza HTML (parola intera, plurali, frasi) e tiene solo quelli che coprono meglio la richiesta.
Per le domande l'AI risponde leggendo i primi articoli.
"""

import html
import json
import logging
import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta

import anthropic
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .api_usage_tracker import APIUsageTracker
from .models import Articolo

logger = logging.getLogger(__name__)


GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto',
        'settembre', 'ottobre', 'novembre', 'dicembre']

# Parole che da sole non individuano un argomento (scartate se sono un termine a se')
STOPWORDS = {
    'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'di', 'da', 'in', 'con', 'su', 'per',
    'tra', 'fra', 'a', 'e', 'ed', 'o', 'od', 'che', 'chi', 'cosa', 'come', 'dove', 'quando',
    'quale', 'quali', 'quanto', 'quanti', 'del', 'dello', 'della', 'dei', 'degli', 'delle',
    'al', 'allo', 'alla', 'ai', 'agli', 'alle', 'dal', 'dallo', 'dalla', 'dai', 'dagli', 'dalle',
    'nel', 'nello', 'nella', 'nei', 'negli', 'nelle', 'sul', 'sullo', 'sulla', 'sui', 'sugli',
    'sulle', 'mi', 'ti', 'ci', 'vi', 'si', 'ne', 'non', 'piu', 'sono', 'sei', 'ha', 'hanno',
    'essere', 'avere', 'trovami', 'mostrami', 'cerca', 'cercami', 'dimmi', 'articoli',
    'articolo', 'notizie', 'notizia', 'news', 'carpi', 'successo', 'succede', 'ultime',
    'ultimi', 'ultima', 'ultimo', 'oggi', 'domani', 'ieri', 'ci', 'c', 'l', 'un', 'po',
}
# Parole che, in una ricerca per data dell'evento, indicano solo "eventi in generale"
PAROLE_EVENTO_GENERICHE = {
    'evento', 'eventi', 'iniziativa', 'iniziative', 'appuntamento', 'appuntamenti',
    'manifestazione', 'manifestazioni', 'fare', 'programma', 'programmi', 'spettacoli',
    'cultura', 'weekend', 'fine settimana', 'stasera', 'sera',
}

TIMEFRAME_LEGACY = ['oggi', 'domani', 'ieri', 'weekend', 'settimana', 'mese',
                    'lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica'] + MESI


def normalizza(testo):
    """Testo confrontabile: senza HTML, URL e accenti, minuscolo, spazi singoli."""
    testo = testo or ''
    testo = re.sub(r'\]\([^)]*\)', ']', testo)          # link markdown: resta il testo
    testo = re.sub(r'<[^>]+>', ' ', testo)              # tag HTML (anche <strong> dentro i nomi)
    testo = html.unescape(testo)
    testo = re.sub(r'https?://\S+', ' ', testo)
    testo = unicodedata.normalize('NFKD', testo)
    testo = ''.join(c for c in testo if not unicodedata.combining(c))
    testo = testo.lower().replace('’', "'").replace('‘', "'").replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', testo)


def _pattern_parola(tok):
    """Regex di una parola: le parole lunghe ammettono le desinenze (incidente/incidenti,
    accoltellato/accoltellata), quelle corte sono esatte ('arte' non trova 'parte')."""
    if any(ch.isdigit() for ch in tok):
        return re.escape(tok), tok
    if len(tok) >= 5 and tok[-1] in 'aeiou':
        radice = tok[:-1]
        return re.escape(radice) + r'[a-z]{0,2}', radice
    if len(tok) >= 5:
        return re.escape(tok) + r'[a-z]?', tok
    return re.escape(tok), tok


class Termine:
    """Una parola chiave della richiesta (anche una frase, anche con sinonimi 'a|b')."""

    def __init__(self, testo):
        self.testo = testo
        alternative = [normalizza(a).strip() for a in str(testo).split('|')]
        patterns = []
        self.prefissi = []  # pezzi per il filtro grezzo nel database (icontains)
        for alt in alternative:
            parole = [p for p in re.split(r"[\s'\-]+", alt) if p]
            if not parole:
                continue
            if len(parole) == 1 and (parole[0] in STOPWORDS or len(parole[0]) < 2):
                continue
            pezzi = [_pattern_parola(p) for p in parole]
            patterns.append(r"[\s'\-]+".join(p for p, _ in pezzi))
            # Nel database basta il pezzo piu' lungo (le frasi si verificano poi sul testo pulito:
            # 'Alex <strong>Bernardi</strong>' non contiene 'alex bernardi')
            self.prefissi.append(max((r for _, r in pezzi), key=len))
        self.valido = bool(patterns)
        self.regex = re.compile(r'(?<![a-z0-9])(?:' + '|'.join(patterns) + r')(?![a-z0-9])') if patterns else None

    def conta(self, testo):
        return len(self.regex.findall(testo)) if self.regex else 0


class ChatbotService:
    """Servizio per gestire le conversazioni del chatbot"""

    # Modello Claude usato quando provider='anthropic' (e come fallback di OpenRouter)
    ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

    # Numero massimo di articoli restituiti al frontend (evita di passarne migliaia)
    MAX_ARTICLES_DISPLAY = 10
    # Articoli letti al massimo dal database prima dell'ordinamento per pertinenza
    MAX_CANDIDATI = 1200
    # Messaggi della chat passati all'AI per capire le domande di seguito ("e domani?")
    MAX_STORICO_AI = 6

    def __init__(self):
        # Client Anthropic sempre disponibile (default + fallback)
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        # Selezione provider. Default 'anthropic'.
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
                logger.warning("CHATBOT_PROVIDER=openrouter ma OPENROUTER_API_KEY assente: uso Anthropic")
                self.provider = 'anthropic'

    # ------------------------------------------------------------------ chiamate AI

    def _chat(self, system_prompt, user_content, max_tokens, temperature, operation):
        """
        Chiamata LLM sul provider attivo. Ritorna il testo della risposta e traccia l'utilizzo.
        Le eccezioni passano ai chiamanti (che hanno i loro fallback).
        """
        if self.provider == 'openrouter' and self.or_client is not None:
            try:
                response = self.or_client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    # Con il ragionamento attivo i token finiscono li' e il contenuto torna vuoto
                    extra_body={"reasoning": {"enabled": False}},
                )
                text = (response.choices[0].message.content or "").strip()
                usage = getattr(response, 'usage', None)
                APIUsageTracker.track_openrouter(
                    operation=operation,
                    model=self.model,
                    input_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                    output_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                    success=bool(text),
                )
                if text:
                    return text
                logger.warning(f"OpenRouter contenuto vuoto per '{operation}', fallback ad Anthropic")
            except Exception as e:
                logger.warning(f"OpenRouter fallito per '{operation}' ({e}), fallback ad Anthropic")
            return self._chat_anthropic(system_prompt, user_content, max_tokens, temperature, operation)

        return self._chat_anthropic(system_prompt, user_content, max_tokens, temperature, operation)

    def _chat_anthropic(self, system_prompt, user_content, max_tokens, temperature, operation):
        """Chiamata a Claude: provider di default e fallback quando OpenRouter fallisce."""
        message = self.client.messages.create(
            model=self.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        APIUsageTracker.track_anthropic(
            operation=operation,
            model=self.ANTHROPIC_MODEL,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            success=True,
        )
        return message.content[0].text.strip()

    # ------------------------------------------------------------------ flusso principale

    def process_message(self, user_message, conversation_history=None):
        """
        Processa un messaggio dell'utente.

        Returns:
            dict con response (testo), articles (lista articoli serializzati), intent
        """
        try:
            storico = self._storico_testuale(conversation_history, user_message)

            intent = self._analyze_intent(user_message, storico)
            intent = self._coerce_question_intent(user_message, intent)
            logger.info(f"Chatbot intent: {intent}")

            request_type = intent.get('request_type')
            if request_type in ('greeting', 'help', 'feedback'):
                return {'response': self._generate_response(intent, [], user_message), 'articles': [],
                        'total_found': 0, 'intent': intent}

            articles = self._search_articles(intent)

            if request_type == 'question' and articles:
                da_leggere = self._articoli_da_leggere(intent, articles)
                response = self._answer_question(user_message, da_leggere, intent, storico)
                articles_to_return = da_leggere
            else:
                response = self._generate_response(intent, articles, user_message)
                quanti = self.MAX_ARTICLES_DISPLAY
                if request_type == 'latest' and intent.get('articles_needed'):
                    quanti = max(1, min(int(intent['articles_needed']), self.MAX_ARTICLES_DISPLAY))
                articles_to_return = articles[:quanti]

            return {
                'response': response,
                'articles': [self._serialize_article(a) for a in articles_to_return],
                'total_found': len(articles) if request_type != 'latest' else len(articles_to_return),
                'intent': intent,
            }

        except Exception as e:
            logger.error(f"Errore chatbot: {e}", exc_info=True)
            return {
                'response': "Mi dispiace, si è verificato un errore. Riprova più tardi.",
                'articles': [],
                'total_found': 0,
                'intent': {},
            }

    def _storico_testuale(self, conversation_history, user_message):
        """Ultimi messaggi della chat come testo ('Utente: ... / Assistente: ...').
        Il client manda anche il messaggio appena scritto: lo si toglie."""
        righe = []
        for m in (conversation_history or [])[-(self.MAX_STORICO_AI + 1):]:
            if not isinstance(m, dict):
                continue
            testo = str(m.get('text') or '').strip()
            if not testo or testo.startswith("Ti porto all'articolo"):
                continue
            chi = 'Utente' if m.get('type') == 'user' else 'Assistente'
            righe.append(f"{chi}: {testo[:400]}")
        if righe and righe[-1] == f"Utente: {user_message.strip()[:400]}":
            righe.pop()
        return "\n".join(righe[-self.MAX_STORICO_AI:])

    # ------------------------------------------------------------------ analisi della richiesta

    # Parole interrogative che identificano una domanda fattuale
    _QUESTION_STARTERS = (
        'chi', 'quando', 'dove', 'perché', 'perche', 'quanto', 'quanti',
        'quante', 'quanta', 'quale', 'quali', 'come', "cos'è", "cos'e", 'cosa', 'che',
    )
    # Frasi che sembrano domande ma sono ricerche di eventi/attivita'
    _QUESTION_EXCLUSIONS = ('cosa fare', 'che fare', 'cosa c', 'cosa succede stasera')
    # Frasi sul bot o sul sito -> 'help' (non si risponde pescando dagli articoli)
    _INFO_PHRASES = (
        'cosa puoi fare', 'cosa sai fare', 'come funzioni', 'a cosa servi',
        'come ti uso', 'come posso usarti', 'chi siamo', 'chi sei', 'cosa fai',
        'informazioni sul sito', 'contatti', 'contattare',
    )

    def _coerce_question_intent(self, message, intent):
        """Rete di sicurezza sul tipo di richiesta deciso dall'AI."""
        try:
            if not isinstance(intent, dict):
                return intent
            m = (message or '').strip().lower()
            if not m:
                return intent
            if any(p in m for p in self._INFO_PHRASES):
                intent['request_type'] = 'help'
                return intent
            if intent.get('request_type') in ('feedback', 'greeting', 'help', 'question'):
                if intent.get('request_type') == 'question' and any(m.startswith(x) for x in self._QUESTION_EXCLUSIONS):
                    intent['request_type'] = 'search'
                return intent
            if any(m.startswith(x) for x in self._QUESTION_EXCLUSIONS):
                return intent
            first_word = m.split()[0]
            if m.endswith('?') or first_word in self._QUESTION_STARTERS:
                intent['request_type'] = 'question'
                if not intent.get('articles_needed') or intent.get('articles_needed', 0) < 1:
                    intent['articles_needed'] = 4
                logger.info(f"Intent forzato a 'question' da euristica per: '{message}'")
        except Exception as e:
            logger.warning(f"Errore in _coerce_question_intent: {e}")
        return intent

    def _calendario(self):
        """Date di riferimento per l'AI (le date relative le calcola meglio se gliele diamo)."""
        oggi = timezone.localdate()
        righe = []
        for delta in range(-7, 15):
            d = oggi + timedelta(days=delta)
            etichetta = {0: ' (OGGI)', 1: ' (domani)', -1: ' (ieri)'}.get(delta, '')
            righe.append(f"{GIORNI[d.weekday()]} {d.isoformat()}{etichetta}")
        return oggi, "\n".join(righe)

    def _analyze_intent(self, user_message, storico=''):
        """L'AI traduce la richiesta in parole chiave, date e tipo di richiesta."""
        oggi, calendario = self._calendario()
        system_prompt = f"""Analizzi le richieste fatte al motore di ricerca di Ombra del Portico, giornale online di Carpi (Modena).
Oggi è {GIORNI[oggi.weekday()]} {oggi.day} {MESI[oggi.month - 1]} {oggi.year}.

Calendario:
{calendario}

Restituisci SOLO un JSON:
{{
  "keywords": ["..."],
  "data_da": "AAAA-MM-GG" | null,
  "data_a": "AAAA-MM-GG" | null,
  "campo_data": "evento" | "pubblicazione" | null,
  "categoria": "Sport" | "Cronaca" | "Cultura & Eventi" | "Attualità" | "Politica" | null,
  "request_type": "search" | "latest" | "question" | "greeting" | "help" | "feedback",
  "articles_needed": numero
}}

KEYWORDS (al massimo 4, sono le parole cercate nel testo degli articoli):
- Solo gli argomenti: nomi, luoghi, organizzazioni, fatti. Niente articoli, preposizioni, verbi generici ("successo", "sono", "fare"), niente "carpi", "notizie", "articoli".
- Nomi composti e nomi di persona interi in UNA keyword: "alex bernardi", "san marino", "museo della bilancia", "torrione degli spagnoli", "paolo dall'olio", "de rosa".
- Correggi i refusi evidenti ("evanti" -> eventi, "festiva" -> festival, "trminl" -> terminal).
- Puoi dare sinonimi stretti nella stessa keyword separati da | ("incidente|scontro", "sindaco|sindaca"). Non allargare il senso.
- Se la richiesta è solo "eventi"/"cosa fare" in un giorno, keywords = [].

DATE:
- data_da/data_a solo se la richiesta indica un periodo ("domani", "sabato", "questo weekend", "il 14 maggio", "a ottobre", "la settimana scorsa"). Altrimenti null.
- Usa il calendario. "sabato", "weekend", un giorno della settimana: per eventi e cose da fare è il PROSSIMO (o quello in corso); per fatti già successi ("cosa è successo sabato") è il più recente passato. Un mese senza anno: il più recente passato per le notizie, il prossimo per gli eventi.
- campo_data "evento" se chiede eventi, spettacoli, concerti, mostre, cose da fare, appuntamenti in quel periodo; "pubblicazione" se chiede notizie o fatti di quel periodo.

REQUEST_TYPE:
- "question": una domanda a cui rispondere con un fatto (chi/cosa/quando/dove/perché/quanto, "a che ora...", "cosa è successo...").
- "search": cerca articoli su un argomento o un nome (anche una sola parola: "lambrusco", "terminal").
- "latest": ultime notizie senza argomento ("ultime notizie", "gli ultimi 3 articoli", "ultime di sport").
- "greeting": saluto o messaggio senza senso ("ciao", "A an").
- "help": domande sul bot o sul sito.
- "feedback": segnalazioni, correzioni, complimenti o lamentele rivolte alla redazione ("avete scritto l'orario sbagliato", "che bel servizio").

ARTICLES_NEEDED: per question quanti articoli leggere (fatto preciso 3, quadro generale o rapporti tra soggetti 6); per latest quanti ne chiede (default 10); altrimenti 0.
CATEGORIA: solo per richieste generiche di una sezione ("ultime di sport"); con un argomento preciso è null.

Se c'è una conversazione precedente, il nuovo messaggio può riferirsi ad essa ("e domani?", "dimmi di più", "e lui chi è?"): completa le keywords e le date con quel contesto.

Esempi (oggi = {oggi.isoformat()}):
- "Aimag" -> {{"keywords": ["aimag"], "data_da": null, "data_a": null, "campo_data": null, "categoria": null, "request_type": "search", "articles_needed": 0}}
- "morte alex bernardi" -> {{"keywords": ["alex bernardi", "morte|morto|scomparso|addio|lutto"], "data_da": null, "data_a": null, "campo_data": null, "categoria": null, "request_type": "search", "articles_needed": 0}}
- "che eventi ci sono domani?" -> {{"keywords": [], "data_da": "{(oggi + timedelta(days=1)).isoformat()}", "data_a": "{(oggi + timedelta(days=1)).isoformat()}", "campo_data": "evento", "categoria": null, "request_type": "search", "articles_needed": 0}}
- "Cosa è successo tra Aimag e Hera?" -> {{"keywords": ["aimag", "hera"], "data_da": null, "data_a": null, "campo_data": null, "categoria": null, "request_type": "question", "articles_needed": 6}}
- "Chi è il sindaco di Campogalliano?" -> {{"keywords": ["sindaco|sindaca", "campogalliano"], "data_da": null, "data_a": null, "campo_data": null, "categoria": null, "request_type": "question", "articles_needed": 3}}
- "ultime notizie di sport" -> {{"keywords": [], "data_da": null, "data_a": null, "campo_data": null, "categoria": "Sport", "request_type": "latest", "articles_needed": 10}}
"""

        user_content = user_message
        if storico:
            user_content = f"Conversazione precedente:\n{storico}\n\nNuovo messaggio da analizzare: {user_message}"

        try:
            response_text = self._chat(
                system_prompt=system_prompt,
                user_content=user_content,
                max_tokens=400,
                temperature=0.1,
                operation='chatbot_intent_analysis',
            ).strip()
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json?\s*|\s*```$', '', response_text, flags=re.MULTILINE).strip()
            try:
                intent = json.loads(response_text)
            except json.JSONDecodeError:
                match = re.search(r'\{.*\}', response_text, flags=re.DOTALL)
                if not match:
                    raise
                intent = json.loads(match.group(0))
            if not isinstance(intent, dict):
                raise ValueError("intent non e' un oggetto JSON")
            logger.info(f"Intent estratto da '{user_message}': {intent}")
            return intent

        except Exception as e:
            logger.warning(f"Analisi intent AI non riuscita, uso fallback semplice: {e}")
            return self._simple_intent_analysis(user_message)

    def _simple_intent_analysis(self, message):
        """Fallback senza AI."""
        message_lower = message.lower()
        intent = {'keywords': [], 'timeframe': None, 'categoria': None, 'request_type': 'search'}

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
        for giorno in GIORNI:
            for forma in (giorno, giorno.replace('ì', 'i')):
                if forma in message_lower:
                    intent['timeframe'] = giorno.replace('ì', 'i')
        for mese in MESI:
            if mese in message_lower:
                intent['timeframe'] = mese
                break
        if any(word in message_lower for word in ['evento', 'eventi', 'cosa fare', 'spettacol', 'concert']):
            intent['campo_data'] = 'evento'

        words = re.findall(r'\w+', normalizza(message))
        intent['keywords'] = [w for w in words if w not in STOPWORDS and len(w) > 3 and w not in TIMEFRAME_LEGACY][:4]
        return intent

    # ------------------------------------------------------------------ ricerca

    def _base_queryset(self):
        return Articolo.objects.filter(
            Q(is_pubbliredazionale=False, approvato=True) |
            Q(is_pubbliredazionale=True, approvato=True, payment_status='completed')
        )

    @staticmethod
    def _parse_data(valore):
        if not valore:
            return None
        try:
            return date.fromisoformat(str(valore)[:10])
        except ValueError:
            return None

    def _range_da_timeframe(self, timeframe, futuro=False):
        """Intervallo di date per i vecchi intent con 'timeframe' (pagina risultati, fallback).
        futuro=True per gli eventi: 'sabato' e' il prossimo, non quello passato."""
        oggi = timezone.localdate()
        tf = (timeframe or '').lower().replace('ì', 'i')
        if tf == 'oggi':
            return oggi, oggi
        if tf == 'domani':
            d = oggi + timedelta(days=1)
            return d, d
        if tf == 'ieri':
            d = oggi - timedelta(days=1)
            return d, d
        if tf == 'weekend':
            wd = oggi.weekday()
            if wd == 6:
                return oggi, oggi
            if futuro or wd == 5:
                sabato = oggi + timedelta(days=5 - wd)
            else:
                sabato = oggi - timedelta(days=wd + 2)
            return sabato, sabato + timedelta(days=1)
        giorni = ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']
        if tf in giorni:
            target, wd = giorni.index(tf), oggi.weekday()
            d = oggi + timedelta(days=(target - wd) % 7) if futuro else oggi - timedelta(days=(wd - target) % 7)
            return d, d
        if tf in MESI:
            mese = MESI.index(tf) + 1
            if futuro:
                anno = oggi.year if mese >= oggi.month else oggi.year + 1
            else:
                anno = oggi.year if mese <= oggi.month else oggi.year - 1
            fine = date(anno + 1, 1, 1) if mese == 12 else date(anno, mese + 1, 1)
            return date(anno, mese, 1), fine - timedelta(days=1)
        if tf == 'settimana':
            return (oggi, oggi + timedelta(days=7)) if futuro else (oggi - timedelta(days=7), oggi)
        if tf == 'mese':
            return (oggi, oggi + timedelta(days=30)) if futuro else (oggi - timedelta(days=30), oggi)
        return None, None

    def _termini(self, intent, per_eventi=False):
        termini, visti = [], set()
        for kw in intent.get('keywords') or []:
            if not isinstance(kw, str):
                continue
            chiave = normalizza(kw).strip()
            if not chiave or chiave in visti:
                continue
            if per_eventi and chiave in PAROLE_EVENTO_GENERICHE:
                continue
            visti.add(chiave)
            t = Termine(kw)
            if t.valido:
                termini.append(t)
        return termini

    def _search_articles(self, intent):
        """
        Articoli pertinenti all'intent, dal piu' pertinente. Usata anche dalla pagina
        /chatbot/risultati/ (che passa l'intent ricevuto dal browser).
        """
        if not isinstance(intent, dict):
            intent = {}
        self.termini_mancanti = []  # termini che non compaiono negli articoli restituiti
        now = timezone.now()
        query = self._base_queryset()

        # Date: nuovo formato (data_da/data_a) o vecchio 'timeframe'
        campo = intent.get('campo_data')
        keywords_norm = {normalizza(k).strip() for k in intent.get('keywords') or [] if isinstance(k, str)}
        data_da, data_a = self._parse_data(intent.get('data_da')), self._parse_data(intent.get('data_a'))
        if not data_da and not data_a and intent.get('timeframe'):
            if not campo and (keywords_norm and keywords_norm <= PAROLE_EVENTO_GENERICHE):
                campo = 'evento'
            data_da, data_a = self._range_da_timeframe(intent['timeframe'], futuro=(campo == 'evento'))
        if data_da and not data_a:
            data_a = data_da if campo == 'evento' else timezone.localdate()
        if data_a and not data_da:
            data_da = data_a
        if data_da and data_a and data_da > data_a:
            data_da, data_a = data_a, data_da

        per_eventi = bool(data_da and campo == 'evento')
        termini = self._termini(intent, per_eventi=per_eventi)

        if per_eventi:
            query = query.filter(data_evento__gte=data_da, data_evento__lte=data_a)
        else:
            # Gli articoli programmati (data futura) non sono ancora usciti
            query = query.filter(data_pubblicazione__lte=now)
            if data_da:
                tz = timezone.get_current_timezone()
                inizio = timezone.make_aware(datetime.combine(data_da, time.min), tz)
                fine = timezone.make_aware(datetime.combine(data_a + timedelta(days=1), time.min), tz)
                query = query.filter(data_pubblicazione__gte=inizio, data_pubblicazione__lt=fine)

        if intent.get('categoria') and not termini:
            query = query.filter(categoria__iexact=intent['categoria'])

        if not termini:
            if per_eventi:
                return list(query.order_by('data_evento', '-data_pubblicazione'))
            return list(query.order_by('-data_pubblicazione'))

        # Filtro grezzo nel database: almeno un termine (anche solo in parte)
        filtro = Q()
        for t in termini:
            for p in t.prefissi:
                filtro |= Q(titolo__icontains=p) | Q(sommario__icontains=p) | Q(contenuto__icontains=p)
        ordine = ('data_evento',) if per_eventi else ('-data_pubblicazione',)
        candidati = list(query.filter(filtro).order_by(*ordine)[:self.MAX_CANDIDATI])

        risultati = self._ordina_per_pertinenza(candidati, termini, now)
        if risultati:
            primo = (normalizza(risultati[0].titolo) + ' ' + normalizza(risultati[0].sommario)
                     + ' ' + normalizza(risultati[0].contenuto))
            self.termini_mancanti = [t.testo.split('|')[0] for t in termini if not t.conta(primo)]
            # Se resta un solo termine (es. 'morte' senza il nome cercato) i risultati sono rumore
            if self.termini_mancanti and len(termini) - len(self.termini_mancanti) < 2:
                risultati = []

        if per_eventi:
            risultati.sort(key=lambda a: a.data_evento or date.max)
        logger.info(f"Ricerca {[t.testo for t in termini]}: {len(candidati)} candidati, {len(risultati)} pertinenti")
        return risultati

    def _ordina_per_pertinenza(self, candidati, termini, now):
        """
        Punteggio per articolo: per ogni termine trovato, titolo 3, sommario 1,5, testo fino a 2
        (0,4 a ripetizione), pesato per la rarita' del termine. Restano solo gli articoli che
        coprono i termini quanto il migliore (prima tutti i termini; se nessun articolo li ha
        tutti, i piu' rari). A parita', piu' recente prima.
        """
        if not candidati:
            return []
        dati = []
        df = [0] * len(termini)
        for a in candidati:
            titolo = normalizza(a.titolo)
            sommario = normalizza(a.sommario)
            testo = normalizza(a.contenuto)
            per_termine = []
            for i, t in enumerate(termini):
                in_titolo = t.conta(titolo) > 0
                in_sommario = t.conta(sommario) > 0
                nel_testo = t.conta(testo)
                s = (3 if in_titolo else 0) + (1.5 if in_sommario else 0) + min(nel_testo, 5) * 0.4
                if s:
                    df[i] += 1
                per_termine.append(s)
            dati.append((a, per_termine))

        n = len(candidati)
        pesi = [math.log(1 + n / (1 + d)) + 0.1 for d in df]
        peso_totale = sum(pesi)

        valutati = []
        for a, per_termine in dati:
            copertura = sum(p for p, s in zip(pesi, per_termine) if s) / peso_totale
            if copertura == 0:
                continue  # il termine c'era solo dentro un'altra parola o in un link
            punteggio = sum(p * s for p, s in zip(pesi, per_termine))
            giorni = max((now - a.data_pubblicazione).days, 0) if a.data_pubblicazione else 3650
            punteggio *= 0.6 + 0.4 * math.exp(-giorni / 120)
            valutati.append((copertura, punteggio, a))

        if not valutati:
            return []
        migliore = max(c for c, _, _ in valutati)
        tenuti = [(p, a) for c, p, a in valutati if c >= migliore - 1e-9]
        tenuti.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in tenuti]

    # ------------------------------------------------------------------ risposte

    def _descrizione_ricerca(self, intent):
        parti = []
        kws = [str(k).split('|')[0] for k in intent.get('keywords') or [] if isinstance(k, str)]
        if kws:
            parti.append(', '.join(kws[:3]))
        data_da, data_a = self._parse_data(intent.get('data_da')), self._parse_data(intent.get('data_a'))
        if data_da:
            if data_a and data_a != data_da:
                parti.append(f"dal {data_da.day} {MESI[data_da.month - 1]} al {data_a.day} {MESI[data_a.month - 1]}")
            else:
                parti.append(f"{GIORNI[data_da.weekday()]} {data_da.day} {MESI[data_da.month - 1]}")
        return ' '.join(parti)

    def _generate_response(self, intent, articles, user_message):
        """Testo della risposta per ricerche, ultime notizie, saluti, aiuto, segnalazioni."""
        request_type = intent.get('request_type', 'search')
        user_message_lower = user_message.lower()

        if any(phrase in user_message_lower for phrase in ['chi siamo', 'chi sei', 'cosa fai', 'informazioni sul sito']):
            return "Ombra del Portico è il portale di notizie di Carpi.\n\nPer saperne di più su di noi, visita la pagina [Chi Siamo](/about/)"

        if request_type == 'feedback' or any(p in user_message_lower for p in ['contatti', 'contattare']):
            intro = "Grazie della segnalazione!" if request_type == 'feedback' else "📧 **Contatti**"
            return (f"{intro}\n\nPer scrivere alla redazione: **info@ombradelportico.it**. "
                    "Se riguarda un articolo, indica il titolo: lo controlliamo subito.")

        if request_type == 'greeting':
            return ("Ciao! Sono l'assistente di Ombra del Portico.\n\n"
                    "Cerco tra gli articoli del sito e rispondo alle domande sulle notizie di Carpi. Esempi:\n"
                    "• \"Cosa è successo questa settimana?\"\n"
                    "• \"Eventi di questo weekend\"\n"
                    "• \"Chi è il sindaco di Novi?\"\n"
                    "• \"Aimag\"")

        if request_type == 'help':
            return ("Posso cercare tra gli articoli di Ombra del Portico e rispondere alle domande sulle notizie.\n\n"
                    "Esempi:\n"
                    "• \"Ultime notizie di sport\"\n"
                    "• \"Cosa è successo ieri?\"\n"
                    "• \"Concerti sabato\"\n"
                    "• \"Lavori sulla statale 413\"\n\n"
                    "Cosa vuoi cercare?")

        descrizione = self._descrizione_ricerca(intent)
        eventi = intent.get('campo_data') == 'evento' and intent.get('data_da')

        if not articles:
            if eventi:
                return (f"Non ho trovato eventi in calendario{' per ' + descrizione if descrizione else ''}. "
                        "Il programma completo è nel [calendario degli eventi](/eventi/).")
            mancanti = getattr(self, 'termini_mancanti', [])
            if mancanti:
                descrizione = ', '.join('«' + m + '»' for m in mancanti)
            return (f"Non ho trovato articoli{' su ' + descrizione if descrizione else ''}. "
                    "Prova con altre parole, per esempio un nome o un luogo.")

        count = len(articles)
        if request_type == 'latest' and not intent.get('keywords'):
            sezione = f" di {intent['categoria']}" if intent.get('categoria') else ''
            return f"Ecco le ultime notizie{sezione}:"
        if eventi:
            return f"Ecco gli eventi {descrizione}:" if count > 1 else f"Ecco l'evento {descrizione}:"
        mancanti = getattr(self, 'termini_mancanti', [])
        if mancanti:
            trovati = [k for k in (str(x).split('|')[0] for x in intent.get('keywords') or []) if k not in mancanti]
            return (f"Nessun articolo parla di {', '.join('«' + m + '»' for m in mancanti)}. "
                    f"Ecco quell{'o' if count == 1 else 'i'} su {', '.join(trovati[:3])}:")
        if count == 1:
            return f"Ho trovato un articolo{' su ' + descrizione if descrizione else ''}:"
        if count > self.MAX_ARTICLES_DISPLAY:
            return f"Ho trovato {count} articoli{' su ' + descrizione if descrizione else ''}. Ecco i più pertinenti:"
        return f"Ho trovato {count} articoli{' su ' + descrizione if descrizione else ''}:"

    def _articoli_da_leggere(self, intent, articles):
        try:
            richiesti = int(intent.get('articles_needed') or 4)
        except (TypeError, ValueError):
            richiesti = 4
        senza_argomento = not intent.get('keywords')
        massimo = 8 if senza_argomento else 6
        return articles[:max(3, min(richiesti, massimo))]

    def _answer_question(self, question, articles, intent, storico=''):
        """Risposta a una domanda basata sugli articoli trovati."""
        if not articles:
            return "Non ho trovato informazioni sufficienti per rispondere alla tua domanda."

        oggi = timezone.localdate()
        # Con molti articoli (es. "cosa è successo questa settimana") se ne legge l'inizio
        limite = 1500 if len(articles) > 6 else 3500
        context_parts = []
        for i, article in enumerate(articles, start=1):
            testo = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', article.contenuto or ''))).strip()
            if len(testo) > limite:
                testo = testo[:limite] + '…'
            righe = [f"Articolo {i}: {article.titolo}",
                     f"Pubblicato il {article.data_pubblicazione.strftime('%d/%m/%Y')} · {article.categoria}"]
            if article.data_evento:
                righe.append(f"Data dell'evento: {article.data_evento.strftime('%d/%m/%Y')}")
            righe.append(f"Testo: {testo}")
            context_parts.append("\n".join(righe))
        context = "\n\n---\n\n".join(context_parts)

        system_prompt = f"""Sei l'assistente di Ombra del Portico, giornale online di Carpi. Oggi è {GIORNI[oggi.weekday()]} {oggi.day} {MESI[oggi.month - 1]} {oggi.year}.
Rispondi alla domanda del lettore usando SOLO gli articoli forniti.

REGOLE:
- Ogni fatto, nome, numero, data od orario deve stare negli articoli. Non aggiungere nulla di tuo.
- Se gli articoli non contengono la risposta, dillo in una frase e indica cosa contengono di vicino, se c'è.
- Le notizie hanno una data: se un fatto può essere cambiato (cariche, lavori, prezzi, risultati), indica a quando risale ("secondo l'articolo del 3 luglio..."). Se gli articoli si contraddicono, vale il più recente e lo dici.
- Le date relative degli articoli ("domani", "sabato") vanno lette rispetto alla data di pubblicazione, non a oggi. Un evento già passato rispetto a oggi va detto al passato.
- Risposta breve: 2-4 frasi; per "cosa è successo..." un elenco puntato di 3-6 fatti, uno per riga, che iniziano con "• ".
- Tono diretto e cordiale, in italiano. Puoi usare **grassetto** per il dato chiave. Niente titoli, niente "Fonte:", niente "Articolo 1": gli articoli li mostra il sito sotto la risposta."""

        user_content = f"Domanda: {question}\n\nArticoli:\n\n{context}"
        if storico:
            user_content = f"Conversazione precedente:\n{storico}\n\n{user_content}"

        try:
            return self._chat(
                system_prompt=system_prompt,
                user_content=user_content,
                max_tokens=600,
                temperature=0.2,
                operation='chatbot_question_answering',
            )
        except Exception as e:
            logger.error(f"Errore generazione risposta: {e}", exc_info=True)
            return ("Ho trovato degli articoli sull'argomento ma non riesco a elaborare una risposta adesso: "
                    "li trovi qui sotto.")

    def _serialize_article(self, article):
        """Serializza un articolo per la risposta JSON"""
        sommario = article.sommario or ''
        return {
            'id': article.id,
            'slug': article.slug,
            'titolo': article.titolo,
            'sommario': sommario[:200] + '...' if len(sommario) > 200 else sommario,
            'categoria': article.categoria,
            'data_pubblicazione': article.data_pubblicazione.isoformat(),
            'data_evento': article.data_evento.isoformat() if article.data_evento else None,
            'foto': article.foto if article.foto else None,
            'url': f'/articolo/{article.slug}/'
        }
