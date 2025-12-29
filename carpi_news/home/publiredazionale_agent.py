"""
AI Agent per la creazione di articoli pubbliredazionali
Gestisce l'intero workflow: analisi sito, ricerca web, intervista, generazione articolo
"""

import logging
import json
import anthropic
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from .api_usage_tracker import APIUsageTracker
from .social_media_scraper import SocialMediaScraper

logger = logging.getLogger(__name__)


class PubbliredazioneAgent:
    """
    AI Agent conversazionale per creare articoli pubbliredazionali

    Workflow:
    1. Analisi del sito web dell'azienda
    2. Ricerca web su azienda, mercato, problemi risolti
    3. Intervista dinamica (3-5 domande)
    4. Generazione articolo pubbliredazionale
    """

    def __init__(self, pubbliredazionale):
        """
        Args:
            pubbliredazionale: Istanza di ArticoloPubbliredazionale
        """
        self.pubbliredazionale = pubbliredazionale

        # Verifica che l'API key sia presente
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY non configurata nel file .env")

        try:
            self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        except Exception as e:
            logger.error(f"Errore inizializzazione Anthropic client: {e}")
            raise

    def start_interview(self):
        """
        Fase 1: Analizza il sito web, fa ricerca approfondita, poi inizia l'intervista
        Restituisce la prima domanda
        """
        try:
            logger.info(f"Start interview per: {self.pubbliredazionale.nome_azienda}, sito: {self.pubbliredazionale.sito_web}")

            # FASE 1: Estrai informazioni APPROFONDITE dal sito web
            logger.info("Inizio scraping PROFONDO del sito web...")
            website_content = self._scrape_website_deep(self.pubbliredazionale.sito_web)
            logger.info(f"Scraping profondo completato: {len(website_content)} caratteri estratti")

            # DEBUG: Log del contenuto estratto
            if len(website_content) < 100:
                logger.warning(f"ATTENZIONE: Contenuto sito molto breve o vuoto! Contenuto: {website_content}")
            else:
                logger.info(f"Preview contenuto estratto (primi 500 char): {website_content[:500]}")

            # FASE 2: Ricerca web approfondita e analisi di mercato
            # Esegui SEMPRE la web research, anche se il sito è un profilo social
            # Per profili social, la web research è fondamentale per raccogliere informazioni
            is_social_profile = 'instagram.com' in self.pubbliredazionale.sito_web.lower() or \
                               'facebook.com' in self.pubbliredazionale.sito_web.lower() or \
                               'linkedin.com' in self.pubbliredazionale.sito_web.lower()

            if website_content and len(website_content) > 100 or is_social_profile:
                logger.info("Inizio ricerca web approfondita e analisi di mercato...")
                web_research = self._perform_web_research(website_content)
                logger.info(f"Ricerca completata: {len(web_research.get('findings', ''))} caratteri di analisi")
            else:
                logger.info("Salto ricerca web (nessun contenuto sito disponibile)")
                web_research = {'findings': '', 'sources': []}

            # Salva informazioni raccolte
            interview_data = self.pubbliredazionale.interview_data or {}
            interview_data['website_content'] = website_content
            interview_data['web_research'] = web_research
            interview_data['conversation'] = []

            # FASE 3: Genera la prima domanda usando tutte le info raccolte
            logger.info("Generazione prima domanda basata sulla ricerca...")
            first_question = self._generate_first_question_with_research(website_content, web_research)
            logger.info(f"Prima domanda generata: {first_question[:100]}...")

            interview_data['conversation'].append({
                'role': 'agent',
                'message': first_question
            })

            # Aggiorna stato
            self.pubbliredazionale.interview_data = interview_data
            self.pubbliredazionale.status = 'interview_in_progress'
            self.pubbliredazionale.save()
            logger.info("Intervista iniziata con successo (con ricerca approfondita)")

            return {
                'success': True,
                'message': first_question,
                'interview_data': interview_data
            }

        except Exception as e:
            logger.error(f"Errore start_interview: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _scrape_website(self, url):
        """
        Estrae informazioni di base dal sito web dell'azienda
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Estrai info base
            title = soup.find('title')
            title_text = title.get_text().strip() if title else ''

            # Estrai meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            description = meta_desc.get('content', '').strip() if meta_desc else ''

            # Estrai testo principale (primi 1000 caratteri)
            paragraphs = soup.find_all('p')
            main_text = ' '.join([p.get_text().strip() for p in paragraphs[:5]])[:1000]

            return {
                'url': url,
                'title': title_text,
                'description': description,
                'main_text': main_text,
                'scraped': True
            }

        except Exception as e:
            logger.error(f"Errore scraping {url}: {e}")
            return {
                'url': url,
                'error': str(e),
                'scraped': False
            }

    def _generate_first_question_with_research(self, website_content, web_research):
        """
        Genera la prima domanda: IDENTIFICARE IL FOCUS dell'articolo
        """
        # Controlla se abbiamo contenuto del sito web
        has_website_content = website_content and len(website_content) > 100

        if has_website_content:
            system_prompt = """Sei un giornalista professionista che intervista un cliente per scrivere un pubbliredazionale.

Il tuo primo obiettivo è CAPIRE IL FOCUS: cosa vuole comunicare il cliente in questo articolo?

Possibili focus:
- Un prodotto/servizio specifico (nuovo lancio, bestseller, innovazione)
- La storia dell'azienda (origini, evoluzione, milestone)
- Un cambio importante (nuova dirigenza, sede, direzione strategica)
- Un valore distintivo (approccio unico, filosofia, specializzazione)
- Una combinazione di questi

PRIMA DOMANDA - Due approcci:

A) Se dal sito emerge CHIARAMENTE un focus recente (nuovo prodotto, evento, cambio):
   "Ho visto che [dettaglio specifico dal sito]. Questo pubbliredazionale nasce per raccontare proprio questo, oppure c'è altro su cui vuole focalizzarsi?"

B) Se il sito è generico/corporate:
   "Per questo pubbliredazionale, su cosa vuole che ci concentriamo? Un prodotto/servizio in particolare, la vostra storia, un aspetto distintivo del vostro approccio, o qualcos'altro?"

OBIETTIVO: Capire subito cosa il cliente vuole comunicare, poi costruiremo l'intervista attorno a quello.

Rispondi SOLO con la domanda (max 2-3 frasi)."""

            market_analysis = web_research.get('findings', 'Nessuna analisi disponibile')

            prompt = f"""AZIENDA: {self.pubbliredazionale.nome_azienda}

CONTENUTO SITO WEB:
{website_content[:6000]}

RICERCA PRELIMINARE:
{market_analysis[:3000]}

