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

            return {
                'response': response,
                'articles': [self._serialize_article(a) for a in articles],  # Tutti gli articoli trovati
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
- Usa categoria SOLO per richieste generiche ("ultime notizie di sport")
- Per ricerche specifiche (es. "rugby") NON usare categoria, usa solo keywords
- DOMANDE APERTE (chi/cosa/quando/dove/perché): usa request_type "question"
- Valuta la complessità della domanda per ottimizzare l'uso dei token

Restituisci SOLO un JSON valido con questa struttura:
{
    "keywords": ["parola1", "parola2"],
    "timeframe": "oggi|ieri|settimana|mese|null",
    "categoria": "Sport|Cronaca|Cultura|Eventi|Attualità|Politica|null",
    "entity": "nome persona/organizzazione se menzionata|null",
    "request_type": "search|latest|help|greeting|question",
    "articles_needed": 1-5 (solo per question, numero articoli da analizzare)
}

Esempi:
- "Trovami articoli su Aimag" -> {"keywords": ["aimag"], "timeframe": null, "categoria": null, "entity": "Aimag", "request_type": "search", "articles_needed": 0}
- "Chi è il sindaco di Campogalliano?" -> {"keywords": ["sindaco", "campogalliano"], "timeframe": null, "categoria": null, "entity": "sindaco", "request_type": "question", "articles_needed": 1}
- "Cosa è successo questa settimana a Carpi?" -> {"keywords": [], "timeframe": "settimana", "categoria": null, "entity": null, "request_type": "question", "articles_needed": 5}
- "Quando inizia il mercato?" -> {"keywords": ["mercato", "inizio"], "timeframe": null, "categoria": null, "entity": null, "request_type": "question", "articles_needed": 1}
- "Ultime notizie di sport" -> {"keywords": [], "timeframe": null, "categoria": "Sport", "entity": null, "request_type": "latest", "articles_needed": 0}
- "Rugby" -> {"keywords": ["rugby"], "timeframe": null, "categoria": null, "entity": null, "request_type": "search", "articles_needed": 0}
- "Ciao" -> {"keywords": [], "timeframe": null, "categoria": null, "entity": null, "request_type": "greeting", "articles_needed": 0}
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

            logger.info(f"Intent estratto: {intent}")
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
        elif any(word in message_lower for word in ['settimana', 'ultimi giorni']):
            intent['timeframe'] = 'settimana'

        # Categorie
        if any(word in message_lower for word in ['sport', 'calcio', 'partita']):
            intent['categoria'] = 'Sport'
        elif any(word in message_lower for word in ['evento', 'eventi', 'cosa fare']):
            intent['categoria'] = 'Eventi'
        elif any(word in message_lower for word in ['cultura', 'teatro', 'mostra']):
            intent['categoria'] = 'Cultura'

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
        query = Articolo.objects.filter(approvato=True)

        # Filtro temporale
        if intent.get('timeframe'):
            now = timezone.now()
            if intent['timeframe'] == 'oggi':
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(data_pubblicazione__gte=start_date)
            elif intent['timeframe'] == 'ieri':
                yesterday = now - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(data_pubblicazione__gte=start_date, data_pubblicazione__lt=end_date)
            elif intent['timeframe'] == 'settimana':
                start_date = now - timedelta(days=7)
                query = query.filter(data_pubblicazione__gte=start_date)
            elif intent['timeframe'] == 'mese':
                start_date = now - timedelta(days=30)
                query = query.filter(data_pubblicazione__gte=start_date)

        # Filtro categoria
        if intent.get('categoria'):
            query = query.filter(categoria__iexact=intent['categoria'])

        # Filtro keywords
        keywords = intent.get('keywords', [])
        if keywords:
            # Costruisci query OR per tutte le keywords
            keyword_query = Q()
            for keyword in keywords:
                keyword_query |= Q(titolo__icontains=keyword) | Q(contenuto__icontains=keyword) | Q(sommario__icontains=keyword)
            query = query.filter(keyword_query)
            logger.info(f"Filtro keywords applicato: {keywords}")

        # Ordina per rilevanza (più recenti prima)
        articles = query.order_by('-data_pubblicazione')

        # Converti QuerySet in lista per contare
        articles_list = list(articles)

        logger.info(f"Trovati {len(articles_list)} articoli per intent: {intent}")

        return articles_list

    def _generate_response(self, intent, articles, user_message):
        """
        Genera una risposta testuale in base ai risultati
        """
        request_type = intent.get('request_type', 'search')

        # Gestisci saluti
        if request_type == 'greeting':
            return "Ciao! Sono l'assistente di Ombra del Portico. Posso aiutarti a trovare notizie su Carpi. Cosa ti interessa?"

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

        # DOMANDA APERTA: genera risposta intelligente dal contenuto
        if request_type == 'question':
            return self._answer_question(user_message, articles, intent)

        # Risultati trovati - risposta normale per ricerca
        count = len(articles)

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

    def _answer_question(self, question, articles, intent):
        """
        Genera una risposta intelligente a una domanda usando il contenuto degli articoli
        """
        # Determina quanti articoli leggere (default 1, max 5)
        articles_to_read = min(intent.get('articles_needed', 1), len(articles), 5)

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
