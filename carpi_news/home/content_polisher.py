"""
Modulo per uniformare e pulire il contenuto degli articoli
Rimuove emoji, simboli e uniforma il layout
"""
import re
from typing import Dict, Any


class ContentPolisher:
    """Classe per pulire e uniformare il contenuto degli articoli"""
    
    def __init__(self):
        # Pattern per rimuovere simboli e emoji
        self.emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "\U00002702-\U000027B0"  # dingbats
            "\U000024C2-\U0001F251"  # enclosed characters
            "]+", flags=re.UNICODE
        )
        
        # Pattern per simboli extra
        self.symbol_patterns = [
            re.compile(r'[⚽🏆🎯💪👏🔥⭐✨🎉🚀💯🏅🎊]'),  # Simboli sportivi comuni
            re.compile(r'[📰📢📅🏛️📋📌💼🔗📄📊]'),     # Simboli istituzionali
            re.compile(r'[▪️▫️●○■□◆◇★☆♦♣♠♥]'),      # Simboli geometrici
            re.compile(r'[➤➜➡️⬅️⬆️⬇️↗️↘️↙️↖️]'),       # Frecce
            re.compile(r'[✅❌✔️❎⚠️🚫🛑📍📎]'),       # Check e avvisi
        ]
        
        # Pattern per convertire markdown in HTML
        self.markdown_to_html_patterns = [
            (re.compile(r'\*\*([^*]+)\*\*'), r'<strong>\1</strong>'),  # **bold** -> <strong>
            (re.compile(r'\*([^*]+)\*'), r'<em>\1</em>'),              # *italic* -> <em>
            (re.compile(r'__([^_]+)__'), r'<strong>\1</strong>'),      # __bold__ -> <strong>
            (re.compile(r'_([^_]+)_'), r'<em>\1</em>'),                # _italic_ -> <em>
            (re.compile(r'^#{3}\s*(.+)$', re.MULTILINE), r'<h3>\1</h3>'),  # ### -> <h3>
            (re.compile(r'^#{2}\s*(.+)$', re.MULTILINE), r'<h2>\1</h2>'),  # ## -> <h2>
            (re.compile(r'^#{1}\s*(.+)$', re.MULTILINE), r'<h1>\1</h1>'),  # # -> <h1>
        ]
        
        # Pattern per convertire elenchi
        self.list_patterns = [
            (re.compile(r'^\s*[-•*]\s*(.+)$', re.MULTILINE), r'<li>\1</li>'),  # - item -> <li>
            (re.compile(r'^\s*\d+\.\s*(.+)$', re.MULTILINE), r'<li>\1</li>'),  # 1. item -> <li>
        ]
        
        # Pattern per pulire spazi extra
        self.spacing_patterns = [
            (re.compile(r'\n{3,}'), '\n\n'),          # Max 2 newlines
            (re.compile(r'[ \t]{2,}'), ' '),          # Max 1 space
            (re.compile(r'\n\s*\n'), '\n\n'),         # Clean empty lines
        ]
    
    def clean_title(self, title: str) -> str:
        """Pulisce un titolo da simboli e emoji"""
        if not title:
            return ""
        
        # Rimuovi emoji
        title = self.emoji_pattern.sub('', title)
        
        # Rimuovi altri simboli
        for pattern in self.symbol_patterns:
            title = pattern.sub('', title)
        
        # Converti markdown in HTML
        for pattern, replacement in self.markdown_to_html_patterns:
            title = pattern.sub(replacement, title)
        
        # Pulisci spazi
        title = re.sub(r'\s+', ' ', title)
        title = title.strip()
        
        # Rimuovi doppi punti all'inizio (comune in titoli markdown)
        title = re.sub(r'^[:\-\s]+', '', title)
        
        return title
    
    def clean_title_plain(self, title: str) -> str:
        """Pulisce un titolo SENZA applicare formattazione HTML"""
        if not title:
            return ""
        
        # Rimuovi emoji
        title = self.emoji_pattern.sub('', title)
        
        # Rimuovi altri simboli
        for pattern in self.symbol_patterns:
            title = pattern.sub('', title)
        
        # Rimuovi markdown E HTML (tutto viene convertito in plain text)
        for pattern, replacement in self.markdown_to_html_patterns:
            if isinstance(replacement, str) and '<' in replacement:
                # Se il replacement contiene HTML, usa solo il testo
                plain_replacement = r'\1'  # Prendi solo il contenuto del gruppo
                title = pattern.sub(plain_replacement, title)
            else:
                title = pattern.sub(replacement, title)
        
        # Rimuovi eventuali tag HTML rimasti
        title = re.sub(r'<[^>]+>', '', title)
        
        # Pulisci spazi
        title = re.sub(r'\s+', ' ', title)
        title = title.strip()
        
        # Rimuovi doppi punti all'inizio
        title = re.sub(r'^[:\-\s]+', '', title)
        
        return title
    
    def clean_content_plain(self, content: str) -> str:
        """Pulisce il contenuto SENZA applicare formattazione HTML"""
        if not content:
            return ""
        
        # Rimuovi emoji
        content = self.emoji_pattern.sub('', content)
        
        # Rimuovi altri simboli
        for pattern in self.symbol_patterns:
            content = pattern.sub('', content)
        
        # Rimuovi markdown E HTML (tutto diventa plain text)
        for pattern, replacement in self.markdown_to_html_patterns:
            if isinstance(replacement, str) and '<' in replacement:
                # Se il replacement contiene HTML, usa solo il testo
                plain_replacement = r'\1'
                content = pattern.sub(plain_replacement, content)
            else:
                content = pattern.sub(replacement, content)
        
        # Rimuovi eventuali tag HTML rimasti
        content = re.sub(r'<[^>]+>', '', content)
        
        # Pulisci spaziatura
        for pattern, replacement in self.spacing_patterns:
            content = pattern.sub(replacement, content)
        
        # Pulisci linee che contengono solo simboli
        content = re.sub(r'^[^\w\s]*$', '', content, flags=re.MULTILINE)
        
        # Rimuovi linee vuote all'inizio e alla fine
        content = content.strip()
        
        return content
    
    def clean_content(self, content: str) -> str:
        """Pulisce il contenuto dell'articolo"""
        if not content:
            return ""
        
        # Rimuovi emoji
        content = self.emoji_pattern.sub('', content)
        
        # Rimuovi altri simboli
        for pattern in self.symbol_patterns:
            content = pattern.sub('', content)
        
        # Converti markdown in HTML
        for pattern, replacement in self.markdown_to_html_patterns:
            content = pattern.sub(replacement, content)
        
        # Converti elenchi
        for pattern, replacement in self.list_patterns:
            content = pattern.sub(replacement, content)
        
        # Pulisci spaziatura
        for pattern, replacement in self.spacing_patterns:
            content = pattern.sub(replacement, content)
        
        # Pulisci linee che contengono solo simboli
        content = re.sub(r'^[^\w\s]*$', '', content, flags=re.MULTILINE)
        
        # Rimuovi linee vuote all'inizio e alla fine
        content = content.strip()
        
        return content
    
    def format_article_structure(self, content: str) -> str:
        """Formatta la struttura dell'articolo in modo uniforme con HTML"""
        if not content:
            return ""
        
        # Normalizza i line break - mantieni struttura paragrafi
        content = re.sub(r'\r\n', '\n', content)  # Windows -> Unix
        content = re.sub(r'\n{3,}', '\n\n', content)  # Max 2 newlines consecutive
        
        # Dividi in paragrafi mantenendo la struttura
        paragraphs = content.split('\n\n')
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        
        formatted_paragraphs = []
        i = 0
        
        while i < len(paragraphs):
            paragraph = paragraphs[i]
            
            # Rimuovi spazi multipli all'interno del paragrafo
            paragraph = re.sub(r'\s+', ' ', paragraph)
            
            # Se è già un header HTML, mantienilo
            if re.match(r'^<h[1-6]>', paragraph):
                formatted_paragraphs.append(paragraph)
            # Se contiene solo elementi lista
            elif re.match(r'^(<li>.*</li>\s*)+$', paragraph, re.DOTALL):
                formatted_paragraphs.append(paragraph)
            # Se il paragrafo contiene elementi lista mescolati
            elif '<li>' in paragraph:
                # Separa gli elementi lista dal testo normale
                parts = re.split(r'(<li>.*?</li>)', paragraph)
                current_text = ""
                list_items = []
                
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                        
                    if part.startswith('<li>') and part.endswith('</li>'):
                        # È un elemento lista
                        if current_text:
                            # Aggiungi il testo accumulato come paragrafo
                            if not current_text.endswith(('.', '!', '?', ':', '"')):
                                current_text += '.'
                            formatted_paragraphs.append(f'<p>{current_text}</p>')
                            current_text = ""
                        list_items.append(part)
                    else:
                        # È testo normale
                        if list_items:
                            # Aggiungi la lista accumulata
                            formatted_paragraphs.append(' '.join(list_items))
                            list_items = []
                        current_text += part + " "
                
                # Aggiungi quello che resta
                if current_text:
                    current_text = current_text.strip()
                    if not current_text.endswith(('.', '!', '?', ':', '"')):
                        current_text += '.'
                    formatted_paragraphs.append(f'<p>{current_text}</p>')
                if list_items:
                    formatted_paragraphs.append(' '.join(list_items))
            else:
                # Paragrafo normale di testo
                # Assicurati che termini correttamente
                if paragraph and not re.search(r'[.!?:"]\s*(<[^>]+>)*\s*$', paragraph):
                    paragraph += '.'
                
                # Aggiungi tag <p> solo se non contiene già tag HTML di blocco
                if not re.search(r'<(p|div|h[1-6]|ul|ol|li)', paragraph):
                    paragraph = f'<p>{paragraph}</p>'
                
                formatted_paragraphs.append(paragraph)
            
            i += 1
        
        # Raggruppa elementi <li> consecutivi in <ul>
        final_content = self._wrap_lists_in_ul_tags('\n\n'.join(formatted_paragraphs))
        
        return final_content
    
    def _wrap_lists_in_ul_tags(self, content: str) -> str:
        """Raggruppa elementi <li> consecutivi in <ul>"""
        # Trova gruppi di <li> consecutivi
        lines = content.split('\n\n')
        result = []
        current_list = []
        
        for line in lines:
            line = line.strip()
            if line.startswith('<li>') and line.endswith('</li>'):
                current_list.append(line)
            else:
                # Se c'era una lista in corso, chiudila
                if current_list:
                    result.append('<ul>')
                    result.extend(current_list)
                    result.append('</ul>')
                    current_list = []
                
                # Aggiungi la riga corrente
                if line:
                    result.append(line)
        
        # Se c'era una lista alla fine, chiudila
        if current_list:
            result.append('<ul>')
            result.extend(current_list)
            result.append('</ul>')
        
        return '\n\n'.join(result)

    def add_internal_links(self, content: str, article_title: str = "") -> str:
        """
        Aggiunge link interni al contenuto estraendo entità e cercandole negli articoli precedenti

        Strategia efficiente:
        1. AI estrae entità specifiche dall'articolo corrente (nomi, luoghi, enti, eventi)
        2. Per ogni entità, cerca nel DB il primo articolo approvato che la contiene
        3. Linka alla prima occorrenza trovata, creando una catena cronologica inversa

        Args:
            content: Contenuto HTML dell'articolo
            article_title: Titolo dell'articolo (per context)

        Returns:
            Contenuto con link interni inseriti
        """
        try:
            from anthropic import Anthropic
            from django.conf import settings
            import json
            import os
            import re

            # Get API key
            api_key = settings.ANTHROPIC_API_KEY if hasattr(settings, 'ANTHROPIC_API_KEY') else None
            if not api_key:
                api_key = os.getenv('ANTHROPIC_API_KEY')

            if not api_key:
                return content  # Nessun link se non c'è API key

            # Import qui per evitare circular imports
            from home.models import Articolo

            # Verifica che ci siano articoli approvati
            if Articolo.objects.filter(approvato=True).count() < 3:
                return content  # Non abbastanza articoli

            # Estrai testo plain dal contenuto HTML per l'analisi
            plain_content = re.sub(r'<[^>]+>', '', content)
            plain_content = plain_content[:3000]  # Prime 3000 caratteri

            # Prompt semplificato: chiediamo solo di estrarre entità
            prompt = f"""Sei un esperto di analisi testuale per un giornale locale di Carpi (Emilia-Romagna).

ARTICOLO DA ANALIZZARE:
Titolo: {article_title}
Contenuto: {plain_content}

TASK:
Estrai dall'articolo TUTTE le entità specifiche che potrebbero essere menzionate in altri articoli del giornale.

CATEGORIE DA ESTRARRE:
1. **NOMI DI PERSONE** - nome e cognome completi
   Esempi: "Riccardo Righi", "Alberto Bellelli", "Giulia Pigoni"

2. **ORGANIZZAZIONI/ENTI/AZIENDE** - nomi ufficiali completi
   Esempi: "AIMAG", "Carpi FC", "Comune di Carpi", "ASL", "Confindustria"

3. **LUOGHI SPECIFICI** - edifici, piazze, vie (NON solo "Carpi")
   Esempi: "Teatro Comunale", "Piazza Martiri", "Ospedale Ramazzini", "Palazzo dei Pio"

4. **ISTITUZIONI LOCALI**
   Esempi: "Consiglio comunale", "Giunta comunale", "Provincia di Modena"

5. **ASSOCIAZIONI/SINDACATI/PARTITI**
   Esempi: "Avis Carpi", "Cgil", "Partito Democratico", "Fratelli d'Italia"

6. **EVENTI SPECIFICI** - manifestazioni con nome proprio
   Esempi: "Festa di San Bernardino", "Carpi Fashion System", "Notte Bianca"

REGOLE:
- Estrai SOLO entità che appaiono testualmente nell'articolo
- Usa il nome esatto come appare nel testo
- NO termini generici ("sindaco", "ospedale", "città")
- NO "Carpi" da solo (troppo generico)
- Massimo 10 entità, priorità alle più rilevanti

FORMATO OUTPUT (solo JSON valido):
{{
  "entities": [
    {{
      "text": "testo esatto come appare nell'articolo",
      "type": "persona|organizzazione|luogo|istituzione|associazione|evento"
    }}
  ]
}}

Se non trovi entità specifiche, restituisci {{"entities": []}}
"""

            # Chiama Claude
            client = Anthropic(api_key=api_key)

            # Log AI response per debug
            import logging
            logger = logging.getLogger(__name__)

            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1500,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
            except Exception as e:
                logger.error(f"Internal Linking: errore API per '{article_title[:50]}...': {e}")
                return content

            # Parse risposta
            if not response.content or len(response.content) == 0:
                logger.warning(f"Internal Linking: response.content vuoto per '{article_title[:50]}...'")
                return content

            response_text = response.content[0].text.strip()

            # Se risposta vuota, ritorna contenuto originale
            if not response_text:
                logger.warning(f"Internal Linking: response_text vuoto per '{article_title[:50]}...'")
                return content

            logger.info(f"Internal Linking AI Response for '{article_title[:50]}...': {response_text[:200]}...")

            if response_text.startswith("```"):
                response_text = re.sub(r'^```json?\s*', '', response_text)
                response_text = re.sub(r'\s*```$', '', response_text)

            # Gestisci JSON invalido
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error(f"Internal Linking: JSON invalido per '{article_title[:50]}...': {e}")
                return content

            entities = result.get("entities", [])

            if not entities:
                logger.info(f"Internal Linking: nessuna entità trovata per '{article_title[:50]}...'")
                return content

            logger.info(f"Internal Linking: trovate {len(entities)} entità per '{article_title[:50]}...'")

            # Per ogni entità, cerca il primo articolo approvato che la contiene
            modified_content = content
            links_applied = 0
            linked_entities = set()  # Traccia entità già linkate per evitare duplicati

            for entity_data in entities:
                entity_text = entity_data.get("text", "")
                entity_type = entity_data.get("type", "")

                if not entity_text:
                    continue

                # Salta se questa entità è già stata linkata
                entity_lower = entity_text.lower()
                if entity_lower in linked_entities:
                    continue

                # Cerca nel DB il primo articolo approvato (più vecchio) che contiene questa entità
                # Ordina per data pubblicazione ASC per trovare il primo cronologicamente
                matching_article = Articolo.objects.filter(
                    approvato=True,
                    contenuto__icontains=entity_text
                ).order_by('data_pubblicazione').first()

                if not matching_article:
                    logger.debug(f"Internal Linking: entità '{entity_text}' non trovata in altri articoli")
                    continue

                # Applica il link alla prima occorrenza dell'entità nel contenuto
                escaped_entity = re.escape(entity_text)
                # Pattern: cerca l'entità ma non dentro tag HTML o link esistenti
                pattern = re.compile(
                    r'(?<![">])(' + escaped_entity + r')(?![^<]*</a>)',
                    re.IGNORECASE
                )

                match = pattern.search(modified_content)
                if match:
                    matched_text = match.group(1)
                    replacement = f'<a href="/articolo/{matching_article.slug}/" class="internal-link" title="{matching_article.titolo}">{matched_text}</a>'
                    modified_content = pattern.sub(replacement, modified_content, count=1)
                    links_applied += 1
                    linked_entities.add(entity_lower)  # Marca come linkata
                    logger.debug(f"Internal Linking: linkato '{entity_text}' ({entity_type}) -> {matching_article.slug}")

            if links_applied > 0:
                logger.info(f"Internal Linking: applicati {links_applied} link per '{article_title[:50]}...'")

            return modified_content

        except Exception as e:
            # In caso di errore, restituisci contenuto originale
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Errore add_internal_links: {e}")
            return content

    def polish_article(self, article_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applica polishing completo a un articolo
        
        Args:
            article_data: Dizionario con titolo, contenuto, etc.
        
        Returns:
            Dizionario con contenuto pulito e formattato
        """
        polished = article_data.copy()
        
        # Pulisci titolo (SOLO pulizia, NO formattazione HTML)
        if 'title' in polished:
            polished['title'] = self.clean_title_plain(polished['title'])
        
        if 'titolo' in polished:
            polished['titolo'] = self.clean_title_plain(polished['titolo'])
        
        # Pulisci contenuto (CON formattazione HTML)
        if 'content' in polished:
            cleaned = self.clean_content(polished['content'])
            formatted = self.format_article_structure(cleaned)
            # Aggiungi link interni
            polished['content'] = self.add_internal_links(
                formatted,
                article_title=polished.get('title', polished.get('titolo', ''))
            )

        if 'contenuto' in polished:
            cleaned = self.clean_content(polished['contenuto'])
            formatted = self.format_article_structure(cleaned)
            # Aggiungi link interni
            polished['contenuto'] = self.add_internal_links(
                formatted,
                article_title=polished.get('titolo', polished.get('title', ''))
            )

        # Pulisci preview/sommario (SOLO pulizia, NO formattazione HTML)
        if 'preview' in polished:
            polished['preview'] = self.clean_content_plain(polished['preview'])
        
        if 'sommario' in polished:
            polished['sommario'] = self.clean_content_plain(polished['sommario'])
        
        return polished
    
    def extract_clean_title_from_ai_response(self, ai_text: str) -> tuple[str, str]:
        """
        Estrae titolo e contenuto puliti da una risposta AI
        
        Returns:
            tuple: (titolo_plain, contenuto_con_html)
        """
        if not ai_text:
            return "", ""
        
        # Dividi in righe
        lines = ai_text.split('\n')
        
        # Prima riga non vuota è il titolo
        title = ""
        content_lines = []
        title_found = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if not title_found:
                # Prima riga significativa è il titolo - SEMPRE PLAIN TEXT
                title = self.clean_title_plain(line)
                title_found = True
            else:
                # Resto è contenuto - PUÒ AVERE MARKUP
                content_lines.append(line)
        
        # Riunisci il contenuto CON formattazione HTML
        content = '\n'.join(content_lines)
        content = self.format_article_structure(self.clean_content(content))
        
        return title, content


# Istanza globale del polisher
content_polisher = ContentPolisher()


# Funzioni di utilità
def clean_title(title: str) -> str:
    """Pulisce un titolo da simboli e emoji"""
    return content_polisher.clean_title(title)


def clean_content(content: str) -> str:
    """Pulisce il contenuto da simboli e emoji"""
    return content_polisher.clean_content(content)


def polish_article(article_data: Dict[str, Any]) -> Dict[str, Any]:
    """Applica polishing completo a un articolo"""
    return content_polisher.polish_article(article_data)


# Test del modulo
if __name__ == "__main__":
    print("=== TEST CONTENT POLISHER ===")
    
    # Test titolo
    test_title = "**Grande Vittoria** del Carpi FC! [EMOJI]"
    clean_title_result = clean_title(test_title)
    print(f"Titolo originale: {test_title}")
    print(f"Titolo pulito: {clean_title_result}")
    
    # Test contenuto
    test_content = """
    [EMOJI] **Una partita incredibile!** [EMOJI]
    
    Il Carpi FC ha dimostrato [EMOJI] grande determinazione...
    
    [EMOJI] I punti salienti:
    • Gol al 15' [EMOJI]
    • Parata decisiva [EMOJI]  
    • Vittoria meritata! [CHECKMARK]
    
    [EMOJI] Complimenti alla squadra! [EMOJI]
    """
    
    clean_content_result = clean_content(test_content)
    print(f"\nContenuto originale:\n{test_content}")
    print(f"\nContenuto pulito:\n{clean_content_result}")
    
    # Test articolo completo
    test_article = {
        'title': '[EMOJI] **Carpi Vince Derby** [EMOJI]',
        'content': test_content,
        'preview': '[EMOJI] Grande vittoria del Carpi! [EMOJI]'
    }
    
    polished = polish_article(test_article)
    print(f"\n=== ARTICOLO COMPLETO ===")
    print(f"Titolo: {polished['title']}")
    print(f"Preview: {polished['preview']}")
    print(f"Contenuto:\n{polished['content']}")
    
    print("\n[SPARKLE] Test completato!")