Genera la PRIMA domanda per identificare il focus dell'articolo.
Usa approccio A se c'è un dettaglio recente/specifico evidente, altrimenti approccio B.

Rispondi SOLO con la domanda."""
        else:
            # Nessun contenuto del sito disponibile - fai ricerca preliminare sul nome azienda
            logger.info("Nessun contenuto del sito web disponibile - ricerca preliminare sul nome azienda")

            # Ricerca web sul nome azienda per capire il tipo di business
            business_research = self._research_business_type(self.pubbliredazionale.nome_azienda)
            logger.info(f"Ricerca business type completata: {business_research.get('business_type', 'unknown')}")

            system_prompt = """Sei un giornalista professionista che intervista un cliente per scrivere un pubbliredazionale.

Non hai informazioni dal sito web, ma hai fatto una ricerca preliminare sul nome dell'azienda.

PRIMA DOMANDA - Saluto + Indagine attività:
1. INIZIA con un saluto cordiale all'intervistato (usa nome e cognome se forniti)
2. POI chiedi cosa fa l'azienda e cosa la distingue

IMPORTANTE - Adatta la domanda al tipo di business:
- PRODUCT/EXPERIENCE (ristoranti, gelaterie, negozi, artigiani): Chiedi cosa OFFRONO e cosa li rende SPECIALI
- PROBLEM-SOLVING (consulenze, servizi B2B, tecnologia): Chiedi quali PROBLEMI risolvono e come AIUTANO i clienti

Esempi per PRODUCT/EXPERIENCE:
- "Buongiorno [Nome], mi parli della Gelateria K2: quali sono le vostre specialità e cosa vi distingue dalle altre gelaterie?"
- "Salve [Nome], raccontami della vostra attività: che tipo di prodotti offrite e qual è il vostro punto di forza?"

Esempi per PROBLEM-SOLVING:
- "Buongiorno [Nome], mi parli di [Azienda]: quali problemi affrontano i vostri clienti e come li aiutate a risolverli?"
- "Salve [Nome], qual è il focus della vostra consulenza e quali sfide affrontate per i clienti?"

STRUTTURA OBBLIGATORIA:
1. Saluto + Nome intervistato
2. Domanda adattata al business type

Rispondi SOLO con saluto + domanda (max 2-3 frasi)."""

            # Aggiungi nome/cognome intervistato se disponibili
            interviewer_name = ""
            if self.pubbliredazionale.intervistato_nome and self.pubbliredazionale.intervistato_cognome:
                interviewer_name = f"{self.pubbliredazionale.intervistato_nome} {self.pubbliredazionale.intervistato_cognome}"
            elif self.pubbliredazionale.intervistato_nome:
                interviewer_name = self.pubbliredazionale.intervistato_nome

            saluto_target = f"a {interviewer_name}" if interviewer_name else "all'intervistato"

            prompt = f"""AZIENDA: {self.pubbliredazionale.nome_azienda}
INTERVISTATO: {interviewer_name if interviewer_name else "Non specificato"}

RICERCA PRELIMINARE:
{business_research.get('summary', 'Nessuna informazione disponibile')}

TIPO DI BUSINESS RILEVATO: {business_research.get('business_type', 'product/experience')}

Genera la PRIMA domanda con:
1. Saluto cordiale {saluto_target}
2. Domanda appropriata per business type "{business_research.get('business_type', 'product/experience')}"

Rispondi SOLO con saluto + domanda."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                temperature=0.7,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Traccia utilizzo (non bloccante)
            try:
                APIUsageTracker.track_anthropic(
                    operation='publiredazionale_first_question',
                    model='claude-sonnet-4-20250514',
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                    success=True,
                    related_article=None
                )
            except Exception as track_error:
                logger.warning(f"Errore tracciamento API (non bloccante): {track_error}")

            return message.content[0].text.strip()

        except Exception as e:
            logger.error(f"Errore generazione prima domanda: {e}", exc_info=True)
            # Fallback generico sicuro (non assume problem-solving)
            interviewer_name = ""
            if self.pubbliredazionale.intervistato_nome and self.pubbliredazionale.intervistato_cognome:
                interviewer_name = f"{self.pubbliredazionale.intervistato_nome} {self.pubbliredazionale.intervistato_cognome}"
            elif self.pubbliredazionale.intervistato_nome:
                interviewer_name = self.pubbliredazionale.intervistato_nome

            saluto = f"Buongiorno {interviewer_name}, " if interviewer_name else "Buongiorno, "
            return f"{saluto}mi parli di {self.pubbliredazionale.nome_azienda}: quali sono le vostre specialità e cosa vi rende unici nel vostro settore?"

    def _generate_first_question(self, website_info):
        """
        DEPRECATO: Usa _generate_first_question_with_research invece
        Mantenuto per compatibilità
        """
        return "Raccontami in poche parole di cosa si occupa la tua azienda e quali servizi/prodotti offrite."

    def process_user_answer(self, user_answer):
        """
        Processa la risposta dell'utente e genera la prossima domanda
        O completa l'intervista se ha abbastanza informazioni
        """
        try:
            interview_data = self.pubbliredazionale.interview_data or {}
            conversation = interview_data.get('conversation', [])

            # Salva risposta utente
            conversation.append({
                'role': 'user',
                'message': user_answer
            })

            # Verifica se abbiamo abbastanza informazioni (min 2 domande oltre la prima, max 8 totali)
            questions_asked = len([msg for msg in conversation if msg['role'] == 'agent'])

            if questions_asked >= 8:
                # Massimo 8 domande - chiudi comunque
                logger.info(f"Raggiunto massimo 8 domande - chiudo intervista")
                return self._complete_interview_deferred()

            # Genera prossima domanda dinamica
            next_question = self._generate_next_question(conversation, interview_data)

            # Controllo minimo 3 domande (prima sul focus + almeno 2 approfondimenti)
            MIN_QUESTIONS = 3
            if next_question.get('complete') and questions_asked >= MIN_QUESTIONS:
                # L'AI ha deciso che ha abbastanza materiale
                logger.info(f"Intervista completata dopo {questions_asked} domande")
                return self._complete_interview_deferred()
            elif next_question.get('complete') and questions_asked < MIN_QUESTIONS:
                # Troppo presto - forza continuazione
                logger.warning(f"AI vuole chiudere dopo solo {questions_asked} domande - continuo (minimo {MIN_QUESTIONS})")
                next_question = {
                    'complete': False,
                    'question': "Può darmi qualche dettaglio in più? Esempi concreti, numeri, o storie che possano arricchire l'articolo?"
                }

            conversation.append({
                'role': 'agent',
                'message': next_question['question']
            })

            interview_data['conversation'] = conversation
            self.pubbliredazionale.interview_data = interview_data
            self.pubbliredazionale.save()

            return {
                'success': True,
                'message': next_question['question'],
                'interview_complete': False
            }

        except Exception as e:
            logger.error(f"Errore process_user_answer: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _generate_next_question(self, conversation, interview_data):
        """
        Genera la prossima domanda in un DIALOGO DINAMICO vero
        """
        system_prompt = """Sei un giornalista professionista che conduce un'intervista DINAMICA per raccogliere materiale per un pubbliredazionale.

APPROCCIO DINAMICO - NON PREDEFINITO:
- Leggi ATTENTAMENTE tutte le risposte precedenti
- Identifica cosa è già emerso e cosa MANCA ancora
- Fai domande di APPROFONDIMENTO su dettagli interessanti menzionati
- Se il cliente cita qualcosa di specifico (prodotto, persona, evento) → APPROFONDISCI
- Adatta le domande al FOCUS identificato (prodotto, storia, cambiamento, ecc.)

COSA SERVE PER SCRIVERE UN BUON ARTICOLO:

1. **FOCUS CHIARO** (identificato nella prima risposta)
2. **DETTAGLI CONCRETI** sul focus:
   - Se prodotto/servizio: caratteristiche, benefici, casi d'uso, esempi
   - Se storia: origini, persone chiave, momenti fondativi, evoluzione
   - Se cambiamento: cosa era prima, cosa è ora, perché, impatto
3. **CONTESTO E SIGNIFICATO**:
   - Perché è importante? Che problema risolve?
   - A chi si rivolge? Esempi concreti di clienti/situazioni
4. **ELEMENTI NARRATIVI**:
   - Aneddoti, storie concrete, momenti significativi
   - Persone (nomi se possibile), emozioni, motivazioni
5. **DATI SPECIFICI**:
   - Nomi propri di prodotti/servizi/strumenti
   - Numeri, date, luoghi se rilevanti
   - Risultati, feedback, casi di successo

DECIDI:
- Se hai raccolto abbastanza materiale per scrivere un articolo RICCO → {"complete": true}
- Se mancano dettagli importanti o approfondimenti → {"complete": false, "question": "domanda specifica"}

REGOLE:
- MINIMO 2 domande (esclusa la prima sul focus)
- MASSIMO 8 domande totali
- Le domande devono essere SPECIFICHE, non generiche
- Se il cliente menziona qualcosa di interessante → approfondisci
- NO domande predefinite - ADATTA al contenuto delle risposte

Rispondi con JSON: {"complete": true} oppure {"complete": false, "question": "la domanda"}"""

        # Conta quante domande sono state fatte
        questions_asked = len([msg for msg in conversation if msg['role'] == 'agent'])

        # Converti conversazione in testo DETTAGLIATO
        conv_text = "\n\n".join([
            f"{'GIORNALISTA' if msg['role'] == 'agent' else 'CLIENTE'}:\n{msg['message']}"
            for msg in conversation
        ])

        # Dati di contesto - Passa TUTTO solo alla prima domanda, poi solo conversazione
        website_content = interview_data.get('website_content', '')
        market_analysis = interview_data.get('web_research', {}).get('findings', '')

        # Nome intervistato se disponibile
        interviewer_name = ""
        if self.pubbliredazionale.intervistato_nome and self.pubbliredazionale.intervistato_cognome:
            interviewer_name = f"{self.pubbliredazionale.intervistato_nome} {self.pubbliredazionale.intervistato_cognome}"
        elif self.pubbliredazionale.intervistato_nome:
            interviewer_name = self.pubbliredazionale.intervistato_nome

        interviewer_line = f"INTERVISTATO: {interviewer_name}" if interviewer_name else ""

        # Data odierna per contestualizzare
        from datetime import datetime
        oggi = datetime.now().strftime("%d/%m/%Y")

        # NESSUN contesto esterno - solo conversazione
        # Il contesto viene usato solo per generare la prima domanda iniziale
        context_section = ""

        prompt = f"""AZIENDA: {self.pubbliredazionale.nome_azienda}
{interviewer_line}
DATA ODIERNA: {oggi}

{context_section}=== CONVERSAZIONE COMPLETA ===
{conv_text}

=== TUO COMPITO ===
Hai fatto {questions_asked} domande finora.

Leggi TUTTE le risposte del cliente e decidi:

1. Hai abbastanza materiale RICCO e SPECIFICO per scrivere un articolo coinvolgente?
   - Ci sono dettagli concreti (nomi, prodotti, persone, numeri)?
   - Hai capito bene il focus?
   - Hai esempi/aneddoti/storie?

2. Oppure serve approfondire?
   - Il cliente ha citato qualcosa di interessante da esplorare?
   - Mancano dettagli importanti sul focus?
   - Le risposte sono state troppo generiche?

Se serve altra domanda: falla SPECIFICA basandoti su ciò che il cliente ha detto.
NON usare domande generiche - REAGISCI alle sue risposte.

FORMATO RISPOSTA - OBBLIGATORIO:
Devi rispondere SOLO con JSON valido, nessun testo prima o dopo.

Esempi:
{{"complete": true}}

oppure

{{"complete": false, "question": "Da quanto tempo siete la gelateria più antica di Carpi? E quali sono i gusti storici che preparate dal 1970?"}}

IMPORTANTE: Rispondi SOLO con il JSON, nient'altro."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                temperature=0.7,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Traccia utilizzo (non bloccante)
            try:
                APIUsageTracker.track_anthropic(
                    operation='publiredazionale_next_question',
                    model='claude-sonnet-4-20250514',
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                    success=True
                )
            except Exception as track_error:
                logger.warning(f"Errore tracciamento API (non bloccante): {track_error}")

            response_text = message.content[0].text.strip()
            logger.info(f"Risposta AI next_question (raw): {response_text[:500]}")

            # Rimuovi markdown code blocks se presenti
            import re
            if '```' in response_text:
                # Estrai contenuto tra ``` markers
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if match:
                    response_text = match.group(1)
                    logger.info(f"Estratto JSON da code block: {response_text[:300]}")
                else:
                    # Rimuovi solo i markers
                    response_text = re.sub(r'```(?:json)?\s*|\s*```', '', response_text)
                    logger.info(f"Rimossi markers markdown: {response_text[:300]}")

            # Prova a trovare JSON anche se c'è testo prima/dopo
            json_match = re.search(r'\{[^{}]*"complete"[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(0)
                logger.info(f"Estratto JSON pattern: {response_text[:300]}")

            parsed = json.loads(response_text)
            logger.info(f"JSON parsed con successo: {str(parsed)}")
            return parsed

        except Exception as e:
            logger.error(f"Errore generazione next question: {e}", exc_info=True)
            # Fallback: continua con domanda generica invece di chiudere
            # (il sistema deciderà se chiudere in base al numero di domande)
            return {
                'complete': False,
                'question': "Mi può dare maggiori dettagli su questo aspetto? Esempi concreti, aneddoti o informazioni specifiche sarebbero molto utili."
            }

    def _complete_interview_and_generate(self):
        """
        Completa l'intervista e genera l'articolo pubbliredazionale
        """
        try:
            # Recupera dati intervista (contiene già website_content)
            interview_data = self.pubbliredazionale.interview_data or {}

            # Se non c'è website_content (vecchi pubbliredazionali), riscrapalo
            website_content = interview_data.get('website_content')
            if not website_content:
                logger.warning("website_content mancante, eseguo scraping profondo...")
                website_content = self._scrape_website_deep(self.pubbliredazionale.sito_web)
                interview_data['website_content'] = website_content

            # Ricerca web già fatta all'inizio, ma se manca rifalla
            if 'web_research' not in interview_data:
                logger.info("web_research mancante, eseguo ricerca...")
                web_research = self._perform_web_research(website_content)
                interview_data['web_research'] = web_research
                self.pubbliredazionale.interview_data = interview_data
                self.pubbliredazionale.save()

            # DISABILITATA: Ricerca post-intervista troppo lenta, causa timeout
            # Usiamo solo la ricerca iniziale + conversazione per generare l'articolo
            logger.info("Ricerca post-intervista saltata per evitare timeout")
            post_interview_research = {'findings': '', 'research_performed': False}

            # Genera articolo
            article = self._generate_article(interview_data)

            # Salva articolo
            self.pubbliredazionale.titolo = article['titolo']
            self.pubbliredazionale.contenuto = article['contenuto']
            self.pubbliredazionale.sommario = article['sommario']
            self.pubbliredazionale.status = 'interview_completed'
            self.pubbliredazionale.save()

            return {
                'success': True,
                'interview_complete': True,
                'message': 'Perfetto! Ho raccolto tutte le informazioni necessarie e ho generato l\'articolo pubbliredazionale.',
                'article': article
            }

        except Exception as e:
            logger.error(f"Errore complete_interview: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _complete_interview_deferred(self):
        """
        Completa l'intervista SENZA generare l'articolo immediatamente.
        L'articolo verrà generato in background dal management command.

        Questo approccio risolve il problema del timeout HTTP e migliora la UX
        creando la percezione di un lavoro editoriale umano.
        """
        try:
            from datetime import timedelta

            # Recupera dati intervista
            interview_data = self.pubbliredazionale.interview_data or {}

            # Assicurati che il website_content sia presente
            if not interview_data.get('website_content'):
                logger.warning("website_content mancante, eseguo scraping profondo...")
                website_content = self._scrape_website_deep(self.pubbliredazionale.sito_web)
                interview_data['website_content'] = website_content

            # Ricerca web iniziale se manca
            if 'web_research' not in interview_data:
                logger.info("web_research mancante, eseguo ricerca...")
                web_research = self._perform_web_research(interview_data.get('website_content', ''))
                interview_data['web_research'] = web_research

            # Salva i dati aggiornati
            self.pubbliredazionale.interview_data = interview_data
            self.pubbliredazionale.status = 'interview_completed'
            self.pubbliredazionale.save()

            # Calcola quando l'articolo sarà pronto
            ready_time = self._calculate_ready_time(self.pubbliredazionale.data_creazione)

            # Formatta orario per messaggio
            ready_str = ready_time.strftime("%d/%m/%Y alle ore %H:%M")

            logger.info(f"Intervista pubbliredazionale {self.pubbliredazionale.id} completata. Articolo pronto: {ready_str}")

            return {
                'success': True,
                'interview_complete': True,
                'deferred': True,
                'ready_time': ready_str,
                'message': f'Grazie! La redazione sta elaborando il suo pubbliredazionale.\n\nRiceverà una email di notifica entro il {ready_str} con il link per visualizzare l\'anteprima dell\'articolo.'
            }

        except Exception as e:
            logger.error(f"Errore complete_interview_deferred: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _calculate_ready_time(self, created_at):
        """
        Calcola quando il pubbliredazionale dovrebbe essere pronto.

        Logica per simulare lavoro editoriale umano:
        - Intervista completata 08:00-18:00 → Pronto dopo 107 minuti (1h 47min)
        - Intervista completata 18:00-08:00 → Pronto ore 09:02 giorno dopo
        """
        from datetime import timedelta

        hour = created_at.hour

        if 8 <= hour < 18:
            # Orario lavorativo → Pronto dopo 107 minuti
            ready = created_at + timedelta(minutes=107)
        else:
            # Sera/Notte → Pronto alle 09:02 del giorno dopo
            next_day = created_at + timedelta(days=1)
            ready = next_day.replace(hour=9, minute=2, second=0, microsecond=0)

        return ready

    def _perform_web_research(self, website_content):
        """
        Esegue ricerca web approfondita su azienda, mercato, storia
        Combina analisi del sito con ricerca narrativa orientata alla storia aziendale
        """
        try:
            logger.info(f"Inizio ricerca web approfondita per {self.pubbliredazionale.nome_azienda}")

            # Usa l'AI per analizzare il contenuto e creare una base narrativa
            system_prompt = """Sei un giornalista investigativo che raccoglie informazioni per scrivere una STORIA AZIENDALE coinvolgente.

Basandoti sulle informazioni del sito web aziendale, genera un'analisi NARRATIVA che includa:

1. **Storia e Origini**: Quando e come è nata l'azienda? Chi l'ha fondata? Perché? (se presente nel sito)
2. **Persone e Valori**: Chi c'è dietro? Quali valori emergono? Qual è la filosofia?
3. **Cosa Offre**: Prodotti/servizi DESCRITTI IN MODO NARRATIVO (non elenco tecnico)
4. **Il Territorio**: Legame con Carpi/Modena/territorio locale (se presente)
5. **Elementi Distintivi**: Cosa rende speciale questa realtà? (approccio, qualità, esperienza)
6. **Dettagli Interessanti**: Qualsiasi elemento che potrebbe diventare parte di una storia (aneddoti, particolarità, citazioni)

STILE: Scrivi come se stessi raccogliendo materiale per un articolo di giornale che racconta UNA STORIA, non un comunicato stampa.

Lunghezza: 500-700 parole, tono narrativo e giornalistico."""

            prompt = f"""Analizza questa azienda per raccogliere materiale narrativo:

Nome: {self.pubbliredazionale.nome_azienda}
Sito web: {self.pubbliredazionale.sito_web}

Contenuto del sito web:
{website_content[:4000]}

Genera un'analisi NARRATIVA che mi aiuti a scrivere una storia coinvolgente su questa azienda."""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,  # Ridotto da 1500 per velocità
                temperature=0.5,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Traccia utilizzo
            APIUsageTracker.track_anthropic(
                operation='publiredazionale_web_research',
                model='claude-sonnet-4-20250514',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            research_text = message.content[0].text.strip()
            logger.info(f"Ricerca web completata: {len(research_text)} caratteri di analisi generata")

            return {
                'research_performed': True,
                'findings': research_text,
                'market_analysis': research_text
            }

        except Exception as e:
            logger.error(f"Errore web research: {e}", exc_info=True)
            return {
                'research_performed': False,
                'error': str(e)
            }

    def _perform_post_interview_research(self, interview_data):
        """
        Ricerca post-intervista: analizza i dettagli emersi (prodotti/servizi citati)
        e fa ricerca su settore di mercato e domanda a cui rispondono
        """
        try:
            logger.info("Inizio ricerca post-intervista su dettagli specifici emersi")

            # Estrai la conversazione
            conversation = interview_data.get('conversation', [])
            conv_text = "\n".join([
                f"{'D' if msg['role'] == 'agent' else 'R'}: {msg['message']}"
                for msg in conversation
            ])

            # Usa l'AI per analizzare dettagli emersi e fare ricerca approfondita
            system_prompt = """Sei un analista di mercato e business intelligence expert.

Il tuo compito è analizzare l'intervista e fare una RICERCA APPROFONDITA su:

1. **Prodotti/Servizi Citati**: Se l'utente ha menzionato nomi specifici di prodotti/servizi/protocolli/strumenti
   → Spiega cosa sono, a cosa servono, perché sono importanti
   → Esempio: "Protocollo GEO" → spiega che si tratta di un metodo per SEO nell'era AI

2. **Settore di Mercato**: In quale settore opera l'azienda?
   → Trend attuali del settore
   → Sfide e opportunità
   → Evoluzione recente (ultimi 2-3 anni)

3. **Problema/Domanda di Mercato**: A quale bisogno/problema rispondono i prodotti/servizi?
   → Qual è il pain point dei clienti?
   → Come questi prodotti/servizi risolvono il problema?
   → Perché sono necessari ora?

4. **Contesto Competitivo**: Se applicabile
   → Quali sono le soluzioni alternative?
   → Cosa rende unico l'approccio di questa azienda?

IMPORTANTE:
- Usa i NOMI SPECIFICI citati nell'intervista (non generalizzare)
- Spiega in modo NARRATIVO e GIORNALISTICO (non tecnico/arido)
- Lunghezza: 600-800 parole
- Tono: informativo ma accessibile

Output: Analisi in formato testo (non JSON)."""

            prompt = f"""Azienda: {self.pubbliredazionale.nome_azienda}

INTERVISTA COMPLETA:
{conv_text}

Analizza l'intervista e genera una ricerca approfondita su:
- Prodotti/servizi/strumenti SPECIFICI citati (con nomi propri se menzionati)
- Settore di mercato e trend
- Problema/bisogno a cui rispondono
- Contesto competitivo

Scrivi in modo narrativo e giornalistico."""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                temperature=0.6,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Traccia utilizzo
            APIUsageTracker.track_anthropic(
                operation='publiredazionale_post_interview_research',
                model='claude-sonnet-4-20250514',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            research_text = message.content[0].text.strip()
            logger.info(f"Ricerca post-intervista completata: {len(research_text)} caratteri")

            return {
                'research_performed': True,
                'findings': research_text
            }

        except Exception as e:
            logger.error(f"Errore post-interview research: {e}", exc_info=True)
            return {
                'research_performed': False,
                'error': str(e)
            }

    def _research_business_type(self, company_name):
        """
        Ricerca veloce sul nome azienda per determinare il tipo di business
        Restituisce: {
            'business_type': 'product/experience' | 'problem-solving',
            'summary': 'Breve descrizione trovata'
        }
        """
        try:
            from home.web_search_tool import WebSearchTool

            logger.info(f"Ricerca business type per: {company_name}")

            # Ricerca rapida con limite di 3 risultati
            search_tool = WebSearchTool()
            query = f"{company_name} Carpi cosa fa attività"

            results = search_tool.search(query, max_results=3)

            if not results or len(results) == 0:
                logger.warning(f"Nessun risultato trovato per {company_name}")
                return {
                    'business_type': 'product/experience',  # Default sicuro
                    'summary': f"Nessuna informazione trovata online per {company_name}"
                }

            # Concatena i risultati
            search_summary = "\n".join([
                f"{r.get('title', '')}: {r.get('snippet', '')}"
                for r in results[:3]
            ])

            # Usa AI per classificare il business type
            classification_prompt = f"""Analizza queste informazioni su {company_name} e determina il tipo di business.

INFORMAZIONI TROVATE:
{search_summary[:1000]}

CLASSIFICAZIONE:
- PRODUCT/EXPERIENCE: Aziende che offrono prodotti tangibili o esperienze (ristoranti, gelaterie, negozi, artigiani, parrucchieri, palestre, hotel, etc.)
- PROBLEM-SOLVING: Aziende che risolvono problemi specifici (consulenze, servizi B2B, software, formazione, assistenza tecnica, etc.)

Rispondi in formato JSON:
{{
  "business_type": "product/experience" o "problem-solving",
  "summary": "Breve descrizione dell'attività in 1-2 frasi",
  "confidence": "high" o "medium" o "low"
}}"""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": classification_prompt
                }]
            )

            # Traccia utilizzo (non bloccante)
            try:
                APIUsageTracker.track_anthropic(
                    operation='business_type_classification',
                    model='claude-sonnet-4-20250514',
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                    success=True,
                    related_article=None
                )
            except Exception as track_error:
                logger.warning(f"Errore tracciamento API (non bloccante): {track_error}")

            # Parse JSON response
            import json
            response_text = message.content[0].text.strip()

            # Rimuovi markdown code block se presente
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            result = json.loads(response_text)

            logger.info(f"Business type classificato: {result.get('business_type')} (confidence: {result.get('confidence')})")

            return {
                'business_type': result.get('business_type', 'product/experience'),
                'summary': result.get('summary', search_summary[:500])
            }

        except Exception as e:
            logger.error(f"Errore research business type: {e}", exc_info=True)
            # Default sicuro in caso di errore
            return {
                'business_type': 'product/experience',
                'summary': f"Informazioni limitate disponibili per {company_name}"
            }

    def _scrape_website_deep(self, url):
        """
        Estrae contenuto approfondito dal sito web per analisi completa
        Riconosce profili social (Instagram, Facebook, LinkedIn) e li gestisce diversamente
        """
        try:
            # Rileva se è un profilo social
            social_platforms = {
                'instagram.com': 'Instagram',
                'facebook.com': 'Facebook',
                'fb.com': 'Facebook',
                'linkedin.com': 'LinkedIn',
                'twitter.com': 'Twitter/X',
                'x.com': 'Twitter/X',
                'tiktok.com': 'TikTok'
            }

            is_social = False
            platform_name = None
            for platform_domain, name in social_platforms.items():
                if platform_domain in url.lower():
                    is_social = True
                    platform_name = name
                    break

            if is_social:
                logger.info(f"Rilevato profilo social ({platform_name}): {url}")

                # Tenta di estrarre informazioni dal profilo social
                try:
                    scraper = SocialMediaScraper()
                    profile_data = scraper.extract_profile_info(url)

                    if profile_data.get('error'):
                        logger.warning(f"Impossibile estrarre info da {platform_name}: {profile_data.get('error')}")
                        social_info = f"Profilo {platform_name}: {url}\n(Informazioni non disponibili - userò intervista e web research)"
                    else:
                        # Formatta informazioni estratte
                        social_info = scraper.format_for_article_context(profile_data)
                        logger.info(f"Estratte informazioni da {platform_name}: {profile_data.get('name', 'N/A')}")

                    return social_info

                except Exception as e:
                    logger.error(f"Errore estrazione profilo {platform_name}: {e}")
                    return f"Profilo {platform_name}: {url}\n(Le informazioni saranno raccolte tramite intervista e web research)"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }

            logger.info(f"Scraping approfondito del sito: {url}")
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            response.raise_for_status()
            logger.info(f"HTTP Status: {response.status_code}, Content-Length: {len(response.content)}, Encoding: {response.encoding}")

            soup = BeautifulSoup(response.content, 'html.parser')

            # Estrai metadata importanti
            metadata = {}

            # Title
            title = soup.find('title')
            if title:
                metadata['title'] = title.get_text().strip()

            # Meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                metadata['description'] = meta_desc.get('content', '').strip()

            # Meta keywords
            meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
            if meta_keywords:
                metadata['keywords'] = meta_keywords.get('content', '').strip()

            # Rimuovi elementi non utili
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                element.decompose()

            # Estrai contenuto strutturato
            content_sections = {
                'headings': [],
                'paragraphs': [],
                'lists': [],
                'links': []
            }

            # Headings (H1-H3)
            for heading in soup.find_all(['h1', 'h2', 'h3']):
                text = heading.get_text().strip()
                if len(text) > 3:
                    content_sections['headings'].append(f"[{heading.name.upper()}] {text}")

            # Paragraphs
            for p in soup.find_all('p'):
                text = p.get_text().strip()
                if len(text) > 30:  # Solo paragrafi significativi
                    content_sections['paragraphs'].append(text)

            # Liste
            for ul in soup.find_all(['ul', 'ol']):
                items = []
                for li in ul.find_all('li', recursive=False):
                    text = li.get_text().strip()
                    if len(text) > 10:
                        items.append(f"• {text}")
                if items:
                    content_sections['lists'].extend(items)

            # Link importanti (solo testi anchor significativi)
            for a in soup.find_all('a', href=True):
                text = a.get_text().strip()
                if len(text) > 3 and len(text) < 100:
                    href = a.get('href', '')
                    if not href.startswith('#') and 'contatt' in text.lower() or 'servizi' in text.lower() or 'chi siamo' in text.lower():
                        content_sections['links'].append(f"Link: {text}")

            # Componi il testo finale strutturato
            full_text_parts = []

            # Metadata
            if metadata:
                full_text_parts.append("=== INFORMAZIONI BASE ===")
                if 'title' in metadata:
                    full_text_parts.append(f"Titolo sito: {metadata['title']}")
                if 'description' in metadata:
                    full_text_parts.append(f"Descrizione: {metadata['description']}")
                if 'keywords' in metadata:
                    full_text_parts.append(f"Keywords: {metadata['keywords']}")
                full_text_parts.append("")

            # Headings
            if content_sections['headings']:
                full_text_parts.append("=== STRUTTURA CONTENUTI ===")
                full_text_parts.extend(content_sections['headings'][:15])  # Prime 15 intestazioni
                full_text_parts.append("")

            # Paragraphs
            if content_sections['paragraphs']:
                full_text_parts.append("=== CONTENUTO PRINCIPALE ===")
                full_text_parts.extend(content_sections['paragraphs'][:20])  # Primi 20 paragrafi
                full_text_parts.append("")

            # Lists
            if content_sections['lists']:
                full_text_parts.append("=== ELEMENTI CHIAVE ===")
                full_text_parts.extend(content_sections['lists'][:15])  # Prime 15 voci

            full_text = '\n'.join(full_text_parts)

            # Limita a 5000 caratteri (aumentato da 3000)
            if len(full_text) > 5000:
                full_text = full_text[:5000] + '\n\n[... contenuto troncato ...]'

            logger.info(f"Estratti {len(full_text)} caratteri dal sito web")
            logger.info(f"Sezioni trovate - Headings: {len(content_sections['headings'])}, Paragraphs: {len(content_sections['paragraphs'])}, Lists: {len(content_sections['lists'])}")

            # Controlla se il contenuto estratto è sufficiente
            if len(full_text) < 100:
                logger.warning(f"Contenuto estratto troppo breve ({len(full_text)} caratteri) - possibile protezione anti-bot o contenuto dinamico")
                return ""

            return full_text

        except requests.RequestException as e:
            logger.error(f"Errore HTTP scraping profondo {url}: {e}")
            # Fallback: usa lo scraping base
            basic_info = self._scrape_website(url)
            return f"{basic_info.get('title', '')} {basic_info.get('description', '')} {basic_info.get('main_text', '')}"
        except Exception as e:
            logger.error(f"Errore scraping profondo {url}: {e}")
            # Fallback: usa lo scraping base
            basic_info = self._scrape_website(url)
            return f"{basic_info.get('title', '')} {basic_info.get('description', '')} {basic_info.get('main_text', '')}"

    def _generate_article(self, interview_data):
        """
        Genera l'articolo pubbliredazionale finale
        """
        system_prompt = """Sei un giornalista narrativo professionista che scrive STORIE AZIENDALI coinvolgenti per pubbliredazionali su un giornale locale (Carpi, Italia).

OBIETTIVO: Creare un RACCONTO che presenti l'azienda attraverso EMOZIONI, PERSONE, VALORI e STORIA - non un comunicato stampa.

APPROCCIO NARRATIVO:
- Scrivi una STORIA che faccia conoscere l'ANIMA dell'azienda
- Tono caldo, umano, giornalistico (come un reportage)
- Inizia con un'immagine, una scena, un momento che catturi
- Usa ANEDDOTI e DETTAGLI CONCRETI che facciano visualizzare
- Mostra le PERSONE, la PASSIONE, i VALORI dietro l'attività
- Connetti l'azienda al TERRITORIO (Carpi/Modena)
- Lunghezza: 500-700 parole

STRUTTURA NARRATIVA:
1. **Titolo evocativo** (deve far venire voglia di leggere, NON generico tipo "Innovazione e Qualità")
   Esempio: "Da un garage di Carpi all'Italia: la storia di..." oppure "Quando la passione diventa mestiere: ecco..."

2. **Apertura coinvolgente** (100-120 parole)
   - Inizia con una SCENA, un MOMENTO, un'IMMAGINE concreta
   - NON iniziare con "L'azienda X opera nel settore..."
   - Cattura subito con qualcosa di umano/emozionale

3. **Storia e Origini** (120-150 parole)
   - Come è nata? Chi l'ha creata? Perché?
   - La scintilla iniziale, il sogno, la motivazione
   - Usa i dettagli dell'intervista per creare una NARRAZIONE

4. **Il Cuore dell'Attività** (150-180 parole)
   - Cosa offre l'azienda (ma NARRATO, non elencato)
   - Chi c'è dietro, cosa li muove
   - Elementi distintivi raccontati attraverso STORIE
   - Approccio, valori, passione che emergono

5. **Connessione Umana e Territorio** (100-120 parole)
   - Aneddoti, esempi, storie di clienti
   - Legame con Carpi/territorio
   - Momenti significativi

6. **Chiusura Naturale** (60-80 parole)
   - Visione futura, dove vogliono andare
   - Invito naturale a conoscerli (NON "per maggiori informazioni...")
   - Chiudi con calore e autenticità
   - OBBLIGATORIO: Alla fine dell'articolo aggiungi il link al sito aziendale in modo naturale (es: "Per saperne di più, visita [nome azienda]" con link al sito)

REGOLE D'ORO - DETTAGLI SPECIFICI:
- **PRIORITÀ ASSOLUTA**: Usa TUTTI i dettagli specifici raccolti nell'intervista
  → Se menzionano "Protocollo GEO" o "GLIMPSE" → DEVI includerli nell'articolo
  → Se parlano di persone, nomi, anni → DEVI citarli
  → Se raccontano aneddoti → DEVI narrarli
- OGNI dettaglio tecnico/prodotto/servizio menzionato va INTEGRATO nella narrazione
- NON sostituire dettagli reali con descrizioni generiche
- NON inventare - usa SOLO ciò che è emerso
- EVITA frasi fatte: "eccellenza", "leader di settore", "sempre al vostro servizio", "punto di riferimento"
- EVITA aperture generiche tipo "L'azienda X rappresenta..." o "Da anni impegnati..."
- Scrivi come se raccontassi al bar la storia di qualcuno, MA citando i dettagli precisi che ti ha detto
- Il pubbliredazionale deve essere un RACCONTO CONCRETO, non una brochure generica

**VERIFICA FINALE**: Prima di completare, rileggi l'intervista e assicurati di aver incluso almeno 3-5 dettagli specifici menzionati dall'utente.

FORMATTAZIONE RICHIESTA:
- Il titolo è sempre plain text, senza markup HTML
- Per il contenuto usa <strong>grassetto</strong> per nomi di persone, aziende e fatti importanti
- Separa i paragrafi con tag <p></p>
- Crea una struttura chiara e leggibile
- Alla fine dell'articolo, SEMPRE inserire il link al sito aziendale usando <a href="URL">testo</a>

STRUTTURA CON HEADING:
- Usa <h2> per i sottotitoli principali delle sezioni
- Usa <h3> per le sottosezioni (se necessario)
- NON usare mai <h1> (riservato solo al titolo dell'articolo)
- Gli heading aiutano la leggibilità e la navigazione dell'articolo

Restituisci un JSON con:
{
    "titolo": "Titolo evocativo e coinvolgente (PLAIN TEXT, no HTML)",
    "sommario": "Breve sommario narrativo (2-3 frasi) che invogli alla lettura (PLAIN TEXT)",
    "contenuto": "Contenuto HTML con <p>, <strong> per nomi/fatti importanti, <h2>/<h3> per sezioni"
}"""

        # Prepara contesto
        nome_azienda = self.pubbliredazionale.nome_azienda
        sito_web = self.pubbliredazionale.sito_web

        # Nome intervistato se disponibile
        interviewer_name = ""
        if self.pubbliredazionale.intervistato_nome and self.pubbliredazionale.intervistato_cognome:
            interviewer_name = f"{self.pubbliredazionale.intervistato_nome} {self.pubbliredazionale.intervistato_cognome}"
        elif self.pubbliredazionale.intervistato_nome:
            interviewer_name = self.pubbliredazionale.intervistato_nome

        website_content = interview_data.get('website_content', '')
        conversation = interview_data.get('conversation', [])
        web_research = interview_data.get('web_research', {})
        post_research = interview_data.get('post_interview_research', {})

        # Converti conversazione in testo formattato
        conv_text = "\n\n".join([
            f"{'DOMANDA' if msg['role'] == 'agent' else 'RISPOSTA'}:\n{msg['message']}"
            for msg in conversation
        ])

        research_text = web_research.get('findings', '')
        post_research_text = post_research.get('findings', '')

        interviewer_line = f"INTERVISTATO: {interviewer_name} (puoi citarlo nell'articolo per personalizzare)" if interviewer_name else ""

        # Data odierna per contestualizzare
        from datetime import datetime
        oggi = datetime.now().strftime("%d/%m/%Y")

        prompt = f"""Scrivi un ARTICOLO GIORNALISTICO (pubbliredazionale) per:

AZIENDA: {nome_azienda}
{interviewer_line}
DATA ODIERNA: {oggi}

📊 HAI A DISPOSIZIONE 4 FONTI DI INFORMAZIONE:

1️⃣ CONTENUTO SITO WEB (usa per contesto aziendale generale):
{website_content[:8000]}

2️⃣ RICERCA MERCATO/SETTORE (usa per inquadrare settore, trend, problemi risolti):
{research_text[:3000]}

3️⃣ RICERCA APPROFONDITA POST-INTERVISTA (usa per spiegare prodotti/servizi specifici citati):
{post_research_text[:4000]}

4️⃣ INTERVISTA CON IL CLIENTE (FONTE PRINCIPALE - qui c'è il materiale narrativo):
{conv_text}

🎯 TUO COMPITO:

Scrivi un articolo di 500-700 parole che:

A) USA IL MATERIALE DELL'INTERVISTA come base narrativa
   - Tutti i dettagli specifici menzionati (nomi, prodotti, servizi, persone, date)
   - Le storie, aneddoti, esempi concreti raccontati
   - Il focus identificato nella prima risposta

B) ARRICCHISCI con informazioni dalle ricerche
   - Se cita "Protocollo GEO" → usa la ricerca per spiegare meglio cos'è
   - Se parla di un settore → usa la ricerca mercato per contestualizzare
   - Se menziona prodotti/servizi → integra con info dal sito/ricerche

C) SCRIVI COME UN GIORNALISTA
   - Titolo giornalistico (NO "Innovazione e Qualità")
   - Attacco coinvolgente (NO "L'azienda X rappresenta...")
   - Paragrafi narrativi che raccontano
   - Integrazione fluida di dettagli tecnici
   - Conclusione naturale

⚠️ VERIFICA FINALE:
Prima di completare, rileggi l'intervista e assicurati di aver usato:
- I nomi/termini specifici citati dal cliente
- Gli esempi/aneddoti raccontati
- Le informazioni delle ricerche per arricchire
- Il link al sito aziendale ({sito_web}) nella parte finale dell'articolo

Genera JSON."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=3000,  # Aumentato per articoli più ricchi
                temperature=0.8,  # Aumentato per più creatività narrativa
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Traccia utilizzo
            APIUsageTracker.track_anthropic(
                operation='publiredazionale_article_generation',
                model='claude-sonnet-4-20250514',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            response_text = message.content[0].text.strip()

            # Rimuovi markdown code blocks
            if response_text.startswith('```'):
                import re
                response_text = re.sub(r'^```json?\s*|\s*```$', '', response_text, flags=re.MULTILINE)

            article = json.loads(response_text)

            # Applica polishing al contenuto
            from .content_polisher import content_polisher
            article = content_polisher.polish_article(article)

            return article

        except Exception as e:
            logger.error(f"Errore generazione articolo: {e}", exc_info=True)
            # Fallback: articolo base
            return {
                'titolo': f"{nome_azienda}: Innovazione e Qualità al Servizio del Territorio",
                'sommario': f"{nome_azienda} rappresenta un punto di riferimento nel settore, offrendo soluzioni di qualità per i clienti.",
                'contenuto': f"<p><strong>{nome_azienda}</strong> è un'azienda che opera nel territorio di Carpi, offrendo servizi di qualità ai propri clienti.</p><p>Per maggiori informazioni, visita il sito <a href='{sito_web}'>{sito_web}</a>.</p>"
            }

    def regenerate_article(self, user_feedback):
        """
        Rigenera l'articolo basandosi sul feedback dell'utente
        """
        try:
            interview_data = self.pubbliredazionale.interview_data or {}
            interview_data['user_feedback'] = user_feedback

            # Rigenera con il feedback
            article = self._generate_article_with_feedback(interview_data, user_feedback)

            # Aggiorna articolo
            self.pubbliredazionale.titolo = article['titolo']
            self.pubbliredazionale.contenuto = article['contenuto']
            self.pubbliredazionale.sommario = article['sommario']
            self.pubbliredazionale.interview_data = interview_data
            self.pubbliredazionale.save()

            return {
                'success': True,
                'article': article
            }

        except Exception as e:
            logger.error(f"Errore regenerate_article: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _generate_article_with_feedback(self, interview_data, feedback):
        """
        Rigenera articolo considerando il feedback dell'utente
        """
        # Usa lo stesso prompt di _generate_article ma aggiunge il feedback
        system_prompt = """Sei un giornalista professionista che scrive articoli pubbliredazionali.

Hai già scritto un articolo, ma l'utente ha chiesto delle modifiche.
Riscrivi l'articolo tenendo conto del feedback fornito.

Mantieni lo stesso stile professionale e giornalistico.

FORMATTAZIONE RICHIESTA:
- Il titolo è sempre plain text, senza markup HTML
- Per il contenuto usa <strong>grassetto</strong> per nomi di persone, aziende e fatti importanti
- Separa i paragrafi con tag <p></p>
- Usa <h2> per i sottotitoli principali delle sezioni
- Usa <h3> per le sottosezioni (se necessario)
- NON usare mai <h1> (riservato solo al titolo dell'articolo)
- OBBLIGATORIO: Alla fine dell'articolo, aggiungi il link al sito aziendale con <a href="URL">testo</a>"""

        current_article = {
            'titolo': self.pubbliredazionale.titolo,
            'sommario': self.pubbliredazionale.sommario,
            'contenuto': self.pubbliredazionale.contenuto
        }

        # Ottieni sito web dall'oggetto pubbliredazionale
        sito_web = self.pubbliredazionale.sito_web or ''

        prompt = f"""Articolo corrente:
{json.dumps(current_article, indent=2, ensure_ascii=False)}

Feedback utente:
{feedback}

Sito web aziendale: {sito_web}

Riscrivi l'articolo applicando il feedback.

IMPORTANTE:
- Usa <strong> per evidenziare nomi di persone, aziende e fatti importanti nel contenuto
- Assicurati di includere il link al sito aziendale alla fine dell'articolo

Restituisci JSON con:
{{
    "titolo": "Titolo (PLAIN TEXT, no HTML)",
    "sommario": "Sommario (PLAIN TEXT)",
    "contenuto": "Contenuto HTML con <p>, <strong> per nomi/fatti importanti, <h2>/<h3> per sezioni, e link al sito aziendale alla fine"
}}"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                temperature=0.7,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Traccia utilizzo
            APIUsageTracker.track_anthropic(
                operation='publiredazionale_article_regeneration',
                model='claude-sonnet-4-20250514',
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                success=True
            )

            response_text = message.content[0].text.strip()

            if response_text.startswith('```'):
                import re
                response_text = re.sub(r'^```json?\s*|\s*```$', '', response_text, flags=re.MULTILINE)

            article = json.loads(response_text)

            # Applica polishing
            from .content_polisher import content_polisher
            article = content_polisher.polish_article(article)

            return article

        except Exception as e:
            logger.error(f"Errore rigenerazione articolo: {e}")
            return current_article  # Mantieni l'articolo corrente
