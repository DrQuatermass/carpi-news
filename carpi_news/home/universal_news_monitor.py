import requests
import time
import threading
import logging
import os
import tempfile
import platform
import uuid
import subprocess
import hashlib
import io
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
from django.utils import timezone
from urllib.parse import urljoin, urlparse
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.db import transaction
from PIL import Image

from home.models import Articolo, MonitorConfig

# Import platform-specific locking
if platform.system() == 'Windows':
    import msvcrt
else:
    import fcntl

# Import configurazione logging centralizzata
from home.logger_config import get_monitor_logger
from home.content_polisher import content_polisher

# Il logger sarà configurato dinamicamente per ogni monitor


TAGS_INSTRUCTION = """

Nel campo JSON "tags", inserisci 3-5 tag pertinenti, specifici per l'argomento.
Esempio: ["Carpi calcio", "Serie D", "stadio Cabassi"]
"""


MAX_SOURCE_CHARS = 20000  # ~6.500 token - margine extra


# Guardrail anti-invenzione per fonti brevissime (tweet della Polizia Locale, ecc.).
# I tweet contengono pochissime informazioni: il modello tende a "riempire" con
# dettagli plausibili ma inventati (reazioni, numeri, conseguenze, scene). Qui gli
# imponiamo di restare aderente ai fatti dichiarati, anche a costo di un articolo corto.
TWITTER_FIDELITY_GUARDRAILS = """

FEDELTA' AI FATTI (OBBLIGATORIO - la fonte e' un tweet, quindi molto breve):
- Riporta SOLO i fatti realmente presenti nel tweet o confermati dalla ricerca web. Non inventare nulla.
- NON aggiungere dettagli non verificabili: reazioni della gente, code ai supermercati, disagi a bar/negozi, numeri di persone coinvolte, dichiarazioni, orari, cause del problema, tempi di ripristino, se non sono esplicitamente nel tweet o in una fonte verificata.
- NON descrivere scene o conseguenze che non puoi verificare ("cittadini alle prese con...", "in tanti si sono riversati...").
- Puoi aggiungere solo contesto FATTUALE e verificabile (es. chi e' il gestore del servizio, dove si trova un luogo), citandolo dalla ricerca web.
- Se il tweet dice poco, l'articolo sara' breve: va bene. Meglio 4-5 frase corrette che un pezzo lungo pieno di dettagli inventati.
- Nel dubbio su un dettaglio, omettilo.
"""


ARTICLE_OUTPUT_GUARDRAILS = """

REGOLE DI OUTPUT OBBLIGATORIE:
- Non mostrare mai reasoning, analisi, note di lavoro, frasi come "ho trovato" o "posso costruire".
- Non ripetere il titolo nel corpo dell'articolo.
- Non iniziare il corpo con un elenco puntato o numerato.
- Evita elenchi puntati salvo necessita' giornalistica reale.
- Usa frasi fluide con virgole; evita trattini e incisi con "-".
- Rispondi solo con JSON valido, senza markdown, senza blocchi ``` e senza testo fuori dal JSON.
- Il JSON deve avere esattamente questi campi: "titolo", "titolo_seo", "sommario", "contenuto", "tags".
- "titolo": titolo editoriale narrativo e coinvolgente per il lettore.
- "titolo_seo": title tag per Google, MAX 60 caratteri, struttura SOGGETTO + LUOGO + AZIONE, deve contenere le parole chiave esatte che qualcuno cercherebbe su Google per questa notizia. Includi sempre "Carpi" o il nome specifico della persona/luogo. STILE: cronaca giornalistica italiana naturale come voce.it, sulpanaro.net, modenatoday.it. VIETATI: titoli clickbait ("rivoluzione silenziosa", "non crederai", "svela il segreto"), frasi che iniziano con "Quando la/il", metafore astratte, "X rock" fuori contesto musica, parole inventate o storpiate. Esempio buono: "AIMAG Carpi: Morelli chiede trasparenza sulle nomine". Esempio CATTIVO: "Tortellini rock quando pasta diventa rivoluzione silenziosa". Se non riesci a creare un titolo_seo migliore del titolo, usa "".
- "sommario" deve essere plain text, senza HTML.
- "contenuto" deve contenere HTML con <p>, <strong>, <h2>/<h3> dove serve, mai <h1>.
- "tags" deve essere un array di stringhe.
"""


def truncate_ai_source_text(content: str, logger, label: str = "Contenuto sorgente") -> str:
    if isinstance(content, str) and len(content) > MAX_SOURCE_CHARS:
        logger.warning(
            f"{label} troncato: {len(content):,} -> "
            f"{MAX_SOURCE_CHARS:,} chars per ottimizzazione costi"
        )
        return content[:MAX_SOURCE_CHARS]
    return content


def get_message_content_length(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                total += len(block.get('text', '') or block.get('content', '') or '')
            else:
                total += len(getattr(block, 'text', '') or getattr(block, 'content', '') or '')
        return total
    return 0


def limit_conversation_messages(messages: list, logger) -> None:
    total_input = sum(get_message_content_length(m.get('content', '')) for m in messages if isinstance(m, dict))
    if total_input <= MAX_SOURCE_CHARS * 3:
        return

    logger.warning(
        f"Contesto conversazionale troncato: {total_input:,} -> "
        f"{MAX_SOURCE_CHARS * 3:,} chars massimo stimato"
    )

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get('content')
        if isinstance(content, str) and len(content) > MAX_SOURCE_CHARS:
            msg['content'] = content[:MAX_SOURCE_CHARS]
            break

    total_input = sum(get_message_content_length(m.get('content', '')) for m in messages if isinstance(m, dict))
    if total_input <= MAX_SOURCE_CHARS * 3:
        return

    for msg in reversed(messages):
        content = msg.get('content') if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and isinstance(block.get('content'), str) and len(block['content']) > MAX_SOURCE_CHARS:
                block['content'] = block['content'][:MAX_SOURCE_CHARS]
                return


def extract_tags(content: str, categoria: str) -> tuple[str, str]:
    """
    Estrae e rimuove la riga TAGS: dal contenuto.
    Restituisce (content_pulito, tags_string).
    """
    tags = ''
    match = re.search(r'\nTAGS:\s*(.+)$', content or '', re.MULTILINE)
    if match:
        tags_raw = match.group(1).strip()
        tags = tags_raw.strip('"\'')[:200]
        content = content[:match.start()].strip()

    base_tags = [t.strip() for t in tags.split(',') if t.strip()]
    existing_tags = {tag.lower() for tag in base_tags}
    if 'carpi' not in existing_tags:
        base_tags.append('Carpi')
    if categoria and categoria.lower() not in existing_tags:
        base_tags.append(categoria)
    return (content or '').strip(), ', '.join(base_tags[:6])


def normalize_ai_tags(tags_value, categoria: str) -> str:
    """Normalizza tag AI da JSON e aggiunge tag base editoriali."""
    if isinstance(tags_value, list):
        base_tags = [str(t).strip() for t in tags_value if str(t).strip()]
    elif isinstance(tags_value, str):
        tags_clean = tags_value.strip().strip('[]')
        base_tags = [t.strip().strip('"\'') for t in tags_clean.split(',') if t.strip()]
    else:
        base_tags = []

    existing_tags = {tag.lower() for tag in base_tags}
    if 'carpi' not in existing_tags:
        base_tags.append('Carpi')
    if categoria and categoria.lower() not in existing_tags:
        base_tags.append(categoria)

    return ', '.join(base_tags[:6])


def parse_ai_article_json(response_text: str) -> Optional[Dict[str, Any]]:
    """Estrae un articolo JSON dalla risposta AI, con tolleranza per code fence."""
    if not response_text:
        return None

    cleaned = response_text.strip()
    cleaned = re.sub(r'^```json?\s*|\s*```$', '', cleaned, flags=re.MULTILINE).strip()

    if not cleaned.startswith('{'):
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]

    try:
        parsed = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError):
        parsed = _parse_loose_ai_article_json(cleaned)
        if not parsed:
            return None

    if not isinstance(parsed, dict):
        return None

    if not parsed.get('titolo') or not parsed.get('contenuto'):
        return None

    return parsed


def _parse_loose_ai_article_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Recupera risposte AI che hanno forma JSON ma non sono JSON valido.

    Il caso piu' comune e' un campo "contenuto" multilinea con newline reali o
    virgolette tipografiche/non escapate dentro il testo. Se non lo recuperiamo
    qui, il fallback legacy salva pezzi come '"sommario": ...' nel corpo articolo.
    """
    if not text or '"contenuto"' not in text:
        return None

    def _extract_between(field: str, next_fields: tuple[str, ...]) -> str:
        field_match = re.search(rf'"{re.escape(field)}"\s*:\s*', text)
        if not field_match:
            return ''

        start = field_match.end()
        end = len(text)
        for next_field in next_fields:
            next_match = re.search(rf',\s*"{re.escape(next_field)}"\s*:', text[start:], flags=re.DOTALL)
            if next_match:
                end = min(end, start + next_match.start())

        value = text[start:end].strip().rstrip(',').strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith('"'):
            value = value[1:]

        return value.strip()

    titolo = _extract_between('titolo', ('titolo_seo', 'sommario', 'contenuto', 'tags'))
    titolo_seo = _extract_between('titolo_seo', ('sommario', 'contenuto', 'tags'))
    sommario = _extract_between('sommario', ('contenuto', 'tags'))
    contenuto = _extract_between('contenuto', ('tags',))

    tags = []
    tags_match = re.search(r'"tags"\s*:\s*(\[[\s\S]*?\])', text)
    if tags_match:
        try:
            parsed_tags = json.loads(tags_match.group(1))
            if isinstance(parsed_tags, list):
                tags = parsed_tags
        except json.JSONDecodeError:
            tags = [
                tag.strip().strip('"\'')
                for tag in tags_match.group(1).strip('[]').split(',')
                if tag.strip()
            ]

    if not titolo or not contenuto:
        return None

    return {
        'titolo': titolo,
        'titolo_seo': titolo_seo,
        'sommario': sommario,
        'contenuto': contenuto,
        'tags': tags,
    }


def download_and_save_image(image_url: str, article_slug: str) -> str:
    """
    Scarica immagine esterna e la salva in /media/images/downloaded/.
    Restituisce il path relativo /media/... o l'URL originale in caso di errore.
    """
    if not image_url or not image_url.startswith('http'):
        return image_url

    try:
        filename = f"{article_slug[:80]}-original.webp"
        save_dir = Path(settings.MEDIA_ROOT) / 'images' / 'downloaded'
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename
        media_url = f"/media/images/downloaded/{filename}"

        if save_path.exists():
            return media_url

        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(image_url, timeout=10, headers=headers)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if 'image' not in content_type and 'octet' not in content_type:
                return image_url

            with Image.open(io.BytesIO(response.content)) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(save_path, 'WebP', quality=75, method=6)
            return media_url

    except Exception as e:
        logging.getLogger(__name__).warning(f"Download immagine fallito: {image_url} - {e}")

    return image_url


def download_article_image_in_background(article_id: int, image_url: str, article_slug: str) -> None:
    """Aggiorna foto con una copia locale solo per articoli gia' approvati."""
    if not image_url or not image_url.startswith('http'):
        return

    def _download():
        if not Articolo.objects.filter(pk=article_id, approvato=True).exists():
            logging.getLogger(__name__).info(
                "Download immagine rinviato fino all'approvazione per articolo %s",
                article_id,
            )
            return

        local_url = download_and_save_image(image_url, article_slug)
        if local_url != image_url:
            Articolo.objects.filter(pk=article_id, foto=image_url).update(foto=local_url)

    def _start_after_commit():
        thread = threading.Thread(target=_download, name=f"ArticleImageDownload-{article_id}", daemon=False)
        thread.start()

    transaction.on_commit(_start_after_commit)


class SiteConfig:
    """Configurazione per un sito specifico"""
    
    def __init__(self, 
                 name: str,
                 base_url: str,
                 scraper_type: str,
                 category: str = "Generale",
                 **kwargs):
        self.name = name
        self.base_url = base_url
        self.scraper_type = scraper_type  # 'html', 'wordpress_api', 'youtube_api'
        self.category = category
        
        # Configurazioni specifiche per tipo
        self.config = kwargs
        
        # Validazione base
        if scraper_type not in ['html', 'wordpress_api', 'youtube_api', 'graphql', 'email']:
            raise ValueError(f"Tipo scraper non supportato: {scraper_type}")


class BaseScraper(ABC):
    """Classe base per tutti gli scraper"""

    def __init__(self, config: SiteConfig, headers: Dict[str, str]):
        self.config = config
        self.headers = headers
        self.logger = get_monitor_logger(f"{config.name.lower().replace(' ', '_')}.scraper")
        # Timeout configurabile, default 15 secondi
        self.timeout = config.config.get('request_timeout', 15)
        # Modalità incognito: crea nuova sessione pulita ad ogni richiesta
        self.incognito_mode = config.config.get('incognito_mode', False)

    def _get_request(self, url: str, **kwargs) -> Any:
        """Esegue richiesta GET con supporto modalità incognito"""
        import requests

        if self.incognito_mode:
            # Modalità incognito: sessione pulita senza cookies persistenti
            session = requests.Session()
            session.cookies.clear()

            # Headers minimalisti (simili a navigazione incognito)
            incognito_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.9',
                'DNT': '1',
                'Upgrade-Insecure-Requests': '1',
            }

            # Merge con eventuali headers custom
            final_headers = {**incognito_headers, **kwargs.get('headers', {})}
            kwargs['headers'] = final_headers

            response = session.get(url, **kwargs)
            session.close()
            return response
        else:
            # Modalità normale
            if 'headers' not in kwargs:
                kwargs['headers'] = self.headers
            return requests.get(url, **kwargs)

    @abstractmethod
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli dal sito"""
        pass
    
    @abstractmethod
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Ottiene il contenuto completo di un articolo"""
        pass

    def mark_article_processed(self, article_data: Dict[str, Any]) -> None:
        """Hook opzionale per segnare una sorgente come processata dopo il salvataggio."""
        return None


class HTMLScraper(BaseScraper):
    """Scraper per siti HTML generici"""

    def _is_excluded_image(self, img_elem) -> bool:
        """Scarta immagini di layout, loghi, icone e placeholder."""
        classes = img_elem.get('class', '')
        if isinstance(classes, list):
            classes = ' '.join(classes)

        attrs = ' '.join([
            img_elem.get('src', ''),
            img_elem.get('data-src', ''),
            classes,
            img_elem.get('id', ''),
            img_elem.get('alt', ''),
        ]).lower()

        excluded_terms = [
            'logo', 'icon', 'banner', 'header', 'footer', 'avatar', 'social',
            'facebook', 'instagram', 'twitter', 'x.com', 'whatsapp', 'ads',
            'advertisement', 'pubblicita', 'placeholder', 'sprite', 'araldo',
            'scritta', 'san-michele'
        ]
        if any(term in attrs for term in excluded_terms):
            return True

        try:
            width = int(img_elem.get('width', '0') or 0)
            height = int(img_elem.get('height', '0') or 0)
            if width and height and (width < 120 or height < 80):
                return True
        except (ValueError, TypeError):
            pass

        return False

    def _extract_meta_image_from_soup(self, soup: BeautifulSoup, page_url: str) -> Optional[str]:
        """Estrae l'immagine dichiarata nei meta tag social/structured data."""
        meta_selectors = [
            'meta[property="og:image"]',
            'meta[property="og:image:secure_url"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image"]',
        ]
        for selector in meta_selectors:
            meta = soup.select_one(selector)
            image_url = meta.get('content') if meta else None
            if image_url:
                return urljoin(page_url, image_url.strip())

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or '')
            except (json.JSONDecodeError, TypeError):
                continue

            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                image_data = item.get('image')
                if isinstance(image_data, str):
                    return urljoin(page_url, image_data)
                if isinstance(image_data, list) and image_data:
                    first_image = image_data[0]
                    if isinstance(first_image, str):
                        return urljoin(page_url, first_image)
                    if isinstance(first_image, dict) and first_image.get('url'):
                        return urljoin(page_url, first_image['url'])
                if isinstance(image_data, dict) and image_data.get('url'):
                    return urljoin(page_url, image_data['url'])

        return None

    def _extract_best_article_image(self, soup: BeautifulSoup, page_url: str) -> Optional[str]:
        """Estrae l'immagine principale evitando navigazione e correlati."""
        meta_image = self._extract_meta_image_from_soup(soup, page_url)
        if meta_image:
            return meta_image

        scoped_selectors = [
            'article img',
            'main img',
            '.article-content img',
            '.entry-content img',
            '.post-content img',
            '.content img',
            '.news-body img',
        ]
        for selector in scoped_selectors:
            for img_elem in soup.select(selector):
                if self._is_excluded_image(img_elem):
                    continue
                image_url = self._extract_image_from_html_elem(img_elem)
                if image_url:
                    return urljoin(page_url, image_url)

        return None
    
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli tramite HTML con supporto RSS discovery e JSON parsing"""
        articles = []

        # 1. Se la pagina usa JSON embedded, parsalo direttamente
        if self.config.config.get('parse_json', False):
            json_articles = self._parse_json_from_page()
            articles.extend(json_articles)
            return articles

        # 2. Se RSS non è disabilitato, prova RSS discovery prima
        if not self.config.config.get('disable_rss', False):
            rss_articles = self._discover_articles_from_rss()
            articles.extend(rss_articles)

        # 3. Poi scrapa pagine HTML normalmente
        urls_to_scrape = [self.config.config.get('news_url', self.config.base_url)]
        
        # Aggiungi URLs aggiuntivi se configurati (escludendo RSS feed)
        additional_urls = self.config.config.get('additional_urls', [])
        for url in additional_urls:
            if not url.endswith('/feed/') and not url.endswith('.rss'):
                urls_to_scrape.append(url)
        
        for url in urls_to_scrape:
            try:
                self.logger.info(f"Scraping HTML: {url}")

                response = self._get_request(url, timeout=self.timeout)
                response.raise_for_status()

                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Usa selettori configurabili
                selectors = self.config.config.get('selectors', [
                    '.news-item', '.article-preview', '.post', 'article',
                    '.news-card', '.content-item', 'div[class*="news"]'
                ])
                
                page_articles = self._extract_articles_from_page(soup, selectors, url)
                articles.extend(page_articles)
                
            except Exception as e:
                self.logger.error(f"Errore nello scraping di {url}: {e}")
                continue
        
        # Rimuovi duplicati basati sull'URL, dando priorità agli articoli con immagini
        url_to_article = {}
        for article in articles:
            url = article['url']
            if url not in url_to_article:
                url_to_article[url] = article
            else:
                # Se l'articolo esistente non ha immagine ma questo sì, sostituiscilo
                existing = url_to_article[url]
                if not existing.get('image_url') and article.get('image_url'):
                    url_to_article[url] = article
        
        unique_articles = list(url_to_article.values())
        
        self.logger.info(f"Totale articoli unici trovati: {len(unique_articles)}")
        return unique_articles
    
    def _discover_articles_from_rss(self) -> List[Dict[str, Any]]:
        """Scopre articoli dal feed RSS e scrapa il loro contenuto"""
        articles = []
        
        # Usa RSS URL personalizzato se configurato, altrimenti usa quello di default
        rss_url = self.config.config.get('rss_url')
        if not rss_url:
            rss_url = f"{self.config.base_url.rstrip('/')}/feed/"
        
        try:
            self.logger.info(f"Discovering articles from RSS: {rss_url}")

            response = self._get_request(rss_url, timeout=self.timeout)
            response.raise_for_status()

            # Parse RSS feed con gestione encoding migliorata
            import xml.etree.ElementTree as ET

            # Prova prima con encoding UTF-8, poi con ISO-8859-1 se fallisce
            try:
                # Decodifica esplicita in UTF-8
                content_text = response.content.decode('utf-8', errors='replace')
                root = ET.fromstring(content_text.encode('utf-8'))
            except (ET.ParseError, UnicodeDecodeError):
                try:
                    # Fallback: prova ISO-8859-1 (Latin-1)
                    content_text = response.content.decode('iso-8859-1', errors='replace')
                    root = ET.fromstring(content_text.encode('utf-8'))
                except ET.ParseError:
                    # Ultimo tentativo: usa response.text che requests gestisce automaticamente
                    root = ET.fromstring(response.text.encode('utf-8'))
            
            rss_items = root.findall('.//item')
            self.logger.info(f"Found {len(rss_items)} items in RSS feed")
            
            for item in rss_items:
                try:
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    description_elem = item.find('description')
                    pub_date_elem = item.find('pubDate')
                    
                    if title_elem is not None and link_elem is not None:
                        article_url = link_elem.text
                        title = title_elem.text
                        description = description_elem.text if description_elem is not None else ''
                        pub_date = pub_date_elem.text if pub_date_elem is not None else ''

                        # Applica filtro URL se configurato (prima di scaricare contenuto)
                        url_filter_keywords = self.config.config.get('url_filter_keywords', [])
                        if url_filter_keywords:
                            url_and_title = f"{article_url} {title}".lower()
                            has_url_keyword = any(keyword.lower() in url_and_title for keyword in url_filter_keywords)
                            if not has_url_keyword:
                                self.logger.debug(f"Skipping article (URL filter): {title[:50]}...")
                                continue

                        # Scrapa il contenuto della pagina specifica PRIMA del filtro
                        full_content = self.get_full_content(article_url)
                        
                        # Applica filtro per parole chiave su TUTTO il contenuto dell'articolo
                        filter_keywords = self.config.config.get('content_filter_keywords', [])
                        if filter_keywords:
                            content_to_check = f"{title} {description} {full_content or ''}".lower()
                            has_keyword = any(keyword.lower() in content_to_check for keyword in filter_keywords)
                            if not has_keyword:
                                self.logger.debug(f"Skipping article (no keywords in full content): {title[:50]}...")
                                continue
                        
                        # Prova a estrarre immagine dal contenuto RSS
                        # NOTA: get_full_content restituisce solo testo, non HTML con immagini
                        # Quindi dobbiamo scaricare la pagina HTML completa
                        image_url = None
                        try:
                            from bs4 import BeautifulSoup
                            article_response = self._get_request(article_url, timeout=self.timeout)
                            article_soup = BeautifulSoup(article_response.content, 'html.parser')
                            image_url = self._extract_best_article_image(article_soup, article_url)

                            # Prima cerca immagini con caratteristiche di articolo (es. Questura con ?art=)
                            all_imgs = article_soup.find_all('img')
                            img_elem = None

                            # Priorità 1: Immagini con parametro art= (tipico delle Questure) o in /statics/
                            if not image_url:
                                for img in all_imgs:
                                    src = img.get('src', '')
                                    if ('art=' in src or '/statics/' in src) and not self._is_excluded_image(img):
                                        img_elem = img
                                        break

                            # Priorità 2: Prima immagine che non sia icona/logo/banner
                            if not image_url and not img_elem:
                                for img in all_imgs:
                                    if not self._is_excluded_image(img):
                                        img_elem = img
                                        break

                            if not image_url and img_elem:
                                image_url = self._extract_image_from_html_elem(img_elem)
                        except Exception as e:
                            self.logger.debug(f"Errore estrazione immagine RSS: {e}")
                        
                        article = {
                            'title': title,
                            'url': article_url,
                            'preview': description or title,
                            'full_content': full_content,
                            'image_url': image_url,
                            'pub_date': pub_date,
                            'source': 'RSS Feed'
                        }
                        articles.append(article)
                        
                except Exception as e:
                    self.logger.debug(f"Error processing RSS item: {e}")
            
        except Exception as e:
            self.logger.warning(f"RSS discovery failed: {e}")

        return articles

    def _parse_json_from_page(self) -> List[Dict[str, Any]]:
        """Estrae articoli da JSON embedded nella pagina"""
        import json

        articles = []
        url = self.config.base_url

        try:
            self.logger.info(f"Parsing JSON from page: {url}")

            response = self._get_request(url, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Trova lo script tag con il JSON
            selectors = self.config.config.get('selectors', ['script#__NEXT_DATA__'])
            script_tag = None

            for selector in selectors:
                script_tag = soup.select_one(selector)
                if script_tag:
                    break

            if not script_tag:
                self.logger.warning(f"Script tag non trovato con selettori: {selectors}")
                return articles

            # Parse JSON
            json_data = json.loads(script_tag.string)

            # Naviga nel JSON usando il path configurato
            json_path = self.config.config.get('json_path', [])
            data = json_data
            for key in json_path:
                data = data.get(key, {})

            if not isinstance(data, list):
                self.logger.warning(f"JSON path non porta a una lista: {json_path}")
                return articles

            # Mappa i campi configurati
            article_fields = self.config.config.get('article_fields', {})

            for item in data:
                try:
                    image_url = item.get(article_fields.get('image_url', 'image'), '')

                    # Rimuovi parametri query se configurato (problema Gazzetta di Modena)
                    if self.config.config.get('strip_image_params', False) and image_url and '?' in image_url:
                        image_url = image_url.split('?')[0]

                    article = {
                        'title': item.get(article_fields.get('title', 'title'), ''),
                        'url': item.get(article_fields.get('url', 'link'), ''),
                        'preview': item.get(article_fields.get('preview', 'text'), ''),
                        'image_url': image_url,
                        'full_content': None,
                        '_fetch_image_from_article': self.config.config.get('fetch_image_from_article', False)  # Flag per fetch successivo
                    }

                    # Valida che l'articolo abbia almeno titolo e URL
                    if article['title'] and article['url']:
                        articles.append(article)

                except Exception as e:
                    self.logger.debug(f"Errore parsing item JSON: {e}")

            self.logger.info(f"Trovati {len(articles)} articoli da JSON")

        except Exception as e:
            self.logger.error(f"Errore nel parsing JSON: {e}")

        return articles

    def _extract_articles_from_page(self, soup: BeautifulSoup, selectors: List[str], page_url: str) -> List[Dict[str, Any]]:
        """Estrae articoli da una singola pagina"""
        articles = []
        news_items = []
        
        # Prova tutti i selettori per trovare elementi
        for selector in selectors:
            items = soup.select(selector)
            if items:
                self.logger.debug(f"Selettore '{selector}' ha trovato {len(items)} elementi")
                news_items.extend(items)
        
        # Rimuovi duplicati mantenendo l'ordine
        seen_items = set()
        unique_items = []
        for item in news_items:
            item_id = id(item)  # Usa l'ID dell'oggetto per identificare duplicati
            if item_id not in seen_items:
                seen_items.add(item_id)
                unique_items.append(item)
        
        news_items = unique_items[:50]  # Limita a 50 elementi per pagina
        
        # Fallback generico se non trova elementi specifici
        if not news_items:
            self.logger.debug(f"Nessun elemento trovato con selettori, usando fallback per {page_url}")
            news_items = soup.select('div, article, section')
            filtered_items = []
            for item in news_items:
                links = item.find_all('a', href=True)
                text = item.get_text(strip=True)
                if links and len(text) > 50:
                    filtered_items.append(item)
            news_items = filtered_items[:20]
        
        # Estrai dati da ogni elemento
        for item in news_items:
            try:
                article_data = self._extract_article_from_html(item, page_url)
                if article_data:
                    articles.append(article_data)
            except Exception as e:
                self.logger.debug(f"Errore nell'estrazione articolo HTML: {e}")
        
        return articles
    
    def _extract_article_from_html(self, item, page_url: str = None) -> Optional[Dict[str, Any]]:
        """Estrae dati articolo da elemento HTML"""
        
        # Se l'elemento stesso è un link
        if item.name == 'a' and item.get('href'):
            link_elem = item
        else:
            # Caso normale: cerca link dentro l'elemento
            # Supporto per link_selector configurabile (risolve casi come Diocesi)
            link_selector = self.config.config.get("link_selector")
            if link_selector:
                link_elem = item.select_one(link_selector)
                self.logger.debug(f"Uso link_selector personalizzato: '{link_selector}' -> trovato: {link_elem is not None}")
            else:
                link_elem = item.find('a', href=True)

        if not link_elem:
            self.logger.debug(f"Nessun link trovato in elemento: {item.name if hasattr(item, 'name') else item}")
            return None
            
        article_url = link_elem.get('href')
        if article_url.startswith('http'):
            # URL assoluta, usa così com'è
            pass
        else:
            # URL relativa (/, ../, ./), usa urljoin per risolverla
            article_url = urljoin(self.config.base_url, article_url)

        # Applica filtri exclude_patterns configurabili da database
        exclude_patterns = self.config.config.get('exclude_patterns', [])
        if exclude_patterns:
            for pattern in exclude_patterns:
                if pattern in article_url:
                    self.logger.debug(f"URL escluso da pattern '{pattern}': {article_url}")
                    return None

        # Titolo
        title = link_elem.get_text(strip=True) or link_elem.get('title')
        if not title:
            title_selectors = ['h1', 'h2', 'h3', 'h4', '.title', '.headline']
            for selector in title_selectors:
                title_elem = item.select_one(selector)
                if title_elem and title_elem.get_text(strip=True):
                    title = title_elem.get_text(strip=True)
                    break
        
        if not title:
            title = f"{self.config.name} Notizie"
        
        title = title[:200]
        
        # Contenuto preview
        content_preview = item.get_text(strip=True)[:500]
        
        # Per elementi <a> semplici (caso Comune), crea preview artificiale
        if item.name == 'a' and len(content_preview) < 30:
            content_preview = f"Notizia dal {self.config.name}: {title}. Clicca per leggere il contenuto completo."

        if len(content_preview) < 30:
            self.logger.debug(f"Articolo scartato: preview troppo corta ({len(content_preview)} < 30): '{content_preview[:50]}'")
            return None
        
        # Applica filtro keywords anche per HTML scraping (controllo su contenuto completo)
        filter_keywords = self.config.config.get('content_filter_keywords', [])
        if filter_keywords:
            # Scarica contenuto completo per il filtro
            full_content = self.get_full_content(article_url)
            content_to_check = f"{title} {content_preview} {full_content or ''}".lower()
            has_keyword = any(keyword.lower() in content_to_check for keyword in filter_keywords)
            if not has_keyword:
                self.logger.debug(f"Articolo scartato: nessuna keyword trovata. Keywords: {filter_keywords}, URL: {article_url}")
                return None
        
        # Immagine
        image_url_suffix = self.config.config.get('image_url_suffix')
        if image_url_suffix:
            # Costruisci URL immagine direttamente dall'URL articolo (es. Plone: /image_news)
            image_url = article_url.rstrip('/') + '/' + image_url_suffix.lstrip('/')
        else:
            image_url = self._extract_image_from_html(item)

        return {
            'title': title,
            'url': article_url,
            'preview': content_preview,
            'image_url': image_url,
            'full_content': None,  # Sarà caricato se necessario
            '_fetch_image_from_article': self.config.config.get('fetch_image_from_article', False)
        }
    
    def _extract_image_from_html(self, item) -> Optional[str]:
        """Estrae URL immagine da elemento HTML usando selettori personalizzati se configurati"""
        # Usa selettori immagine personalizzati se configurati
        image_selectors = self.config.config.get('image_selectors', ['img'])

        # Se item è un link, cerca anche nel parent (caso ModenaToday Eventi)
        elements_to_search = [item]
        if item.name == 'a' and item.parent:
            elements_to_search.append(item.parent)

        for search_elem in elements_to_search:
            for selector in image_selectors:
                img_elem = search_elem.select_one(selector)
                if img_elem:
                    image_url = self._extract_image_from_html_elem(img_elem)
                    if image_url:
                        return image_url

        # Fallback al metodo standard
        img_elem = item.find('img')
        if not img_elem and item.parent:
            img_elem = item.parent.find('img')

        if not img_elem:
            return None
        return self._extract_image_from_html_elem(img_elem)
    
    def _extract_image_from_html_elem(self, img_elem) -> Optional[str]:
        """Estrae URL immagine da un elemento img specifico"""
        # Prova prima attributi data-* per lazy loading
        img_src = (img_elem.get('data-src') or
                  img_elem.get('data-lazy-src') or
                  img_elem.get('src'))

        # Se src è base64 o vuoto, prova srcset/ta-srcset
        if not img_src or img_src.startswith('data:'):
            # Controlla ta-srcset (usato da notiziecarpi.it) e srcset standard
            srcset = img_elem.get('ta-srcset') or img_elem.get('srcset') or img_elem.get('data-srcset')
            if srcset:
                # Formato: "url1 width1, url2 width2, ..."
                # Prendiamo l'ultima (immagine più grande), filtrando parti vuote
                parts = [p.strip() for p in srcset.split(',') if p.strip()]
                if parts:
                    # Prendi l'URL dalla parte (es. "url 300w" -> "url")
                    last_part = parts[-1]
                    img_src = last_part.split()[0] if ' ' in last_part else last_part

            if not img_src or img_src.startswith('data:'):
                return None

        # Filtra immagini piccole
        try:
            width = int(img_elem.get('width', '0'))
            height = int(img_elem.get('height', '0'))
            if width > 0 and height > 0 and (width < 80 or height < 60):
                return None
        except (ValueError, TypeError):
            pass

        # Filtra loghi e icone
        if any(term in img_src.lower() for term in ['logo', 'icon', 'avatar', 'social', 'placeholder']):
            return None

        # Rimuovi parametri query se configurato (problema Gazzetta di Modena)
        if self.config.config.get('strip_image_params', False) and '?' in img_src:
            img_src = img_src.split('?')[0]

        # Fix per URL con spazi (problema Voce di Carpi)
        if ' ' in img_src:
            from urllib.parse import quote
            # Codifica solo la parte del path, mantenendo lo schema e host
            if img_src.startswith('http'):
                parts = img_src.split('/', 3)  # ['http:', '', 'domain.com', 'path/with spaces.jpg']
                if len(parts) > 3:
                    # Codifica solo il path mantenendo il resto
                    encoded_path = quote(parts[3], safe='/')
                    img_src = f"{parts[0]}//{parts[2]}/{encoded_path}"
            else:
                img_src = quote(img_src, safe='/:?#[]@!$&\'()*+,;=')

        # Gestione URL protocol-relative (//domain.com/path)
        if img_src.startswith('//'):
            return 'https:' + img_src
        elif img_src.startswith('/'):
            return urljoin(self.config.base_url, img_src)
        elif img_src.startswith('http'):
            return img_src

        return None
    
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Scarica contenuto completo da pagina HTML"""
        try:
            self.logger.debug(f"[DEBUG get_full_content] Downloading: {article_url}")
            response = self._get_request(article_url, timeout=self.timeout)
            response.raise_for_status()

            # Log encoding info
            self.logger.debug(f"[DEBUG get_full_content] Response encoding: {response.encoding}, Content-Type: {response.headers.get('Content-Type')}")

            soup = BeautifulSoup(response.content, 'html.parser')

            # Rimuovi elementi non necessari
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'menu']):
                tag.decompose()

            # Cerca contenuto principale
            content_selectors = self.config.config.get('content_selectors', [
                '.article-content', '.post-content', '.content', '.entry-content',
                'main', 'article', '.news-body'
            ])

            content = ""
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    content = content_elem.get_text(strip=True)
                    self.logger.debug(f"[DEBUG get_full_content] Found content with selector '{selector}': {len(content)} chars, preview: {content[:200]}")
                    break

            # Fallback
            if not content or len(content) < 100:
                body = soup.find('body')
                if body:
                    content = body.get_text(strip=True)
                    self.logger.debug(f"[DEBUG get_full_content] Fallback to body: {len(content)} chars")

            return content if len(content) > 100 else None

        except Exception as e:
            self.logger.error(f"Errore nel recuperare contenuto da {article_url}: {e}")
            return None


class WordPressAPIScraper(BaseScraper):
    """Scraper per siti WordPress tramite REST API"""
    
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli tramite WordPress REST API"""
        try:
            # Check if custom API endpoint is specified
            custom_endpoint = self.config.config.get('custom_api_endpoint')
            if custom_endpoint:
                return self._scrape_custom_api(custom_endpoint)
            else:
                return self._scrape_standard_wp_api()
            
        except Exception as e:
            self.logger.error(f"Errore nello scraping WordPress API: {e}")
            return []
    
    def _scrape_standard_wp_api(self) -> List[Dict[str, Any]]:
        """Scrape using standard WordPress API"""
        api_url = f"{self.config.base_url}wp-json/wp/v2/posts"
        per_page = self.config.config.get('per_page', 10)
        
        self.logger.info(f"Scraping standard WordPress API: {api_url}")

        api_headers = {**self.headers, 'Accept': 'application/json'}
        response = self._get_request(f"{api_url}?per_page={per_page}",
                              headers=api_headers, timeout=15)
        response.raise_for_status()
        
        posts = response.json()
        articles = []
        
        for post in posts:
            try:
                article_data = self._extract_article_from_wp_post(post, api_headers)
                if article_data:
                    articles.append(article_data)
            except Exception as e:
                self.logger.warning(f"Errore nell'estrazione post WP {post.get('id')}: {e}")
        
        return articles
    
    def _scrape_custom_api(self, endpoint: str) -> List[Dict[str, Any]]:
        """Scrape using custom API endpoint (e.g., Comune di Carpi)"""
        api_url = f"{self.config.base_url.rstrip('/')}{endpoint}"
        
        self.logger.info(f"Scraping custom API: {api_url}")

        api_headers = {**self.headers, 'Accept': 'application/json'}
        response = self._get_request(api_url, headers=api_headers, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        articles = []
        
        # Handle different response formats
        if isinstance(data, dict) and 'risultati' in data:
            # Comune di Carpi format
            items = data['risultati']
        elif isinstance(data, list):
            items = data
        else:
            self.logger.warning(f"Formato risposta API non riconosciuto: {type(data)}")
            return []
        
        exclude_titles = self.config.config.get('exclude_titles', [])
        
        for item in items:
            try:
                article_data = self._extract_article_from_custom_item(item)
                if article_data and self._should_include_article(article_data, exclude_titles):
                    articles.append(article_data)
            except Exception as e:
                self.logger.warning(f"Errore nell'estrazione item custom: {e}")
        
        return articles
    
    def _should_include_article(self, article_data: Dict[str, Any], exclude_titles: List[str]) -> bool:
        """Check if article should be included based on filters"""
        title_lower = article_data.get('title', '').lower()
        
        # Skip articles with excluded titles
        for exclude_term in exclude_titles:
            if exclude_term.lower() in title_lower:
                return False
        
        # Skip articles that are too old (only static pages)
        date_str = article_data.get('date', '')
        if date_str and not any(year in date_str for year in ['2023', '2024', '2025']):
            return False
        
        # Must have some content (more lenient for Comune di Carpi)
        preview = article_data.get('preview', '')
        title = article_data.get('title', '')
        if len(preview.strip()) < 20 and len(title.strip()) < 10:
            return False
        
        return True
    
    def _extract_article_from_custom_item(self, item: Dict) -> Optional[Dict[str, Any]]:
        """Extract article data from custom API item (Comune di Carpi format)"""
        title = item.get('titolo', 'Senza titolo')
        if not title or title == 'Senza titolo':
            return None
        
        article_url = item.get('link', '')
        if not article_url:
            return None
        
        # Use description as preview, fallback to title + context
        content_preview = item.get('descrizione', '').strip()
        if not content_preview or len(content_preview) < 20:
            # Create informative preview from available data
            entity_type = item.get('nomeEntita', 'contenuto')
            if entity_type == 'page':
                content_preview = f"Pagina informativa del Comune di Carpi: {title}"
            else:
                content_preview = f"Contenuto dal sito del Comune di Carpi: {title}"
        
        # Clean HTML if present
        if '<' in content_preview and '>' in content_preview:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content_preview, 'html.parser')
            content_preview = soup.get_text(strip=True)
        
        # Get image if available
        image_url = item.get('immagineUrl')
        if image_url and (image_url == 'False' or image_url == False):
            image_url = None
        
        return {
            'title': title[:200],
            'url': article_url,
            'preview': content_preview[:500],
            'image_url': image_url,
            'full_content': None,  # Will be loaded later if needed
            'date': item.get('data', ''),
            'entity_type': item.get('nomeEntita', 'unknown')
        }
    
    def _extract_article_from_wp_post(self, post: Dict, api_headers: Dict) -> Optional[Dict[str, Any]]:
        """Estrae dati articolo da post WordPress"""
        title = post['title']['rendered'].strip()[:200]
        article_url = post['link']
        content_preview = post.get('excerpt', {}).get('rendered', '')
        full_content = post.get('content', {}).get('rendered', '')
        
        if not title:
            title = f"{self.config.name} #{post['id']}"
        
        # Pulisci preview HTML
        if content_preview:
            preview_soup = BeautifulSoup(content_preview, 'html.parser')
            content_preview = preview_soup.get_text(strip=True)
        
        if not content_preview and full_content:
            content_soup = BeautifulSoup(full_content, 'html.parser')
            content_preview = content_soup.get_text(strip=True)[:500]
        
        if len(content_preview) < 30:
            return None
        
        # Cerca immagine featured media
        image_url = None
        featured_media_id = post.get('featured_media', 0)
        if featured_media_id > 0:
            try:
                media_response = self._get_request(
                    f"{self.config.base_url}wp-json/wp/v2/media/{featured_media_id}",
                    headers=api_headers, timeout=10
                )
                if media_response.status_code == 200:
                    media_data = media_response.json()
                    image_url = media_data.get('source_url')
            except Exception:
                pass
        
        # Se no featured image, cerca nel contenuto
        if not image_url and full_content:
            image_url = self._extract_image_from_wp_content(full_content)
        
        # Download image locally only when this monitor auto-approves the article.
        final_image_url = image_url
        if (
            image_url
            and self.config.config.get('download_images_locally', False)
            and self.config.config.get('auto_approve', False)
        ):
            try:
                # Use article ID as unique identifier for download
                article_id = str(post.get('id', ''))
                downloaded_url = self.download_and_save_image(image_url, article_id, force_download=True)
                if downloaded_url:
                    final_image_url = downloaded_url
                    self.logger.info(f"Downloaded image locally: {downloaded_url}")
            except Exception as e:
                self.logger.warning(f"Failed to download image {image_url}: {e}")

        return {
            'title': title,
            'url': article_url,
            'preview': content_preview[:500],
            'image_url': final_image_url,
            'full_content': full_content
        }
    
    def _extract_image_from_wp_content(self, content: str) -> Optional[str]:
        """Estrae immagine dal contenuto WordPress"""
        soup = BeautifulSoup(content, 'html.parser')
        images = soup.find_all('img')
        
        for img in images:
            img_src = (img.get('src') or img.get('data-src') or img.get('data-lazy-src'))
            
            if (img_src and
                not img_src.startswith('data:') and
                not any(term in img_src.lower() for term in ['logo', 'icon', 'avatar', 'social']) and
                'uploads' in img_src):

                if img_src.startswith('//'):
                    return 'https:' + img_src
                elif img_src.startswith('/'):
                    return urljoin(self.config.base_url, img_src)
                elif img_src.startswith('http'):
                    return img_src
        
        return None
    
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Per WordPress API il contenuto è già disponibile"""
        return None  # Il contenuto completo è già nell'articolo


class YouTubeAPIScraper(BaseScraper):
    """Scraper per playlist YouTube"""
    
    def __init__(self, config: SiteConfig, headers: Dict[str, str]):
        super().__init__(config, headers)
        self.api_key = config.config.get('api_key')
        self.playlist_id = config.config.get('playlist_id')
        self.fallback_video_ids = config.config.get('fallback_video_ids', [])
        self.excluded_video_ids = set(config.config.get('excluded_video_ids', []))
        
        # Se non abbiamo API key/playlist ma abbiamo video IDs di fallback, va bene
        if not self.api_key or not self.playlist_id:
            if not self.fallback_video_ids:
                raise ValueError("YouTubeAPIScraper richiede (api_key + playlist_id) o fallback_video_ids")
            else:
                self.logger.warning("YouTube API non configurata, usando modalità fallback con video IDs")
    
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape video da playlist YouTube o usa fallback IDs"""
        articles = []

        # Controlla prima i video in attesa di retry
        pending_videos = self._check_pending_retries()
        if pending_videos:
            self.logger.info(f"Processando {len(pending_videos)} video in retry")
            for video_id in pending_videos:
                if self._is_video_excluded(video_id):
                    self.logger.info(f"Video YouTube escluso dal retry: {video_id}")
                    continue
                try:
                    article_data = {
                        'title': f"Consiglio Comunale Carpi - Video {video_id} (Retry)",
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'preview': "Trascrizione del consiglio comunale di Carpi (processamento differito)",
                        'image_url': f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                        'video_id': video_id,
                        'published_at': None
                    }

                    # Prova di nuovo il transcript
                    transcript = self.get_video_transcript(video_id)
                    if transcript:
                        article_data['full_content'] = transcript
                        articles.append(article_data)
                        self.logger.info(f"Retry riuscito per video {video_id}")
                    else:
                        self.logger.warning(f"Retry fallito per video {video_id}")

                except Exception as e:
                    self.logger.error(f"Errore nel retry video {video_id}: {e}")

        # Se abbiamo API key e playlist, usa YouTube API
        if self.api_key and self.playlist_id and not self.api_key.startswith("AIzaSyDummy"):
            new_articles = self._scrape_from_api()
            articles.extend(new_articles)
        else:
            # Altrimenti usa modalità fallback
            new_articles = self._scrape_from_fallback_ids()
            articles.extend(new_articles)

        return articles
    
    def _scrape_from_api(self) -> List[Dict[str, Any]]:
        """Scrape usando YouTube API (quando configurata)"""
        try:
            self.logger.info("Usando YouTube API per scraping")
            url = "https://www.googleapis.com/youtube/v3/playlistItems"
            params = {
                'part': 'snippet',
                'playlistId': self.playlist_id,
                'key': self.api_key,
                'maxResults': self.config.config.get('max_results', 10),
                'order': 'date'
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            articles = []
            for item in data.get('items', []):
                try:
                    video_id = item['snippet']['resourceId']['videoId']
                    if self._is_video_excluded(video_id):
                        self.logger.info(f"Video YouTube escluso dalla playlist: {video_id}")
                        continue

                    article_data = {
                        'title': item['snippet']['title'][:200],
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'preview': item['snippet']['description'][:500],
                        'image_url': item['snippet'].get('thumbnails', {}).get('medium', {}).get('url'),
                        'video_id': video_id,
                        'published_at': item['snippet']['publishedAt']
                    }
                    articles.append(article_data)
                except Exception as e:
                    self.logger.warning(f"Errore nell'estrazione video YouTube: {e}")
            
            return articles
            
        except Exception as e:
            self.logger.error(f"Errore nello scraping YouTube API: {e}")
            return []
    
    def _scrape_from_fallback_ids(self) -> List[Dict[str, Any]]:
        """Modalità fallback usando video IDs specifici"""
        try:
            self.logger.info(f"Usando modalità fallback con {len(self.fallback_video_ids)} video IDs")
            articles = []
            
            for video_id in self.fallback_video_ids:
                try:
                    if self._is_video_excluded(video_id):
                        self.logger.info(f"Video YouTube escluso dal fallback: {video_id}")
                        continue

                    article_data = {
                        'title': f"Consiglio Comunale Carpi - Video {video_id}",
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'preview': "Trascrizione del consiglio comunale di Carpi",
                        'image_url': f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                        'video_id': video_id,
                        'published_at': None  # Non disponibile in modalità fallback
                    }
                    articles.append(article_data)
                except Exception as e:
                    self.logger.warning(f"Errore nella creazione dati fallback per video {video_id}: {e}")
            
            return articles
            
        except Exception as e:
            self.logger.error(f"Errore in modalità fallback: {e}")
            return []
    
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Estrae trascrizione YouTube per il contenuto completo"""
        try:
            # Estrai video ID dall'URL
            video_id = article_url.split('v=')[1].split('&')[0]
            return self.get_video_transcript(video_id)
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione contenuto YouTube: {e}")
            return None

    def _is_video_excluded(self, video_id: str) -> bool:
        return bool(video_id and video_id in self.excluded_video_ids)
    
    def get_video_transcript(self, video_id: str) -> Optional[str]:
        """Estrae trascrizione da video YouTube con rate limiting e gestione dirette"""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

            # Applica rate limiting se configurato
            delay = self.config.config.get('transcript_delay', 0)
            if delay > 0:
                self.logger.info(f"Applicando pausa di {delay} secondi prima della richiesta transcript")
                time.sleep(delay)

            # Controlla prima se i sottotitoli sono disponibili
            self.logger.info(f"Verifica disponibilità sottotitoli per video {video_id}")

            try:
                # Crea istanza API e ottieni lista transcript disponibili
                api = YouTubeTranscriptApi()
                transcript_list = api.list(video_id)

                # Prova prima con transcript italiano manuale
                transcript = None
                try:
                    transcript = transcript_list.find_transcript(['it'])
                    self.logger.info(f"Trovato transcript italiano manuale per video {video_id}")
                except NoTranscriptFound:
                    # Se non c'è italiano manuale, prova con autogenerato
                    try:
                        self.logger.info(f"Transcript italiano manuale non disponibile, provo con autogenerato")
                        transcript = transcript_list.find_generated_transcript(['it'])
                        self.logger.info(f"Trovato transcript autogenerato italiano per video {video_id}")
                    except NoTranscriptFound:
                        # Se non c'è nemmeno autogenerato, prova con qualsiasi lingua
                        self.logger.info(f"Nessun transcript italiano, provo con altre lingue")
                        for t in transcript_list:
                            transcript = t
                            self.logger.info(f"Usando transcript in {t.language} (code: {t.language_code})")
                            break

                if not transcript:
                    raise NoTranscriptFound("Nessun transcript disponibile in alcuna lingua")

                # Estrai il testo dal transcript
                transcript_data = transcript.fetch()
                # Gli oggetti possono essere dict o oggetti con attributi
                text = " ".join([
                    item['text'] if isinstance(item, dict) else item.text
                    for item in transcript_data
                ])
                self.logger.info(f"Transcript estratto: {len(text)} caratteri")
                return text

            except TranscriptsDisabled:
                self.logger.info(f"Sottotitoli disabilitati per video {video_id}")
                # Controlla se è una diretta
                if self._is_live_stream(video_id):
                    self.logger.info(f"Video {video_id} è una diretta - sarà riprovato più tardi")
                    self._schedule_retry(video_id)
                return None

            except NoTranscriptFound:
                self.logger.info(f"Nessun transcript disponibile per video {video_id}")
                # Controlla se è una diretta
                if self._is_live_stream(video_id):
                    self.logger.info(f"Video {video_id} è una diretta - sarà riprovato più tardi")
                    self._schedule_retry(video_id)
                return None

        except (TranscriptsDisabled, NoTranscriptFound) as e:
            self.logger.error(f"Transcript non disponibile per video {video_id}: {e}")
            return None

        except Exception as e:
            self.logger.error(f"Errore nell'estrazione transcript per {video_id}: {e}")
            return None

    def _is_live_stream(self, video_id: str) -> bool:
        """Controlla se un video è una diretta in corso"""
        try:
            import requests
            # Usa YouTube oEmbed API per ottenere info base
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(oembed_url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                title = data.get('title', '').lower()
                # Indica diretta se nel titolo c'è "live", "diretta", "streaming"
                return any(keyword in title for keyword in ['live', 'diretta', 'streaming', 'in corso'])

            return False
        except Exception:
            # Se non riusciamo a verificare, assumiamo che sia una diretta
            return True

    def _schedule_retry(self, video_id: str):
        """Programma un retry per il video"""
        try:
            retry_delay = self.config.config.get('live_stream_retry_delay', 3600)  # 1 ora default
            retry_file = f"youtube_retry_{video_id}.txt"
            retry_path = os.path.join(tempfile.gettempdir(), retry_file)

            # Salva timestamp per il retry
            retry_time = time.time() + retry_delay
            with open(retry_path, 'w') as f:
                f.write(str(retry_time))

            self.logger.info(f"Scheduled retry for video {video_id} in {retry_delay} seconds")

        except Exception as e:
            self.logger.error(f"Errore scheduling retry per {video_id}: {e}")

    def _check_pending_retries(self) -> List[str]:
        """Controlla se ci sono video da riprovare"""
        try:
            import glob
            retry_files = glob.glob(os.path.join(tempfile.gettempdir(), "youtube_retry_*.txt"))
            ready_videos = []

            current_time = time.time()

            for retry_file in retry_files:
                try:
                    with open(retry_file, 'r') as f:
                        retry_time = float(f.read().strip())

                    if current_time >= retry_time:
                        # È ora di riprovare
                        video_id = os.path.basename(retry_file).replace('youtube_retry_', '').replace('.txt', '')
                        ready_videos.append(video_id)
                        os.unlink(retry_file)  # Rimuovi il file di retry

                except Exception as e:
                    # File corrotto, rimuovilo
                    try:
                        os.unlink(retry_file)
                    except:
                        pass

            return ready_videos

        except Exception as e:
            self.logger.error(f"Errore checking pending retries: {e}")
            return []


class GraphQLScraper(BaseScraper):
    """Scraper per API GraphQL AI4SmartCity del Comune di Carpi"""
    
    def __init__(self, config: SiteConfig, headers: Dict[str, str]):
        super().__init__(config, headers)
        self.graphql_endpoint = config.config.get('graphql_endpoint')
        self.fallback_to_wordpress = config.config.get('fallback_to_wordpress', True)
        self.wordpress_config = config.config.get('wordpress_config', {})
        
        if not self.graphql_endpoint:
            raise ValueError("GraphQLScraper richiede graphql_endpoint nella configurazione")
        
        # Headers per GraphQL (inclusi headers autenticazione trovati dal browser)
        self.graphql_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Content-Type': 'application/json',
            'Content-Language': 'it',
            'Origin': 'https://www.comune.carpi.mo.it',
            'Referer': 'https://www.comune.carpi.mo.it/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-site',
            'URL-Referer': 'https://www.comune.carpi.mo.it/novita/',
            # Headers critici per autenticazione
            'X-API-Key': 'comune-carpi-mo-it',
            'X-Ref-Host': 'www.comune.carpi.mo.it'
        }

        # Sovrascrivi con header specifici dalla configurazione se presenti
        config_headers = config.config.get('graphql_headers', {})
        if config_headers:
            self.graphql_headers.update(config_headers)
    
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli da API GraphQL con fallback a WordPress"""
        
        # Prima prova GraphQL
        articles = self._scrape_from_graphql()
        
        # Se GraphQL non funziona o restituisce risultati vuoti, usa fallback
        if not articles and self.fallback_to_wordpress:
            self.logger.warning("GraphQL non ha restituito articoli, usando fallback WordPress API")
            return self._scrape_from_wordpress_fallback()
        
        return articles
    
    def _scrape_from_graphql(self) -> List[Dict[str, Any]]:
        """Scrape usando API GraphQL"""
        try:
            self.logger.info(f"Tentativo GraphQL su: {self.graphql_endpoint}")
            
            # Usa query personalizzata se fornita, altrimenti usa quella predefinita per notizie
            custom_query = self.config.config.get('graphql_query')
            
            if custom_query:
                # Query personalizzata dalla configurazione
                query = {
                    'operationName': self.config.config.get('graphql_operation_name', 'CustomQuery'),
                    'variables': self.config.config.get('graphql_variables', {}),
                    'query': custom_query
                }
            else:
                # Query predefinita per notizie (mantenuta per compatibilità)
                # Usa variables personalizzate se fornite, altrimenti usa i default
                default_variables = {'pageNumber': 1, 'pageSize': 12}
                custom_variables = self.config.config.get('graphql_variables', {})
                variables = {**default_variables, **custom_variables}

                query = {
                    'operationName': 'getNotizie',
                    'variables': variables,
                    'query': '''
                    query getNotizie($pageNumber: Int! = 1, $pageSize: Int! = 12) {
                        notizieQuery {
                            notizie {
                                listaPaginata(
                                    paginazione: {pageNumber: $pageNumber, pageSize: $pageSize}
                                    ordinamento: {rilevanza: DESC, data: DESC, _orderBy: ["rilevanza", "data"]}
                                ) {
                                    currentPage
                                    hasNextPage
                                    hasPreviousPage
                                    pageSize
                                    totalCount
                                    totalPages
                                    data {
                                        __typename
                                        uniqueId
                                        data
                                        slug
                                        inEvidenza
                                        rilevanza
                                        immagineUrl
                                        traduzioni {
                                            titolo
                                            descrizioneBreve
                                            testoCompleto
                                            codiceLingua
                                            __typename
                                        }
                                        tipologie {
                                            uniqueId
                                            traduzioni {
                                                nome
                                                __typename
                                            }
                                            __typename
                                        }
                                    }
                                    __typename
                                }
                                __typename
                            }
                            __typename
                        }
                    }
                    '''
                }
            
            response = requests.post(
                self.graphql_endpoint,
                json=query,
                headers=self.graphql_headers,
                timeout=15
            )
            
            self.logger.info(f"GraphQL response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if 'errors' in result:
                    self.logger.error(f"GraphQL errors: {result['errors']}")
                    return []
                
                if 'data' in result and result['data']:
                    try:
                        # Determina se stiamo usando query personalizzata o predefinita
                        if custom_query:
                            # Per query personalizzate, usa una logica più flessibile
                            articles = self._extract_articles_from_custom_graphql(result['data'])
                        else:
                            # Struttura predefinita: notizieQuery.notizie.listaPaginata.data
                            notizie_data = result['data']['notizieQuery']['notizie']['listaPaginata']['data']
                            total_count = result['data']['notizieQuery']['notizie']['listaPaginata']['totalCount']
                            self.logger.info(f"GraphQL trovate {len(notizie_data)} notizie su {total_count} totali")
                            
                            articles = []
                            for notizia in notizie_data:
                                article = self._extract_article_from_graphql(notizia)
                                if article:
                                    articles.append(article)
                        
                        return articles
                        
                    except KeyError as e:
                        self.logger.error(f"Struttura dati GraphQL inaspettata: {e}")
                        self.logger.debug(f"Struttura ricevuta: {result['data']}")
                        return []
            else:
                self.logger.error(f"GraphQL HTTP error: {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"Errore GraphQL: {e}")
            return []
    
    def _extract_articles_from_custom_graphql(self, data: Dict) -> List[Dict[str, Any]]:
        """Estrae articoli da query GraphQL personalizzata"""
        articles = []
        
        try:
            # Per eventi: eventiQuery.eventi.lista
            if 'eventiQuery' in data and 'eventi' in data['eventiQuery']:
                eventi_data = data['eventiQuery']['eventi']['lista']
                self.logger.info(f"GraphQL trovati {len(eventi_data)} eventi")
                
                for evento in eventi_data:
                    article = self._extract_event_from_graphql(evento)
                    if article:
                        articles.append(article)
            
            # Per altri tipi di query personalizzate, aggiungi qui...
            
            return articles
            
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione da query personalizzata: {e}")
            return []
    
    def _format_evento_datetime(self, raw) -> Optional[str]:
        """Converte un datetime evento della GraphQL all'ora locale italiana.

        La GraphQL restituisce datetime ISO SENZA timezone ma in UTC
        (es. '2026-07-02T19:00:00' per un evento delle 21:00 CEST): senza
        conversione l'orario passato all'AI risultava anticipato di 1-2 ore.
        """
        if not raw:
            return None
        try:
            from datetime import datetime as _dt, timezone as _tz
            from zoneinfo import ZoneInfo
            dt = _dt.fromisoformat(str(raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)  # naive = UTC dalla GraphQL
            local = dt.astimezone(ZoneInfo('Europe/Rome'))
            # Giorno della settimana calcolato in codice: gli LLM spesso sbagliano a dedurlo
            giorni = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
            giorno = giorni[local.weekday()].capitalize()
            return f"{giorno} {local.strftime('%d/%m/%Y')} alle ore {local.strftime('%H:%M')}"
        except Exception as e:
            self.logger.warning(f"Formattazione data evento fallita per '{raw}': {e}")
            return str(raw)

    def _extract_event_from_graphql(self, evento: Dict) -> Optional[Dict[str, Any]]:
        """Estrae dati evento da risposta GraphQL"""
        try:
            # Estrai traduzioni in italiano
            traduzioni = evento.get('traduzioni', [])
            traduzione_it = None
            
            for trad in traduzioni:
                if trad.get('codiceLingua') == 'it':
                    traduzione_it = trad
                    break
            
            if not traduzione_it:
                self.logger.warning(f"Nessuna traduzione italiana trovata per evento {evento.get('uniqueId')}")
                return None
            
            title = traduzione_it.get('titolo', '').strip()
            if not title:
                return None
            
            # Usa descrizioneEstesa come contenuto principale
            descrizione_estesa = traduzione_it.get('descrizioneEstesa', '').strip()
            descrizione_breve = traduzione_it.get('descrizioneBreve', '').strip()
            
            # Combina le informazioni dell'evento
            content_parts = []
            if descrizione_breve:
                content_parts.append(descrizione_breve)
            if descrizione_estesa:
                content_parts.append(descrizione_estesa)
            
            # Aggiungi informazioni pratiche (orari convertiti in ora locale italiana)
            inizio_fmt = self._format_evento_datetime(evento.get('dataOraInizio'))
            if inizio_fmt:
                content_parts.append(f"Data e ora inizio: {inizio_fmt}")
            fine_fmt = self._format_evento_datetime(evento.get('dataOraFine'))
            if fine_fmt:
                content_parts.append(f"Data e ora fine: {fine_fmt}")
            if evento.get('costo'):
                content_parts.append(f"Costo: {evento['costo']}")
            
            # Aggiungi luoghi
            luoghi = evento.get('luoghi', [])
            if luoghi:
                luoghi_nomi = [luogo.get('nome', '') for luogo in luoghi if luogo.get('nome')]
                if luoghi_nomi:
                    content_parts.append(f"Luogo: {', '.join(luoghi_nomi)}")
            
            full_content = '\n\n'.join(content_parts)
            
            # Costruisci URL evento
            article_url = f"{self.config.base_url}vivere-il-comune/eventi/{evento.get('uniqueId', '')}"
            
            # Scarica e salva immagine localmente se è dall'API Comune Carpi
            event_image_url = evento.get('immagineUrl')
            if (
                event_image_url
                and 'api.wp.ai4smartcity.ai' in event_image_url
                and self.config.config.get('auto_approve', False)
            ):
                event_image_url = self.download_and_save_image(event_image_url, evento.get('uniqueId', ''))
            
            return {
                'title': title,
                'url': article_url,
                'preview': descrizione_breve or descrizione_estesa[:500],
                'image_url': event_image_url,
                'full_content': full_content,
                'event_id': evento.get('uniqueId'),
                'event_start': evento.get('dataOraInizio'),
                'event_end': evento.get('dataOraFine')
            }
            
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione evento GraphQL: {e}")
            return None
    
    def _extract_article_from_graphql(self, notizia: Dict) -> Optional[Dict[str, Any]]:
        """Estrae dati articolo da risposta GraphQL"""
        try:
            # Dati base dalla nuova struttura
            unique_id = notizia.get('uniqueId')
            data_pubblicazione = notizia.get('data')
            immagine_url = notizia.get('immagineUrl')
            slug = notizia.get('slug', '')
            in_evidenza = notizia.get('inEvidenza', False)
            
            # Traduzioni (assumiamo italiano come prima lingua)
            traduzioni = notizia.get('traduzioni', [])
            if not traduzioni:
                return None
            
            # Trova traduzione italiana o prendi la prima
            traduzione = None
            for trad in traduzioni:
                if trad.get('codiceLingua') == 'it':
                    traduzione = trad
                    break
            if not traduzione:
                traduzione = traduzioni[0]  # Fallback alla prima traduzione
            
            titolo = traduzione.get('titolo', '').strip()
            descrizione_breve = traduzione.get('descrizioneBreve', '').strip()
            testo_completo = traduzione.get('testoCompleto', '').strip()
            
            if not titolo:
                return None
            
            # Crea URL articolo: GraphQL dovrebbe fornire slug direttamente
            if slug:
                # Usa lo slug fornito da GraphQL (dovrebbe essere il path corretto)
                article_url = f"{self.config.base_url.rstrip('/')}/novita/notizie/{slug}/"
            else:
                # Fallback: costruisci da titolo se manca slug
                import re
                url_titolo = titolo.lower()
                url_titolo = re.sub(r'[^\w\s]', '', url_titolo)
                url_titolo = re.sub(r'\s+', '-', url_titolo.strip())
                article_url = f"{self.config.base_url.rstrip('/')}/novita/notizie/{url_titolo}/"
            
            # Content preview: usa descrizione breve o inizio del testo completo
            content_preview = descrizione_breve
            if not content_preview and testo_completo:
                # Rimuovi HTML dal testo completo per preview
                from bs4 import BeautifulSoup
                clean_text = BeautifulSoup(testo_completo, 'html.parser').get_text(strip=True)
                content_preview = clean_text[:300]
            
            if len(content_preview) < 30:
                content_preview = f"Notizia dal Comune di Carpi: {titolo}"
            
            # Tipologie per categoria
            categoria = "Comunicazioni"
            tipologie = notizia.get('tipologie', [])
            if tipologie:
                for tipologia in tipologie:
                    trad_tipo = tipologia.get('traduzioni', [])
                    if trad_tipo:
                        categoria = trad_tipo[0].get('nome', 'Comunicazioni')
                        break
            
            # Scarica e salva immagine localmente se è dall'API Comune Carpi
            final_image_url = immagine_url
            if (
                immagine_url
                and 'api.wp.ai4smartcity.ai' in immagine_url
                and self.config.config.get('auto_approve', False)
            ):
                final_image_url = self.download_and_save_image(immagine_url, unique_id)

            return {
                'title': titolo[:200],
                'url': article_url,
                'preview': content_preview[:500],
                'image_url': final_image_url,
                'publish_date': data_pubblicazione,
                'full_content': testo_completo,
                'source_id': unique_id,
                'category': categoria,
                'featured': in_evidenza
            }
            
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione dati GraphQL: {e}")
            return None
    
    def _scrape_from_wordpress_fallback(self) -> List[Dict[str, Any]]:
        """Fallback usando WordPress REST API"""
        try:
            if not self.wordpress_config:
                self.logger.error("Configurazione WordPress fallback non presente")
                return []
            
            # Crea temporaneamente un WordPressAPIScraper per il fallback
            wordpress_config = SiteConfig(
                name=self.config.name,
                base_url=self.config.base_url,
                scraper_type='wordpress_api',
                config=self.wordpress_config
            )
            
            wordpress_scraper = WordPressAPIScraper(wordpress_config, self.headers)
            return wordpress_scraper.scrape_articles()
            
        except Exception as e:
            self.logger.error(f"Errore nel fallback WordPress: {e}")
            return []
    
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Per GraphQL il contenuto completo è già disponibile nella risposta"""
        # Il testoCompleto è già incluso nella risposta GraphQL, non serve fetch aggiuntivo
        return None
    
    def _get_image_hash(self, image_content: bytes) -> str:
        """Calcola hash MD5 del contenuto dell'immagine"""
        return hashlib.md5(image_content).hexdigest()
    
    def _find_existing_image_by_hash(self, image_hash: str, media_dir: str) -> Optional[str]:
        """Cerca un'immagine esistente con lo stesso hash"""
        try:
            if not os.path.exists(media_dir):
                return None
                
            for filename in os.listdir(media_dir):
                if filename.startswith('comune_carpi_') and filename.endswith(('.jpg', '.png', '.webp')):
                    file_path = os.path.join(media_dir, filename)
                    try:
                        with open(file_path, 'rb') as f:
                            existing_hash = self._get_image_hash(f.read())
                            if existing_hash == image_hash:
                                return filename
                    except Exception as e:
                        self.logger.warning(f"Errore nel leggere {filename}: {e}")
                        continue
            return None
        except Exception as e:
            self.logger.warning(f"Errore nella ricerca immagini esistenti: {e}")
            return None
    
    def download_and_save_image(self, api_image_url: str, unique_id: str, force_download: bool = False) -> Optional[str]:
        """Scarica immagine dall'API e la salva localmente (evitando duplicati)"""
        # Se non c'è configurazione per download locale, restituisci URL originale
        if not force_download and not getattr(self.config, 'download_images_locally', False):
            # Solo per GraphQL Carpi (comportamento legacy)
            if not api_image_url or 'api.wp.ai4smartcity.ai' not in api_image_url:
                return api_image_url
        
        try:
            # Se non abbiamo un URL valido
            if not api_image_url:
                return None

            # Scegli header appropriati
            headers = {}
            if hasattr(self, 'graphql_headers') and 'api.wp.ai4smartcity.ai' in api_image_url:
                headers = self.graphql_headers
            else:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

            # Scarica l'immagine
            response = requests.get(api_image_url, headers=headers, timeout=15)
            response.raise_for_status()

            # Ridimensiona e converte in WebP
            image_content, ext = self._resize_image_if_needed(response.content)

            # Calcola hash del contenuto (dopo ridimensionamento)
            image_hash = self._get_image_hash(image_content)

            # Directory per le immagini
            media_dir = os.path.join(settings.MEDIA_ROOT, 'images', 'downloaded')
            os.makedirs(media_dir, exist_ok=True)

            # Controlla se esiste già un'immagine con lo stesso hash
            existing_filename = self._find_existing_image_by_hash(image_hash, media_dir)
            if existing_filename:
                media_url = f"{settings.MEDIA_URL}images/downloaded/{existing_filename}"
                self.logger.info(f"Immagine già esistente riutilizzata: {existing_filename} (hash: {image_hash[:12]}...)")
                return media_url

            # L'estensione ora viene restituita dalla funzione resize (sempre .webp)
            # Genera nome file con prefisso configurabile
            prefix = getattr(self.config, 'local_image_prefix', 'comune_carpi')
            filename = f"{prefix}_{unique_id}_{image_hash[:12]}{ext}"
            file_path = os.path.join(media_dir, filename)

            # Salva l'immagine
            with open(file_path, 'wb') as f:
                f.write(image_content)

            # Restituisci l'URL media Django
            media_url = f"{settings.MEDIA_URL}images/downloaded/{filename}"

            self.logger.info(f"Nuova immagine salvata: {filename} (hash: {image_hash[:12]}...)")
            return media_url
            
        except Exception as e:
            self.logger.error(f"Errore nel download immagine: {e}")
            return None

    def _resize_image_if_needed(self, image_bytes: bytes, max_width: int = 1200, max_height: int = 1200, quality: int = 60) -> tuple[bytes, str]:
        """
        Ridimensiona e converte un'immagine in WebP, mantenendo aspect ratio

        Args:
            image_bytes: Immagine originale in bytes
            max_width: Larghezza massima (default 1200px - ottimizzato per Google Discover)
            max_height: Altezza massima (default 1200px - ottimizzato per Google Discover)
            quality: Qualità WebP (default 60)

        Returns:
            Tuple (immagine_bytes, estensione) - sempre WebP
        """
        try:
            # Apri l'immagine da bytes
            img = Image.open(io.BytesIO(image_bytes))

            # Dimensioni originali
            original_width, original_height = img.size

            # Se l'immagine è già piccola, converti comunque in WebP per uniformità
            if original_width <= max_width and original_height <= max_height:
                self.logger.debug(f"Immagine già nelle dimensioni corrette: {original_width}x{original_height}, converto in WebP")

                # Converti in RGB se necessario
                if img.mode in ('RGBA', 'LA'):
                    pass  # Mantieni RGBA per trasparenza
                elif img.mode == 'P':
                    img = img.convert('RGBA')
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                # Salva come WebP
                output_buffer = io.BytesIO()
                img.save(output_buffer, format='WEBP', quality=quality, method=6)
                return output_buffer.getvalue(), '.webp'

            # Calcola nuove dimensioni mantenendo aspect ratio
            ratio = min(max_width / original_width, max_height / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)

            self.logger.info(f"Ridimensionamento immagine da {original_width}x{original_height} a {new_width}x{new_height}")

            # Ridimensiona con anti-aliasing di alta qualità
            img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Converti in RGB se necessario (WebP supporta RGBA per trasparenze)
            if img_resized.mode in ('RGBA', 'LA'):
                # Mantieni RGBA per WebP con trasparenza
                pass
            elif img_resized.mode == 'P':
                img_resized = img_resized.convert('RGBA')
            elif img_resized.mode != 'RGB':
                img_resized = img_resized.convert('RGB')

            # Salva in un buffer come WebP
            output_buffer = io.BytesIO()
            img_resized.save(output_buffer, format='WEBP', quality=quality, method=6)

            resized_bytes = output_buffer.getvalue()

            # Log del risparmio di spazio
            original_size_kb = len(image_bytes) / 1024
            resized_size_kb = len(resized_bytes) / 1024
            saving_percent = ((original_size_kb - resized_size_kb) / original_size_kb) * 100

            self.logger.info(f"Conversione WebP completata: {original_size_kb:.1f}KB → {resized_size_kb:.1f}KB (risparmio {saving_percent:.1f}%)")

            return resized_bytes, '.webp'

        except Exception as e:
            self.logger.warning(f"Errore nel ridimensionamento immagine, uso originale: {e}")
            # Prova a determinare estensione originale
            try:
                img = Image.open(io.BytesIO(image_bytes))
                ext = '.' + img.format.lower() if img.format else '.jpg'
            except:
                ext = '.jpg'
            return image_bytes, ext


class EmailScraper(BaseScraper):
    """Scraper per monitoraggio email IMAP"""

    def __init__(self, config: SiteConfig, headers: Dict[str, str]):
        super().__init__(config, headers)
        self.imap_server = config.config.get('imap_server')
        self.imap_port = config.config.get('imap_port', 993)
        self.email = config.config.get('email')
        self.password = config.config.get('password')
        self.mailbox = config.config.get('mailbox', 'INBOX')
        self.sender_filter = config.config.get('sender_filter', [])
        self.subject_filter = config.config.get('subject_filter', [])

        if not all([self.imap_server, self.email, self.password]):
            raise ValueError("EmailScraper richiede imap_server, email e password nella configurazione")

        # Import IMAP solo se necessario
        import imaplib
        import email as email_lib
        import email.utils
        from email.mime.text import MIMEText

        self.imaplib = imaplib
        self.email_lib = email_lib

    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli dalle email"""
        articles = []

        try:
            # Connessione IMAP (prova SSL prima, poi normale)
            self.logger.info(f"Connessione a {self.imap_server}:{self.imap_port}")

            try:
                mail = self.imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            except Exception as e:
                self.logger.info(f"SSL fallito, provo connessione normale: {e}")
                mail = self.imaplib.IMAP4(self.imap_server, 143)
                mail.starttls()

            mail.login(self.email, self.password)
            mail.select(self.mailbox)

            # Cerca email non lette usando UID stabili, non sequence number IMAP.
            status, messages = mail.uid('SEARCH', None, 'UNSEEN')

            if status == 'OK':
                email_uids = messages[0].split()
                self.logger.info(f"Trovate {len(email_uids)} email non lette")

                for email_uid in email_uids[-10:]:  # Prendi massimo ultime 10 email
                    try:
                        article = self._process_email(mail, email_uid)
                        if article:
                            articles.append(article)
                    except Exception as e:
                        self.logger.error(f"Errore processamento email UID {email_uid}: {e}")

            mail.close()
            mail.logout()

        except Exception as e:
            self.logger.error(f"Errore connessione IMAP: {e}")

        return articles

    def _process_email(self, mail, email_uid) -> Optional[Dict[str, Any]]:
        """Processa singola email"""
        try:
            # Fetch email
            status, msg_data = mail.uid('FETCH', email_uid, '(RFC822)')
            if status != 'OK':
                return None

            email_uid_str = email_uid.decode('ascii', errors='replace') if isinstance(email_uid, bytes) else str(email_uid)

            # Parse email
            email_message = self.email_lib.message_from_bytes(msg_data[0][1])

            # Estrai informazioni base con decodifica header RFC 2047
            from email.header import decode_header

            # Decodifica subject (può essere in formato =?utf-8?b?...?=)
            subject_raw = email_message.get('Subject', '')
            subject_parts = decode_header(subject_raw)
            subject = ''
            for content, encoding in subject_parts:
                if isinstance(content, bytes):
                    subject += content.decode(encoding or 'utf-8', errors='replace')
                else:
                    subject += content

            sender = email_message.get('From', '')
            date_received = email_message.get('Date', '')

            # Applica filtri se configurati
            if self.sender_filter and not any(s.lower() in sender.lower() for s in self.sender_filter):
                return None

            if self.subject_filter and not any(s.lower() in subject.lower() for s in self.subject_filter):
                return None

            # Estrai contenuto
            content = self._extract_email_content(email_message)
            if not content:
                return None

            # Prima estrai il contenuto HTML grezzo per le immagini (prima della conversione a testo)
            raw_html_content = self._get_raw_html_content(email_message)

            # Rileva tipo di contenuto automaticamente
            content_type, category, image_url, source_url = self._detect_content_type(content, sender, subject, raw_html_content)

            # I comunicati stampa allegano spesso la foto come file: ha priorità
            # sull'immagine estratta dall'HTML (che è tipicamente un logo/firma).
            if content_type != 'twitter':
                attached_image = self._extract_attached_image(email_message, email_uid_str)
                if attached_image:
                    image_url = attached_image
                    self.logger.info(f"Immagine allegata usata per l'articolo: {attached_image}")

            # Estrai e verifica link nel contenuto
            links_content = self._extract_and_fetch_links(content)

            self.logger.info(f"Email processata: {subject[:50]}... (Tipo: {content_type})")

            # Per tweet usa l'URL del tweet, per comunicati usa email://
            article_url = source_url if source_url else f"email://{email_uid_str}"

            return {
                'title': subject,
                'content': content,
                'preview': content[:300] + '...' if len(content) > 300 else content,
                'url': article_url,
                'date': self._parse_email_date(date_received),
                'sender': sender,
                'image': image_url,
                'image_url': image_url,
                'content_type': content_type,  # 'twitter' o 'comunicato'
                'category_override': category,  # Categoria specifica
                'links_content': links_content,  # Contenuto dei link estratti
                '_email_uid': email_uid_str
            }

        except Exception as e:
            self.logger.error(f"Errore processing email: {e}")
            return None

    def mark_article_processed(self, article_data: Dict[str, Any]) -> None:
        """Marca una email come letta solo dopo un salvataggio/duplicato confermato."""
        email_uid = article_data.get('_email_uid')
        if not email_uid:
            return

        try:
            try:
                mail = self.imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            except Exception as e:
                self.logger.info(f"SSL fallito durante mark seen, provo connessione normale: {e}")
                mail = self.imaplib.IMAP4(self.imap_server, 143)
                mail.starttls()

            mail.login(self.email, self.password)
            mail.select(self.mailbox)
            status, _ = mail.uid('STORE', email_uid, '+FLAGS', '(\\Seen)')
            if status == 'OK':
                self.logger.info(f"Email UID {email_uid} marcata come letta dopo processamento")
            else:
                self.logger.warning(f"Impossibile marcare letta email UID {email_uid}: status={status}")
            mail.close()
            mail.logout()
        except Exception as e:
            self.logger.error(f"Errore marcando letta email UID {email_uid}: {e}")

    def _detect_content_type(self, content: str, sender: str, subject: str, raw_html: str = "") -> tuple[str, str, Optional[str], Optional[str]]:
        """Rileva automaticamente il tipo di contenuto, estrae immagini e determina fonte"""

        # Indicatori per contenuto Twitter/Social
        twitter_indicators = [
            'twitter.com', 'pic.twitter.com', '@', '#', 'twitter-tweet',
            'action@ifttt.com', 'PMTerredargine', 'Polizia Locale'
        ]

        # Indicatori per comunicati stampa formali
        comunicato_indicators = [
            'comunicato stampa', 'comunicato', 'ufficio stampa', 'press release',
            'si comunica', 'si informa', 'sindaco', 'giunta', 'comune'
        ]

        content_lower = content.lower()
        subject_lower = subject.lower()
        sender_lower = sender.lower()

        # Controlla se è contenuto Twitter/Social
        is_twitter = (
            any(indicator in content_lower for indicator in twitter_indicators) or
            any(indicator in sender_lower for indicator in twitter_indicators) or
            'action@ifttt.com' in sender_lower
        )

        if is_twitter:
            # Estrai prima il link al tweet, poi la sua immagine (via API)
            tweet_url = self._extract_tweet_url(raw_html or content)
            twitter_image = self._extract_twitter_image(raw_html or content, tweet_url)
            return 'twitter', 'Cronaca Social', twitter_image, tweet_url

        # Controlla se è comunicato formale
        is_comunicato = any(indicator in content_lower or indicator in subject_lower
                           for indicator in comunicato_indicators)

        if is_comunicato:
            # Estrai immagine standard, fonte vuota per comunicati
            standard_image = self._extract_first_image(raw_html or content)
            return 'comunicato', 'Comunicati Stampa', standard_image, None

        # Default: tratta come comunicato generico
        return 'comunicato', 'Comunicati Stampa', self._extract_first_image(raw_html or content), None

    def _extract_twitter_image(self, content: str, tweet_url: Optional[str] = None) -> Optional[str]:
        """Estrae l'immagine di un tweet.

        Priorità:
          1) link diretto pbs.twimg.com già incorporato nell'email IFTTT;
          2) foto del tweet via API fxtwitter/vxtwitter.
        NON usa come fallback l'immagine di eventuali articoli linkati nel tweet:
        in passato causava foto sbagliate (es. immagine di wired.it al posto di
        quella del tweet). Meglio nessuna immagine che una sbagliata.
        """
        import re

        # 1) Link diretto pbs.twimg.com incorporato nell'email
        m = re.search(
            r'https://pbs\.twimg\.com/media/[\w-]+(?:\.(?:jpg|jpeg|png|webp))?(?:\?[^\s"\'<>]*)?',
            content
        )
        if m:
            return m.group(0)

        # 2) Foto direttamente dal tweet tramite API
        if not tweet_url:
            tweet_url = self._extract_tweet_url(content)
        if tweet_url:
            tweet_image = self._fetch_tweet_image(tweet_url)
            if tweet_image:
                return tweet_image

        # 3) Nessuna immagine del tweet trovata
        return None

    def _extract_tweet_url(self, content: str) -> Optional[str]:
        """Estrae URL del tweet originale da contenuto IFTTT"""
        import re

        # Pattern per link diretti al tweet
        tweet_url_patterns = [
            r'https://twitter\.com/\w+/status/\d+',
            r'http://twitter\.com/\w+/status/\d+',
            r'https://x\.com/\w+/status/\d+',
            r'http://x\.com/\w+/status/\d+'
        ]

        for pattern in tweet_url_patterns:
            matches = re.findall(pattern, content)
            if matches:
                url = matches[0]
                # Converti twitter.com in x.com se necessario
                if 'twitter.com' in url:
                    url = url.replace('twitter.com', 'x.com')
                return url

        # Se non trova link diretti, cerca link t.co e prova a espanderli
        t_co_pattern = r'https://t\.co/\w+'
        t_co_matches = re.findall(t_co_pattern, content)

        if t_co_matches:
            for t_co_url in t_co_matches:
                try:
                    expanded_url = self._expand_short_url(t_co_url)
                    if expanded_url and ('twitter.com' in expanded_url or 'x.com' in expanded_url):
                        # Converti twitter.com in x.com se necessario
                        if 'twitter.com' in expanded_url:
                            expanded_url = expanded_url.replace('twitter.com', 'x.com')
                        return expanded_url
                except Exception as e:
                    self.logger.debug(f"Errore espansione t.co per URL tweet {t_co_url}: {e}")
                    continue

        # Se non trova link diretti, cerca negli href dei tag <a>
        try:
            soup = BeautifulSoup(content, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']
                if any(domain in href for domain in ['twitter.com/status/', 'x.com/status/']):
                    if 'twitter.com' in href:
                        href = href.replace('twitter.com', 'x.com')
                    return href
        except Exception:
            pass

        return None

    def _expand_short_url(self, short_url: str) -> Optional[str]:
        """Espande un URL accorciato (t.co) per ottenere l'URL originale"""
        try:
            response = requests.head(short_url, allow_redirects=True, timeout=10)
            return response.url
        except Exception as e:
            self.logger.debug(f"Errore espansione URL {short_url}: {e}")
            return None

    def _fetch_tweet_image(self, tweet_url: str) -> Optional[str]:
        """Estrae l'immagine di un tweet usando le API JSON fxtwitter/vxtwitter.

        Molto più affidabile dello scraping dell'og:image (che spesso falliva o
        restituiva la card di un link esterno). Per i tweet-video restituisce la
        thumbnail. Ritorna un URL pbs.twimg.com diretto, oppure None.
        """
        import re

        m = re.search(r'(?:twitter\.com|x\.com|vxtwitter\.com|fxtwitter\.com)/([^/]+)/status/(\d+)', tweet_url)
        if not m:
            return None
        handle, tweet_id = m.group(1), m.group(2)

        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; OmbraBot/1.0; +https://ombradelportico.it)'
        }

        def _is_photo(url: str) -> bool:
            base = url.lower().split('?')[0]
            return base.endswith(('.jpg', '.jpeg', '.png', '.webp'))

        # 1) fxtwitter JSON
        try:
            r = requests.get(f'https://api.fxtwitter.com/{handle}/status/{tweet_id}', headers=headers, timeout=10)
            if r.status_code == 200:
                media = ((r.json().get('tweet') or {}).get('media')) or {}
                photos = media.get('photos') or []
                if photos and photos[0].get('url'):
                    return photos[0]['url']
                videos = media.get('videos') or []
                if videos and videos[0].get('thumbnail_url'):
                    return videos[0]['thumbnail_url']
        except Exception as e:
            self.logger.debug(f"fxtwitter fallito per {tweet_url}: {e}")

        # 2) vxtwitter JSON (fallback)
        try:
            r = requests.get(f'https://api.vxtwitter.com/{handle}/status/{tweet_id}', headers=headers, timeout=10)
            if r.status_code == 200:
                media_urls = r.json().get('mediaURLs') or []
                for u in media_urls:
                    if _is_photo(u):
                        return u
                if media_urls:  # es. solo video: usa comunque il primo media
                    return media_urls[0]
        except Exception as e:
            self.logger.debug(f"vxtwitter fallito per {tweet_url}: {e}")

        return None

    def _fetch_tweet_image_fallback(self, tweet_url: str) -> Optional[str]:
        """Metodo fallback per estrarre immagini da tweet"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            response = requests.get(tweet_url, headers=headers, timeout=10)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # Cerca immagini nelle meta tag Open Graph
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                image_url = og_image['content']
                if 'twimg.com' in image_url:
                    return image_url

            # Cerca immagini nei tag img con pattern Twitter
            img_tags = soup.find_all('img')
            for img in img_tags:
                src = img.get('src', '')
                if 'twimg.com' in src and ('media' in src or 'card_img' in src):
                    return src

            # Fallback: cerca link pic.twitter.com nel contenuto della pagina
            page_text = soup.get_text()
            import re
            pic_pattern = r'pic\.twitter\.com/\w+'
            matches = re.findall(pic_pattern, page_text)
            if matches:
                return f'https://{matches[0]}'

        except Exception as e:
            self.logger.debug(f"Errore estrazione immagine da tweet {tweet_url}: {e}")

        return None

    def _get_raw_html_content(self, email_message) -> str:
        """Estrae contenuto HTML grezzo senza conversioni per l'estrazione link/immagini"""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/html":
                    try:
                        return part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except (UnicodeDecodeError, AttributeError):
                        return str(part.get_payload(decode=True), errors='replace')
        else:
            if email_message.get_content_type() == "text/html":
                try:
                    return email_message.get_payload(decode=True).decode('utf-8', errors='replace')
                except (UnicodeDecodeError, AttributeError):
                    return str(email_message.get_payload(decode=True), errors='replace')
        return ""

    def _extract_and_fetch_links(self, content: str) -> List[Dict[str, str]]:
        """Estrae link dal contenuto e ne scarica il contenuto"""
        import re
        import requests
        from urllib.parse import urlparse

        links_content = []

        try:
            # Pattern per trovare link HTTP/HTTPS
            url_patterns = [
                r'https?://[^\s<>"\']+',  # Link diretti
                r'href=["\']([^"\']+)["\']'  # Link in tag HTML
            ]

            found_urls = set()

            # Estrai URL con regex
            for pattern in url_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    url = match.strip()
                    if url.startswith(('http://', 'https://')):
                        found_urls.add(url)

            # Estrai URL da tag HTML
            try:
                soup = BeautifulSoup(content, 'html.parser')
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if href.startswith(('http://', 'https://')):
                        found_urls.add(href)
            except Exception:
                pass

            # Filtra URL rilevanti (esclude Twitter, immagini, etc.)
            excluded_domains = [
                'twitter.com', 'x.com', 'pic.twitter.com', 'pbs.twimg.com',
                't.co',  # URL shortener Twitter
                'facebook.com', 'instagram.com', 'youtube.com'
            ]

            relevant_urls = []
            for url in found_urls:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()

                # Esclude domini social e estensioni immagini
                if (not any(excluded in domain for excluded in excluded_domains) and
                    not url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.pdf'))):
                    relevant_urls.append(url)

            # Limita a massimo 3 link per evitare overhead
            for url in relevant_urls[:3]:
                try:
                    self.logger.info(f"Scaricando contenuto da: {url}")

                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }

                    response = requests.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
                    response.raise_for_status()

                    # Parse HTML e estrai contenuto testuale
                    soup = BeautifulSoup(response.content, 'html.parser')

                    # Rimuovi script, style, nav, footer
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()

                    # Estrai titolo
                    title = ""
                    if soup.title:
                        title = soup.title.string.strip()

                    # Estrai contenuto principale
                    content_tags = soup.find_all(['p', 'h1', 'h2', 'h3', 'article', 'main'])
                    text_content = ' '.join(tag.get_text(strip=True) for tag in content_tags)

                    # Pulisci e limita il contenuto
                    clean_content = ' '.join(text_content.split())[:1000]  # Max 1000 caratteri

                    if clean_content and len(clean_content) > 100:  # Solo se ha contenuto significativo
                        links_content.append({
                            'url': url,
                            'title': title,
                            'content': clean_content
                        })

                except Exception as e:
                    self.logger.warning(f"Impossibile scaricare {url}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Errore estrazione link: {e}")

        return links_content

    def _extract_email_content(self, email_message) -> str:
        """Estrai contenuto dall'email (HTML o testo)"""
        content = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/html":
                    try:
                        raw_html = part.get_payload(decode=True).decode('utf-8', errors='replace')
                        self.logger.debug(f"HTML estratto, lunghezza: {len(raw_html)} caratteri")
                        # Converti HTML in testo leggibile, preservando il contenuto HTML per estrazione immagini
                        content = self._html_to_text(raw_html)
                        self.logger.debug(f"Testo estratto da HTML, lunghezza: {len(content)} caratteri")
                        break
                    except (UnicodeDecodeError, AttributeError):
                        # Fallback con encoding più permissivo
                        content = str(part.get_payload(decode=True), errors='replace')
                        content = self._html_to_text(content)
                        break
                elif part.get_content_type() == "text/plain" and not content:
                    try:
                        content = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except (UnicodeDecodeError, AttributeError):
                        content = str(part.get_payload(decode=True), errors='replace')
        else:
            content_type = email_message.get_content_type()
            if content_type == "text/html":
                try:
                    raw_html = email_message.get_payload(decode=True).decode('utf-8', errors='replace')
                    self.logger.debug(f"HTML estratto (non-multipart), lunghezza: {len(raw_html)} caratteri")
                    content = self._html_to_text(raw_html)
                    self.logger.debug(f"Testo estratto (non-multipart), lunghezza: {len(content)} caratteri")
                except (UnicodeDecodeError, AttributeError):
                    content = str(email_message.get_payload(decode=True), errors='replace')
                    content = self._html_to_text(content)
            elif content_type == "text/plain":
                try:
                    content = email_message.get_payload(decode=True).decode('utf-8', errors='replace')
                except (UnicodeDecodeError, AttributeError):
                    content = str(email_message.get_payload(decode=True), errors='replace')

        self.logger.info(f"Contenuto email estratto, lunghezza finale: {len(content)} caratteri")
        return content.strip()

    def _html_to_text(self, html_content: str) -> str:
        """Converti HTML in testo pulito con gestione migliorata per tweet"""
        try:
            import html

            # Prima fai unescape dell'HTML per gestire contenuto escaped
            unescaped_content = html.unescape(html_content)

            soup = BeautifulSoup(unescaped_content, 'html.parser')

            # Rimuovi script, style, e altri elementi non necessari
            for tag in soup(["script", "style", "head", "meta", "link"]):
                tag.decompose()

            # Per tweet IFTTT, cerca il contenuto specifico del tweet
            tweet_content = ""

            # Cerca blockquote twitter-tweet per contenuto tweet
            twitter_blockquote = soup.find('blockquote', class_='twitter-tweet')
            if twitter_blockquote:
                # Estrai solo il testo del tweet, non i link ai profili
                tweet_p = twitter_blockquote.find('p')
                if tweet_p:
                    # Sostituisci hashtag e mention con testo normale
                    for link in tweet_p.find_all('a'):
                        href = link.get('href', '')
                        text = link.get_text()

                        if '/hashtag/' in href:
                            # Trasforma #hashtag in testo normale
                            link.replace_with(text)
                        elif href.startswith('https://twitter.com/') and not '/status/' in href:
                            # Trasforma @mention in testo normale
                            link.replace_with(text)
                        else:
                            # Mantieni altri link
                            link.replace_with(f" {text} ")

                    tweet_content = tweet_p.get_text()

            # Se non trova tweet specifico, estrai tutto il testo
            if not tweet_content:
                # IMPORTANTE: Preserva i paragrafi sostituendo i tag HTML con newline prima dell'estrazione
                # Questo mantiene la struttura dei paragrafi come negli altri monitor
                import re

                # Sostituisci tag di chiusura paragrafo/div/br con doppia newline
                for tag in soup.find_all(['p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    tag.append('\n\n')  # Aggiungi doppia newline dopo ogni paragrafo

                text = soup.get_text()
            else:
                text = tweet_content

            # Pulisci il testo
            # Rimuovi caratteri di controllo e sostituisci emoji problematici
            import re

            # Sostituisci emoji comuni con testo
            emoji_replacements = {
                '👮': 'agenti',
                '🚔': 'pattuglia',
                '👉': '',
                '⚠️': 'attenzione',
                '🚧': 'cantiere',
                '🚗': 'traffico',
                '📍': 'posizione'
            }

            for emoji, replacement in emoji_replacements.items():
                text = text.replace(emoji, f' {replacement} ')

            # Pulisci spazi multipli SOLO per spazi, NON per newline
            # Preserva doppie newline per divisione paragrafi (come negli altri monitor)
            text = re.sub(r'[ \t]+', ' ', text)  # Collassa solo spazi/tab orizzontali
            text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newline consecutive
            text = text.strip()

            # Se il testo è troppo corto o sembra vuoto, prova estrazione alternativa
            if len(text) < 20:
                text = soup.get_text()
                text = re.sub(r'[ \t]+', ' ', text)  # Collassa solo spazi/tab orizzontali
                text = re.sub(r'\n{3,}', '\n\n', text).strip()  # Max 2 newline consecutive

            return text

        except Exception as e:
            self.logger.error(f"Errore conversione HTML: {e}")
            # Fallback: restituisci HTML grezzo pulito preservando paragrafi
            import re
            # Sostituisci tag di chiusura paragrafo con doppie newline
            clean_text = re.sub(r'</p>|</div>|<br\s*/?>|</h[1-6]>', '\n\n', html_content)
            clean_text = re.sub(r'<[^>]+>', ' ', clean_text)  # Rimuovi altri tag
            clean_text = re.sub(r'[ \t]+', ' ', clean_text)  # Collassa spazi/tab
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()  # Max 2 newline
            return clean_text

    def _extract_first_image(self, content: str) -> Optional[str]:
        """Estrai prima immagine dal contenuto HTML"""
        try:
            if 'http' not in content:
                return None

            soup = BeautifulSoup(content, 'html.parser')
            img = soup.find('img')
            if img and img.get('src'):
                return img['src']
        except Exception:
            pass
        return None

    def _extract_attached_image(self, email_message, unique_id: str) -> Optional[str]:
        """Estrae l'immagine allegata (o inline) dall'email e la salva in /media/.

        Sceglie l'allegato immagine più grande per evitare loghi, firme e pixel
        di tracking. Restituisce l'URL /media/... locale, oppure None.
        """
        try:
            if not email_message.is_multipart():
                return None

            import re
            import hashlib

            best_bytes = None
            best_ext = '.jpg'
            best_size = 0

            for part in email_message.walk():
                ctype = part.get_content_type()
                if not ctype.startswith('image/'):
                    continue

                try:
                    payload = part.get_payload(decode=True)
                except Exception:
                    payload = None
                if not payload:
                    continue

                size = len(payload)
                # Scarta immagini troppo piccole: loghi, firme, pixel di tracking
                if size < 8000:
                    continue

                if size > best_size:
                    best_size = size
                    best_bytes = payload
                    subtype = ctype.split('/', 1)[1].lower()
                    ext_map = {
                        'jpeg': '.jpg', 'jpg': '.jpg', 'png': '.png',
                        'gif': '.gif', 'webp': '.webp'
                    }
                    best_ext = ext_map.get(subtype, '.jpg')

            if not best_bytes:
                return None

            image_hash = hashlib.sha256(best_bytes).hexdigest()
            media_dir = os.path.join(settings.MEDIA_ROOT, 'images', 'downloaded')
            os.makedirs(media_dir, exist_ok=True)

            # Dedup: riusa un file già salvato con lo stesso hash
            for existing in os.listdir(media_dir):
                if image_hash[:16] in existing:
                    self.logger.info(f"Immagine allegata già esistente riutilizzata: {existing}")
                    return f"{settings.MEDIA_URL}images/downloaded/{existing}"

            safe_id = re.sub(r'[^A-Za-z0-9_-]', '', str(unique_id))[:20] or 'email'
            filename = f"email_{safe_id}_{image_hash[:16]}{best_ext}"
            file_path = os.path.join(media_dir, filename)
            with open(file_path, 'wb') as f:
                f.write(best_bytes)

            self.logger.info(f"Immagine allegata salvata: {filename} ({best_size} bytes)")
            return f"{settings.MEDIA_URL}images/downloaded/{filename}"

        except Exception as e:
            self.logger.error(f"Errore estrazione immagine allegata: {e}")
            return None

    def _parse_email_date(self, date_str: str) -> str:
        """Parse data email"""
        try:
            if date_str:
                parsed_date = self.email_lib.utils.parsedate_to_datetime(date_str)
                return parsed_date.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def get_full_content(self, article_url: str) -> Optional[str]:
        """Per email, il contenuto è già completo"""
        return None  # Il contenuto è già estratto in scrape_articles


class UniversalNewsMonitor:
    """Monitor universale per diversi tipi di siti news"""

    def __init__(self, site_config: SiteConfig, check_interval: int = 900):
        self.config = site_config
        self.monitor_name = site_config.name  # Salva il nome per ricaricare config
        self.check_interval = check_interval
        self.seen_articles = {}
        self.is_running = False
        self.monitor_thread = None
        self.lock_fd = None

        # Logger specifico per questo monitor
        self.logger = get_monitor_logger(site_config.name.lower().replace(' ', '_'))

        # File lock - usa directory locks del progetto
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        locks_dir = os.path.join(project_dir, 'locks')
        os.makedirs(locks_dir, exist_ok=True)  # Crea directory se non esiste

        self.lock_file_path = os.path.join(
            locks_dir,
            f'{site_config.name.lower().replace(" ", "_")}_monitor.lock'
        )

        # Headers standard (Accept-Encoding rimosso per evitare problemi di decompressione)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
        }

        # Crea scraper appropriato
        self.scraper = self._create_scraper()
    
    def _reload_config_from_db(self) -> bool:
        """Ricarica la configurazione dal database e aggiorna lo scraper se necessario"""
        try:
            db_monitor = MonitorConfig.objects.get(name=self.monitor_name)

            # Se il monitor è stato disattivato, fermalo
            if not db_monitor.is_active:
                self.logger.warning(f"Monitor disattivato dal database, arresto...")
                self.is_running = False
                return False

            # Crea nuova configurazione dal database usando to_site_config()
            # che garantisce la precedenza corretta dei campi del modello
            new_config = db_monitor.to_site_config()

            # Controlla se la configurazione è cambiata
            config_changed = (
                self.config.base_url != new_config.base_url or
                self.config.scraper_type != new_config.scraper_type or
                self.config.config != new_config.config
            )

            if config_changed:
                self.logger.info("Configurazione modificata, ricarico...")
                self.config = new_config
                self.scraper = self._create_scraper()
                self.logger.info("Configurazione aggiornata con successo")

            # Aggiorna intervallo se cambiato
            new_interval = db_monitor.config_data.get('interval', 900)
            if new_interval != self.check_interval:
                self.logger.info(f"Intervallo aggiornato: {self.check_interval}s -> {new_interval}s")
                self.check_interval = new_interval

            return True

        except MonitorConfig.DoesNotExist:
            self.logger.error(f"Monitor {self.monitor_name} non trovato nel database, arresto...")
            self.is_running = False
            return False
        except Exception as e:
            self.logger.error(f"Errore nel ricaricamento configurazione: {e}")
            return True  # Continua con la configurazione attuale

    def _create_scraper(self) -> BaseScraper:
        """Crea il scraper appropriato basato sulla configurazione"""
        scraper_classes = {
            'html': HTMLScraper,
            'wordpress_api': WordPressAPIScraper,
            'youtube_api': YouTubeAPIScraper,
            'graphql': GraphQLScraper,
            'email': EmailScraper
        }

        scraper_class = scraper_classes.get(self.config.scraper_type)
        if not scraper_class:
            raise ValueError(f"Tipo scraper non supportato: {self.config.scraper_type}")

        return scraper_class(self.config, self.headers)
    
    def get_article_hash(self, title: str, url: str) -> str:
        """Crea hash dell'articolo per rilevare duplicati"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    def acquire_lock(self) -> bool:
        """Acquisisce lock esclusivo con gestione migliorata"""
        try:
            # Prima controlla se esiste già un lock file orfano
            if os.path.exists(self.lock_file_path):
                try:
                    # Prova a leggere il PID dal lock file
                    with open(self.lock_file_path, 'r') as f:
                        old_pid = int(f.read().strip())
                    
                    # Controlla se il processo è ancora attivo
                    if not self._is_process_running(old_pid):
                        self.logger.info(f"Rimuovo lock file orfano (PID {old_pid} non più attivo)")
                        os.unlink(self.lock_file_path)
                except (ValueError, FileNotFoundError, PermissionError):
                    # File corrotto o non accessibile, prova a rimuoverlo
                    try:
                        os.unlink(self.lock_file_path)
                        self.logger.info("Rimosso lock file corrotto")
                    except:
                        pass
            
            self.lock_fd = os.open(self.lock_file_path, os.O_CREAT | os.O_TRUNC | os.O_RDWR)

            # Scrivi il PID prima di acquisire il lock
            pid_bytes = f"{os.getpid()}\n".encode()
            os.write(self.lock_fd, pid_bytes)
            os.fsync(self.lock_fd)

            # Ora acquisisci il lock
            if platform.system() == 'Windows':
                # Su Windows, skip msvcrt.locking che causa problemi
                # Il lock file stesso serve come indicatore
                self.logger.info("Windows: usando lock file-based senza msvcrt.locking")
                pass
            else:
                fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            self.logger.info(f"Lock acquisito: {self.lock_file_path}")
            return True
            
        except (OSError, IOError) as e:
            if self.lock_fd:
                try:
                    os.close(self.lock_fd)
                except:
                    pass
                self.lock_fd = None
            
            self.logger.warning(f"Impossibile acquisire lock: {e}")
            return False
    
    def _is_process_running(self, pid: int) -> bool:
        """Controlla se un processo con il PID dato è ancora attivo"""
        try:
            if platform.system() == 'Windows':
                # Su Windows, usa tasklist per controllare se il PID esiste
                result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], 
                                      capture_output=True, text=True)
                return str(pid) in result.stdout
            else:
                # Su Unix, usa os.kill con signal 0
                os.kill(pid, 0)
                return True
        except (OSError, subprocess.SubprocessError):
            return False
    
    def release_lock(self):
        """Rilascia il lock"""
        if self.lock_fd is not None:
            try:
                if platform.system() == 'Windows':
                    # Su Windows, skip msvcrt.locking
                    pass
                else:
                    fcntl.lockf(self.lock_fd, fcntl.LOCK_UN)

                os.close(self.lock_fd)
                self.lock_fd = None

                if os.path.exists(self.lock_file_path):
                    os.unlink(self.lock_file_path)

                self.logger.info("Lock rilasciato")
            except (OSError, IOError) as e:
                self.logger.error(f"Errore nel rilasciare lock: {e}")
    
    def check_for_new_articles(self):
        """Controlla per nuovi articoli"""
        try:
            # Aggiorna last_run nel database
            self._update_last_run()

            new_articles = self.scraper.scrape_articles()

            if new_articles:
                self.logger.info(f"Trovati {len(new_articles)} potenziali nuovi articoli")

                processed_count = 0
                for article_data in new_articles:
                    article_hash = self.get_article_hash(article_data['title'], article_data['url'])

                    # Controllo duplicati sia in memoria che nel database
                    if article_hash not in self.seen_articles:
                        # Controllo duplicati nel database prima di processare
                        # Controlla sia per URL esatto che per titolo simile
                        existing_by_url = Articolo.objects.filter(fonte=article_data['url']).exists()
                        existing_by_title = Articolo.objects.filter(titolo=article_data['title']).exists()

                        if not existing_by_url and not existing_by_title:
                            success = self.process_new_article(article_data)
                            if success:
                                processed_count += 1
                                # Aggiungi hash solo se articolo effettivamente creato
                                self.seen_articles[article_hash] = datetime.now().isoformat()
                                self.scraper.mark_article_processed(article_data)
                        else:
                            # Articolo già esistente, aggiungi comunque l'hash per evitare ricontrolli DB
                            self.seen_articles[article_hash] = datetime.now().isoformat()
                            self.scraper.mark_article_processed(article_data)
                            self.logger.debug(f"Articolo già esistente nel DB: {article_data['title'][:50]}...")
                    else:
                        self.logger.debug(f"Articolo già visto in memoria: {article_data['title'][:50]}...")

                self.logger.info(f"Processati {processed_count} nuovi articoli")
            else:
                self.logger.debug("Nessun nuovo articolo trovato")

        except Exception as e:
            self.logger.error(f"Errore nel controllo articoli: {e}")

    def _update_last_run(self):
        """Aggiorna il timestamp last_run nel database"""
        try:
            from home.models import MonitorConfig
            monitor = MonitorConfig.objects.filter(name=self.config.name).first()
            if monitor:
                monitor.last_run = timezone.now()
                monitor.save(update_fields=['last_run'])
        except Exception as e:
            self.logger.debug(f"Impossibile aggiornare last_run: {e}")

    def _article_exists_for_data(self, article_data: Dict[str, Any]) -> bool:
        """Verifica se il processamento ha realmente prodotto o trovato un articolo."""
        article_url = article_data.get('url')
        title = article_data.get('title')

        if article_url and Articolo.objects.filter(fonte=article_url).exists():
            return True
        if title and Articolo.objects.filter(titolo=title).exists():
            return True
        return False
    
    def should_auto_approve(self, category: str) -> bool:
        """Determina se un articolo deve essere auto-approvato basandosi sulla configurazione"""
        # Solo la configurazione specifica del sito determina l'auto-approvazione
        return self.config.config.get('auto_approve', False)
    
    def process_new_article(self, article_data: Dict[str, Any]) -> bool:
        """Processa un nuovo articolo"""
        try:
            self.logger.info(f"Processando nuovo articolo: {article_data['title']}")
            self.logger.debug(f"[DEBUG process_new_article] URL: {article_data['url']}")

            # Se necessario, scarica immagine dall'articolo invece che dal JSON
            if article_data.get('_fetch_image_from_article', False):
                self.logger.debug(f"[DEBUG] fetch_image_from_article attivo, scarico immagine da articolo")
                try:
                    response = self.scraper._get_request(article_data['url'], timeout=15)
                    soup = BeautifulSoup(response.content, 'html.parser')

                    # Cerca og:image
                    og_image = soup.select_one('meta[property="og:image"]')
                    if og_image:
                        new_image_url = og_image.get('content')
                        if new_image_url:
                            self.logger.debug(f"[DEBUG] Trovato og:image: {new_image_url}")
                            article_data['image_url'] = new_image_url
                except Exception as e:
                    self.logger.warning(f"[DEBUG] Errore scaricando immagine da articolo: {e}")

            # Ottieni contenuto completo se necessario
            if not article_data.get('full_content'):
                self.logger.debug(f"[DEBUG process_new_article] Scarico contenuto completo da: {article_data['url']}")
                full_content = self.scraper.get_full_content(article_data['url'])
                if full_content:
                    self.logger.debug(f"[DEBUG process_new_article] Contenuto ottenuto: {len(full_content)} chars, preview: {full_content[:150]}")
                    article_data['full_content'] = full_content
                else:
                    # Per YouTube, NON creare articolo se transcript mancante (sarà ritentato)
                    if isinstance(self.scraper, YouTubeAPIScraper):
                        self.logger.warning(f"[YOUTUBE] Transcript non disponibile per {article_data['url']} - articolo NON creato, sarà ritentato")
                        return False  # Skip creazione articolo

                    # Per altri tipi (email, HTML), usa fallback con preview
                    fallback_content = article_data.get('content') or article_data['preview']
                    self.logger.warning(f"[DEBUG process_new_article] get_full_content() ha fallito! Uso fallback: {len(fallback_content)} chars, preview: {fallback_content[:150]}")
                    article_data['full_content'] = fallback_content
            else:
                self.logger.debug(f"[DEBUG process_new_article] full_content già presente: {len(article_data['full_content'])} chars")
            
            # Genera articolo con AI se configurato
            use_ai = self.config.config.get('use_ai_generation', False)
            self.logger.warning(f"[DEBUG] Controllo AI generation: use_ai={use_ai}, config keys={list(self.config.config.keys())[:10]}")

            if use_ai:
                self.logger.warning("[DEBUG] Chiamata generate_ai_article()...")
                result = self.generate_ai_article(article_data)
                self.logger.info(f"Articolo AI generato: {result}")
                if not self._article_exists_for_data(article_data):
                    self.logger.warning(
                        "Generazione AI senza articolo salvato: "
                        f"{result}. La sorgente restera' da processare."
                    )
                    return False
            else:
                self.logger.warning("[DEBUG] AI disabilitata, salvataggio diretto")
                # Salva direttamente senza AI
                self.save_article_directly(article_data)
                if not self._article_exists_for_data(article_data):
                    self.logger.warning(
                        "Salvataggio diretto completato senza articolo nel DB. "
                        "La sorgente restera' da processare."
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Errore nel processare articolo: {e}")
            return False
    
    def generate_ai_article(self, article_data: Dict[str, Any]) -> str:
        """Genera articolo con AI con ricerca web conversazionale integrata"""
        self.logger.warning(f"[DEBUG] generate_ai_article START per: {article_data.get('title', 'N/A')}")
        try:
            self.logger.warning("[DEBUG] Import Anthropic...")
            from anthropic import Anthropic
            from django.conf import settings

            # Usa API key dalla config del monitor, altrimenti usa quella dalle settings Django
            api_key = self.config.config.get('ai_api_key') or getattr(settings, 'ANTHROPIC_API_KEY', None)
            if not api_key:
                raise ValueError("API key mancante per generazione AI (né in monitor config né in settings)")

            client = Anthropic(api_key=api_key)

            preliminary_title = article_data.get('title')
            existing = None
            if article_data.get('url'):
                existing = Articolo.objects.filter(fonte=article_data['url']).first()
            if not existing and preliminary_title:
                existing = Articolo.objects.filter(titolo=preliminary_title).first()
            if existing:
                self.logger.info(f"Articolo saltato (pre-check duplicato): {existing.titolo}")
                return f"Articolo gia' esistente con ID: {existing.id}"

            # Scegli prompt in base al tipo di contenuto (MANTENIAMO IDENTICI)
            content_type = article_data.get('content_type', 'comunicato')

            # Aggiungi data corrente al contesto
            self.logger.warning("[DEBUG] Creazione date_context...")
            _now = datetime.now()
            _giorni_sett = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
            today_date = _now.strftime("%d/%m/%Y")
            today_weekday = _giorni_sett[_now.weekday()]
            date_context = (
                f"\n\nIMPORTANTE: La data odierna è {today_weekday} {today_date}. "
                "Usa questa data come riferimento per verificare fatti, nomi di cariche pubbliche e informazioni correnti "
                "e dare un valore cronologico alle informazioni che trovi online. "
                "NON calcolare a mente il giorno della settimana di una data: usa SOLO i giorni della settimana "
                "già indicati esplicitamente nel contenuto o nelle fonti. Se un giorno della settimana non è fornito, "
                "riporta solo la data numerica senza inventare il giorno."
            )
            self.logger.warning(f"[DEBUG] date_context creato: {today_date}")

            if content_type == 'twitter':
                base_prompt = self.config.config.get('ai_twitter_prompt',
                    self.config.config.get('ai_system_prompt',
                    """Sei un giornalista esperto. Rielabora questa notizia per il giornale locale."""))
                system_prompt = base_prompt + date_context + TWITTER_FIDELITY_GUARDRAILS + ARTICLE_OUTPUT_GUARDRAILS + TAGS_INSTRUCTION
            else:
                base_prompt = self.config.config.get('ai_system_prompt',
                    """Sei un giornalista esperto. Rielabora questa notizia per il giornale locale.""")
                system_prompt = base_prompt + date_context + ARTICLE_OUTPUT_GUARDRAILS + TAGS_INSTRUCTION

            # Costruisci contenuto con eventuali link (MANTENIAMO)
            links_section = ""
            if article_data.get('links_content'):
                links_section = "\n\nContenuto aggiuntivo dai link riferiti:\n"
                for i, link_data in enumerate(article_data['links_content'], 1):
                    link_content = truncate_ai_source_text(
                        link_data.get('content', ''),
                        self.logger,
                        label=f"Contenuto link {i}"
                    )
                    links_section += f"\n--- Link {i}: {link_data['url']} ---\n"
                    if link_data.get('title'):
                        links_section += f"Titolo: {link_data['title']}\n"
                    links_section += f"Contenuto: {link_content}\n"

            # Setup per Tool Use conversazionale autonomo
            enable_web_search = self.config.config.get('enable_web_search', False)
            web_sources = []  # Lista delle fonti web utilizzate da Claude


            # Tool definition per ricerca web (aggiuntiva, opzionale)
            web_search_tool_def = None
            if enable_web_search:
                web_search_tool_def = {
                    "name": "web_search",
                    "description": """OBBLIGATORIO: usa la ricerca web per verificare fatti (nomi, date, luoghi, organizzazioni) e arricchire l'articolo con contesto e dettagli.

                    COME SCRIVERE LA QUERY (decisivo per ottenere risultati):
                    - BREVE: 2-4 parole chiave essenziali (nomi propri, luogo, tema). MAI una frase lunga.
                    - NON attaccare l'anno o numeri ai nomi: scrivi "Manuela Ghizzoni Fondazione Fossoli", NON "Manuela Ghizzoni2026".
                    - Parti generico: le query troppo specifiche restituiscono ZERO risultati. Meglio poche parole giuste.
                    - Esempi:
                        BUONA: "Yoga Radio Bruno Estate Carpi"  |  CATTIVA: "Yoga Radio Bruno Estate 2026 Carpi piazza Martiri luglio"
                        BUONA: "Orchestra Tangenziale Villotti documentario"  |  CATTIVA: "Doc orchestra ritmica tangenziale raccordi Villotti Negroni anziani ottantenni"

                    ATTENZIONE ALLE DATE: ogni risultato riporta la "Data pubblicazione". Puoi usare anche fonti datate (per contesto e retroscena), ma colloca ogni fatto nel suo tempo: NON scambiare un fatto passato per attuale (cariche, ruoli e situazioni possono essere cambiati nel frattempo). Verifica la coerenza con la data odierna.

                    Fai almeno una ricerca per il fact-checking, poi decidi se i risultati sono abbastanza pertinenti da includerli come fonti (se non lo sono, non includerli).""",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Query BREVE: 2-4 parole chiave (nomi, luogo, tema). No frasi lunghe, no anno attaccato ai nomi."
                            },
                            "max_results": {
                                "type": "integer",
                                "default": 2,
                                "description": "Numero massimo di risultati (1-5)"
                            }
                        },
                        "required": ["query"]
                    }
                }

            content = article_data.get('full_content') or article_data.get('content', '')
            content = truncate_ai_source_text(content, self.logger)

            # Contenuto iniziale per Claude con ricerca forzata
            user_content = f"""Fonte: {article_data['url']}
Titolo originale: {article_data['title']}

Contenuto principale da rielaborare:
{content}
{links_section}

Rielabora questa notizia creando un articolo coinvolgente e ben strutturato.
{f"OBBLIGATORIO: Devi SEMPRE usare web_search almeno una volta per verificare fatti e approfondire l'articolo. Usa query BREVI (2-4 parole chiave: nomi propri, luogo, tema), non frasi lunghe e senza attaccare l'anno ai nomi. Dopo aver fatto le ricerche, decidi autonomamente se i risultati sono abbastanza rilevanti e specifici da includere come fonti, oppure se è meglio non includere fonti generiche o poco pertinenti." if enable_web_search else "Lavora solo con il contenuto fornito."}"""

            user_content = truncate_ai_source_text(user_content, self.logger, label="Messaggio user generate_article")

            # Tools da includere
            tools = [web_search_tool_def] if web_search_tool_def else []

            self.logger.info(f"Inizio generazione AI articolo: '{article_data['title']}' (web search: {enable_web_search})")
            self.logger.warning("[DEBUG] Preparazione chiamata API Anthropic...")

            # --- Selezione provider AI ---
            # Default globale da settings.AI_ARTICLE_PROVIDER (env AI_ARTICLE_PROVIDER);
            # override per-monitor con config_data "ai_provider".
            default_provider = getattr(settings, 'AI_ARTICLE_PROVIDER', 'anthropic')
            provider = (self.config.config.get('ai_provider') or default_provider).lower()
            articolo_testo = None
            used_sources = []
            ai_model_used = None

            if provider == 'openrouter':
                or_result = None
                try:
                    or_result = self._generate_with_openrouter(
                        system_prompt, user_content, web_search_tool_def, article_data
                    )
                except Exception as or_err:
                    self.logger.error(f"[OpenRouter] Generazione fallita, fallback ad Anthropic: {or_err}", exc_info=True)
                    or_result = None
                if or_result and or_result[0] and or_result[0].strip():
                    articolo_testo, used_sources, ai_model_used = or_result
                    self.logger.info(f"[OpenRouter] Articolo generato con {ai_model_used}")
                else:
                    self.logger.warning("[OpenRouter] Nessun contenuto valido, fallback ad Anthropic")

            # Path Anthropic: default, oppure fallback se OpenRouter non ha prodotto nulla
            if not (articolo_testo and articolo_testo.strip()):
                # Prima chiamata ad Anthropic
                # Se tools è vuoto, non passarlo all'API
                api_params = {
                    "system": system_prompt,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": user_content}],
                    "model": "claude-sonnet-4-6"
                }
                if tools:
                    api_params["tools"] = tools

                self.logger.warning("[DEBUG] Chiamata client.messages.create...")
                message = client.messages.create(**api_params)
                self.logger.warning("[DEBUG] Risposta API ricevuta")

                # Traccia utilizzo API (prima chiamata)
                try:
                    from home.api_usage_tracker import APIUsageTracker
                    APIUsageTracker.track_anthropic(
                        operation='generate_article',
                        model=api_params["model"],
                        input_tokens=message.usage.input_tokens,
                        output_tokens=message.usage.output_tokens,
                        related_article=None,  # Articolo non ancora creato
                        success=True
                    )
                except Exception as e:
                    self.logger.warning(f"Errore nel tracciare utilizzo API: {e}")

                # Modello AI usato (di default Anthropic)
                ai_model_used = api_params["model"]

                # Processa risposta e gestisci tool use conversazionale
                self.logger.warning("[DEBUG] Inizio _process_conversational_response...")
                response_data = self._process_conversational_response(
                    client, message, system_prompt, user_content, tools, web_sources, article_data, web_search_tool_def
                )
                self.logger.warning(f"[DEBUG] _process_conversational_response completato, response_data len: {len(response_data)}")

                # Gestisci tuple di 2 o 3 elementi (fallback OpenAI aggiunge modello)
                if len(response_data) == 3:
                    articolo_testo, used_sources, ai_model_used = response_data
                else:
                    articolo_testo, used_sources = response_data

            if not articolo_testo:
                raise Exception("Nessun contenuto ricevuto dalla conversazione AI")

            # Usa categoria override se disponibile, altrimenti quella di default
            category = article_data.get('category_override', self.config.category)
            parsed_article = parse_ai_article_json(articolo_testo)

            if parsed_article:
                self.logger.warning("[DEBUG] Risposta AI JSON valida")
                raw_titolo = content_polisher.clean_title_plain(parsed_article.get('titolo', ''))[:200]
                ok, reason = content_polisher.is_natural_italian_title(raw_titolo)
                if not ok:
                    self.logger.warning(
                        f"[TITOLO REJECTED] '{raw_titolo}' - {reason}"
                    )
                titolo = raw_titolo

                raw_titolo_seo = content_polisher.clean_title_plain(parsed_article.get('titolo_seo', ''))[:70]
                if raw_titolo_seo:
                    ok, reason = content_polisher.is_natural_seo_title(raw_titolo_seo)
                    if ok:
                        titolo_seo = raw_titolo_seo
                    else:
                        self.logger.warning(
                            f"[TITOLO_SEO REJECTED] '{raw_titolo_seo}' - {reason} "
                            f"- uso titolo regular come fallback"
                        )
                        titolo_seo = ''
                else:
                    titolo_seo = ''
                contenuto = parsed_article.get('contenuto', '')
                sommario = content_polisher.clean_content_plain(parsed_article.get('sommario', ''))
                tags_estratti = normalize_ai_tags(parsed_article.get('tags'), category)
            else:
                self.logger.warning("[DEBUG] Risposta AI non JSON, uso parser legacy")
                articolo_testo, tags_estratti = extract_tags(articolo_testo, category)

                # Estrai titolo e contenuto usando il content polisher
                self.logger.warning("[DEBUG] Estrazione titolo e contenuto...")
                titolo, contenuto = content_polisher.extract_clean_title_from_ai_response(articolo_testo)
                sommario = ''
                self.logger.warning(f"[DEBUG] Titolo estratto: {titolo[:50] if titolo else 'None'}...")

                # Se l'estrazione fallisce, usa il metodo fallback
                if not titolo:
                    titolo = content_polisher.clean_title(article_data['title'])[:200]
                if not contenuto:
                    contenuto = content_polisher.clean_content(articolo_testo)
                titolo_seo = ''

            # Rileva se l'AI ha rifiutato/avvisato invece di generare un articolo
            # (il titolo supera i 200 caratteri: l'AI ha scritto un avviso invece di seguire il formato)
            if len(titolo or '') > 200 and article_data.get('content_type') == 'comunicato':
                self.logger.warning(f"[REVISIONE] AI ha rifiutato il comunicato '{(titolo or '')[:80]}...' - invio email per revisione manuale")
                try:
                    from home.email_notifications import send_comunicato_review_notification
                    send_comunicato_review_notification(article_data, articolo_testo)
                except Exception as mail_err:
                    self.logger.error(f"[REVISIONE] Errore invio email revisione: {mail_err}")
                return "Comunicato inviato per revisione manuale (AI ha rilevato contenuto sospetto)"

            # Applica polishing finale
            polished_data = content_polisher.polish_article({
                'titolo': titolo,
                'contenuto': contenuto,
                'sommario': sommario
            })

            # Salva nel database con protezione race condition
            self.logger.warning("[DEBUG] Inizio salvataggio DB...")
            from django.db import transaction

            # Controllo atomico per prevenire duplicati da race condition
            with transaction.atomic():
                self.logger.warning("[DEBUG] Transaction atomic block enter")
                # Lock a livello DB: controlla se esiste già per URL fonte o titolo
                # (per articoli senza fonte come editoriali usa il titolo)
                if article_data.get('url'):
                    existing = Articolo.objects.select_for_update().filter(fonte=article_data['url']).first()
                else:
                    # Per articoli senza fonte (editoriali), usa il titolo generato dall'AI
                    existing = Articolo.objects.select_for_update().filter(titolo=polished_data['titolo']).first()

                if existing:
                    self.logger.warning(f"Articolo AI già esistente (race condition evitata): {existing.titolo}")
                    return f"Articolo già esistente con ID: {existing.id}"

                # Determina se deve essere auto-approvato
                auto_approve = self.should_auto_approve(category)

                # Estrai data evento se presente (per Eventi Carpi GraphQL)
                data_evento = None
                if article_data.get('event_start'):
                    try:
                        # Formato: "2025-10-28T10:00:00" o "2025-10-28"
                        event_start_str = article_data['event_start']
                        if 'T' in event_start_str:
                            data_evento = datetime.fromisoformat(event_start_str).date()
                        else:
                            data_evento = datetime.strptime(event_start_str, '%Y-%m-%d').date()
                    except Exception as e:
                        self.logger.warning(f"Errore parsing data evento: {e}")

                self.logger.warning("[DEBUG] Creazione oggetto Articolo...")
                articolo = Articolo(
                    titolo=polished_data['titolo'][:200],
                    titolo_seo=titolo_seo,
                    contenuto=polished_data['contenuto'],
                    sommario=polished_data.get('sommario', ''),
                    categoria=category,
                    tags=tags_estratti,
                    fonte=article_data['url'],
                    foto=article_data.get('image_url'),
                    foto_valida=True,
                    fonti_web=used_sources if used_sources else None,  # Salva fonti web utilizzate
                    ai_model_used=ai_model_used,  # Modello AI usato (Anthropic o OpenAI fallback)
                    data_evento=data_evento,  # Imposta data evento se disponibile
                    approvato=auto_approve,  # Auto-approva se configurato
                    data_pubblicazione=timezone.now()
                )
                self.logger.warning("[DEBUG] Chiamata articolo.save()...")
                articolo.save()
                self.logger.warning(f"[DEBUG] Articolo salvato! ID: {articolo.id}")
                download_article_image_in_background(
                    articolo.id,
                    article_data.get('image_url'),
                    articolo.slug,
                )

                search_status = f" (fonti web: {len(used_sources)})" if enable_web_search and used_sources else ""
                return f"Articolo AI salvato con ID: {articolo.id}{search_status}"

        except Exception as e:
            self.logger.error(f"[DEBUG] ECCEZIONE in generate_ai_article: {e}", exc_info=True)
            return f"Errore nella generazione AI: {e}"

    def _process_conversational_response(self, client, message, system_prompt: str,
                                       initial_user_content: str, tools, web_sources: List, article_data: Dict[str, Any], web_search_tool_def: Dict = None):
        """Processa la risposta conversazionale di Anthropic gestendo tool use

        Returns:
            tuple: (content, sources) oppure (content, sources, model_name) se fallback OpenAI
        """
        try:
            conversation = [{"role": "user", "content": initial_user_content}]
            current_message = message
            max_iterations = 3  # Limite iterazioni: taglia le ricerche a vuoto della coda
            iteration = 0

            while iteration < max_iterations:
                response_content = ""
                tool_uses = []

                # Analizza i blocchi di contenuto
                for content_block in current_message.content:
                    if content_block.type == "text":
                        response_content += content_block.text
                    elif content_block.type == "tool_use":
                        tool_uses.append(content_block)

                # Se non ci sono tool use, abbiamo finito
                if not tool_uses:
                    self.logger.info(f"Conversazione AI completata dopo {iteration} iterazioni")
                    return response_content, web_sources

                # Aggiungi la risposta assistant alla conversazione
                conversation.append({"role": "assistant", "content": current_message.content})

                # Processa i tool use
                tool_results = []
                for tool_use in tool_uses:
                    if tool_use.name == "web_search":
                        query = tool_use.input.get("query", "")
                        max_results = tool_use.input.get("max_results", 2)

                        self.logger.info(f"Claude richiede ricerca web: '{query}'")

                        # Effettua ricerca con contenuto completo con retry e gestione errori robusta
                        search_results = []
                        error_message = None

                        try:
                            from home.web_search_tool import web_search_tool

                            # Retry con backoff esponenziale
                            max_retries = 2
                            retry_delay = 1  # secondi

                            for attempt in range(max_retries):
                                try:
                                    search_results = web_search_tool.search_with_content(
                                        query, max_results, fetch_content=True
                                    )

                                    # Successo - esci dal loop
                                    if search_results:
                                        break

                                    # Nessun risultato ma nessun errore - prova ancora
                                    if attempt < max_retries - 1:
                                        self.logger.warning(f"Tentativo {attempt + 1}: nessun risultato, riprovo in {retry_delay}s")
                                        time.sleep(retry_delay)
                                        retry_delay *= 2  # Backoff esponenziale

                                except Exception as search_error:
                                    self.logger.warning(f"Tentativo {attempt + 1} web search fallito: {search_error}")

                                    if attempt < max_retries - 1:
                                        time.sleep(retry_delay)
                                        retry_delay *= 2
                                    else:
                                        # Ultimo tentativo fallito
                                        error_message = str(search_error)

                        except Exception as e:
                            self.logger.error(f"Errore critico web search per '{query}': {e}")
                            error_message = str(e)

                        # Gestione risultati o errori
                        if search_results:
                            # Traccia utilizzo Google Search API
                            try:
                                from home.api_usage_tracker import APIUsageTracker
                                APIUsageTracker.track_google_search(
                                    operation='web_search_for_article',
                                    num_queries=1,  # Una query per tool_use
                                    related_article=None,
                                    success=True
                                )
                            except Exception as e:
                                self.logger.warning(f"Errore nel tracciare utilizzo Google Search: {e}")

                            # Salva le fonti utilizzate
                            for result in search_results:
                                if result['url'] not in [s['url'] for s in web_sources]:
                                    web_sources.append({
                                        'url': result['url'],
                                        'title': result.get('page_title', result['title']),
                                        'query_used': query
                                    })

                            # Formatta per Claude con contenuto completo
                            formatted_results = web_search_tool.format_results_with_content_for_ai(search_results)

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": formatted_results
                            })

                            self.logger.info(f"Forniti {len(search_results)} risultati con contenuto completo a Claude")
                        else:
                            # Nessun risultato o errore - comunica a Claude di continuare senza
                            error_msg = f"Ricerca web non disponibile al momento"
                            if error_message:
                                if "quota" in error_message.lower() or "429" in error_message:
                                    error_msg = "Quota API Google esaurita. Procedi con le informazioni disponibili."
                                elif "timeout" in error_message.lower():
                                    error_msg = "Timeout ricerca web. Procedi con le informazioni disponibili."
                                else:
                                    error_msg = f"Ricerca web non disponibile ({error_message[:100]}). Procedi con le informazioni disponibili."

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": error_msg,
                                "is_error": False  # Non è un errore bloccante
                            })

                            self.logger.warning(f"Web search fallita per '{query}', ma continuo senza bloccare: {error_msg}")

                # Se abbiamo tool results, continua la conversazione
                if tool_results:
                    conversation.append({"role": "user", "content": tool_results})

                    # Nuova chiamata ad Anthropic
                    api_params_iter = {
                        "system": system_prompt,
                        "max_tokens": 4096,
                        "messages": conversation,
                        "model": "claude-sonnet-4-6"
                    }
                    if tools:
                        api_params_iter["tools"] = tools

                    limit_conversation_messages(api_params_iter["messages"], self.logger)
                    current_message = client.messages.create(**api_params_iter)

                    # Traccia utilizzo API (chiamate successive conversazionali)
                    try:
                        from home.api_usage_tracker import APIUsageTracker
                        APIUsageTracker.track_anthropic(
                            operation='generate_article_conversational',
                            model=api_params_iter["model"],
                            input_tokens=current_message.usage.input_tokens,
                            output_tokens=current_message.usage.output_tokens,
                            related_article=None,
                            success=True
                        )
                    except Exception as e:
                        self.logger.warning(f"Errore nel tracciare utilizzo API conversazionale: {e}")

                    iteration += 1
                else:
                    break

            # Se arriviamo qui, abbiamo raggiunto il limite di iterazioni
            self.logger.warning(f"Conversazione AI interrotta dopo {max_iterations} iterazioni")

            try:
                conversation.append({
                    "role": "user",
                    "content": (
                        "Hai raggiunto il limite massimo di ricerche. Non usare altri strumenti. "
                        "Genera ora l'articolo finale usando solo le informazioni disponibili e "
                        "rispondi esclusivamente con il JSON richiesto dal system prompt."
                    )
                })
                final_params = {
                    "system": system_prompt,
                    "max_tokens": 4096,
                    "messages": conversation,
                    "model": "claude-sonnet-4-6"
                }
                limit_conversation_messages(final_params["messages"], self.logger)
                final_message = client.messages.create(**final_params)

                try:
                    from home.api_usage_tracker import APIUsageTracker
                    APIUsageTracker.track_anthropic(
                        operation='generate_article_final_no_tools',
                        model=final_params["model"],
                        input_tokens=final_message.usage.input_tokens,
                        output_tokens=final_message.usage.output_tokens,
                        related_article=None,
                        success=True
                    )
                except Exception as e:
                    self.logger.warning(f"Errore nel tracciare utilizzo API finale senza tool: {e}")

                final_response = ""
                for content_block in final_message.content:
                    if content_block.type == "text":
                        final_response += content_block.text

                if final_response.strip():
                    self.logger.warning("Conversazione AI completata con fallback finale senza tool")
                    return final_response, web_sources
            except Exception as final_error:
                self.logger.error(f"Fallback finale senza tool fallito: {final_error}")

            # Restituisci l'ultimo contenuto disponibile
            final_content = ""
            for content_block in current_message.content:
                if content_block.type == "text":
                    final_content += content_block.text

            return final_content, web_sources

        except Exception as e:
            error_str = str(e)

            # Se errore 529 (Overloaded), prova fallback OpenAI
            if "529" in error_str or "overloaded" in error_str.lower():
                self.logger.warning(f"Anthropic API sovraccarica (529), fallback a OpenAI...")
                try:
                    content, sources, openai_model = self._generate_with_openai_fallback(
                        article_data, system_prompt, web_search_tool_def
                    )
                    # Ritorna tuple estesa con modello OpenAI
                    return content, sources, openai_model
                except Exception as openai_error:
                    self.logger.error(f"Anche fallback OpenAI fallito: {openai_error}")
            else:
                self.logger.error(f"Errore nella conversazione AI: {e}")

            # Fallback finale: prova a estrarre il testo dalla risposta originale
            try:
                fallback_content = ""
                for content_block in current_message.content:
                    if content_block.type == "text":
                        fallback_content += content_block.text
                return fallback_content, web_sources
            except:
                return "", web_sources

    def _track_openrouter_usage(self, operation: str, model: str, resp):
        """Traccia l'utilizzo di una chiamata OpenRouter (formato usage OpenAI)."""
        try:
            from home.api_usage_tracker import APIUsageTracker
            u = getattr(resp, 'usage', None)
            APIUsageTracker.track_openrouter(
                operation=operation,
                model=model,
                input_tokens=getattr(u, 'prompt_tokens', 0) or 0,
                output_tokens=getattr(u, 'completion_tokens', 0) or 0,
                related_article=None,
                success=True,
            )
        except Exception as e:
            self.logger.warning(f"Errore nel tracciare utilizzo OpenRouter: {e}")

    def _run_article_web_search(self, query: str, max_results: int, web_sources: List) -> str:
        """Esegue una ricerca web per il loop OpenRouter e ne traccia l'uso.

        Aggiorna web_sources in-place e ritorna i risultati formattati (o un
        messaggio non bloccante se la ricerca fallisce/è vuota).
        """
        from home.web_search_tool import web_search_tool
        self.logger.info(f"[OpenRouter] Ricerca web: '{query}'")
        try:
            results = web_search_tool.search_with_content(query, max_results, fetch_content=True)
        except Exception as e:
            self.logger.warning(f"[OpenRouter] web search fallita '{query}': {e}")
            return "Ricerca web non disponibile al momento. Procedi con le informazioni disponibili."
        if not results:
            return "Nessun risultato dalla ricerca. Procedi con le informazioni disponibili."
        try:
            from home.api_usage_tracker import APIUsageTracker
            APIUsageTracker.track_google_search(
                operation='web_search_for_article',
                num_queries=1,
                related_article=None,
                success=True,
            )
        except Exception as e:
            self.logger.warning(f"[OpenRouter] Errore tracking Google Search: {e}")
        for result in results:
            if result['url'] not in [s['url'] for s in web_sources]:
                web_sources.append({
                    'url': result['url'],
                    'title': result.get('page_title', result['title']),
                    'query_used': query,
                })
        return web_search_tool.format_results_with_content_for_ai(results)

    def _generate_with_openrouter(self, system_prompt: str, initial_user_content: str,
                                  web_search_tool_def: Dict, article_data: Dict[str, Any]):
        """Genera l'articolo via OpenRouter (Chat Completions) con loop tool-use e
        finalizzazione forzata, replicando il comportamento del path Anthropic.

        Ritorna (contenuto, web_sources, model_name) oppure None su errore/contenuto vuoto,
        così che il chiamante possa ricorrere al fallback Anthropic.
        """
        from openai import OpenAI
        from django.conf import settings

        api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
        if not api_key:
            self.logger.error("[OpenRouter] OPENROUTER_API_KEY mancante: impossibile generare")
            return None

        model = (self.config.config.get('ai_openrouter_model')
                 or getattr(settings, 'OPENROUTER_ARTICLE_MODEL', 'deepseek/deepseek-v4-pro'))
        client = OpenAI(
            base_url=getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'),
            api_key=api_key,
            default_headers={
                'HTTP-Referer': getattr(settings, 'SITE_URL', 'https://ombradelportico.it'),
                'X-Title': 'Ombra del Portico',
            },
        )

        # Tool web_search in formato OpenAI (function calling)
        tools = None
        if web_search_tool_def:
            tools = [{
                "type": "function",
                "function": {
                    "name": web_search_tool_def["name"],
                    "description": web_search_tool_def["description"],
                    "parameters": web_search_tool_def["input_schema"],
                },
            }]

        web_sources = []
        conversation = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_user_content},
        ]
        max_iterations = 3  # Limite iterazioni: taglia le ricerche a vuoto della coda
        natural_end = False
        text = ''

        for iteration in range(max_iterations):
            # max_tokens generoso: DeepSeek V4 è reasoning, serve spazio per ragionamento +
            # stesura articolo, altrimenti l'articolo esce vuoto o troncato
            params = {"model": model, "max_tokens": 8192, "messages": conversation}
            if tools:
                params["tools"] = tools
                params["tool_choice"] = "auto"
            limit_conversation_messages(params["messages"], self.logger)
            resp = client.chat.completions.create(**params)
            self._track_openrouter_usage('generate_article_openrouter', model, resp)

            msg = resp.choices[0].message
            tool_calls = getattr(msg, 'tool_calls', None)
            if not tool_calls:
                text = msg.content or ''
                natural_end = True
                self.logger.info(f"[OpenRouter] Conversazione completata dopo {iteration} iterazioni")
                break

            conversation.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in tool_calls],
            })
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                query = args.get("query", "")
                formatted = self._run_article_web_search(query, args.get("max_results", 2), web_sources)
                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": formatted,
                })

        # Finalizzazione forzata (come produzione): stesura finale senza tool
        if not natural_end:
            self.logger.warning(f"[OpenRouter] Limite {max_iterations} iterazioni raggiunto, forzo stesura finale")
            conversation.append({
                "role": "user",
                "content": (
                    "Hai raggiunto il limite massimo di ricerche. Non usare altri strumenti. "
                    "Genera ora l'articolo finale usando solo le informazioni disponibili e "
                    "rispondi esclusivamente con il JSON richiesto dal system prompt."
                ),
            })
            # DeepSeek V4 è reasoning: sulla finalizzazione (contesto pesante dopo 5 ricerche)
            # reasoning + articolo sforavano i 4096 token e il contenuto tornava vuoto -> fallback
            # a Claude. Alziamo max_tokens per lasciare spazio a entrambi, mantenendo il reasoning
            # attivo (migliore sintesi delle fonti).
            params = {
                "model": model,
                "max_tokens": 8192,
                "messages": conversation,
            }
            if tools:
                params["tools"] = tools
                params["tool_choice"] = "none"
            limit_conversation_messages(params["messages"], self.logger)
            resp = client.chat.completions.create(**params)
            self._track_openrouter_usage('generate_article_openrouter_final', model, resp)
            text = resp.choices[0].message.content or ''

        if not (text and text.strip()):
            return None
        return text, web_sources, model

    def _generate_with_openai_fallback(self, article_data: Dict[str, Any], system_prompt: str, web_search_tool_def: Dict = None) -> tuple[str, list, str]:
        """Fallback a OpenAI GPT-4 Turbo quando Anthropic è sovraccarico

        Returns:
            tuple: (contenuto, web_sources, model_name)
        """
        from openai import OpenAI
        from django.conf import settings

        # API key OpenAI
        openai_api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY non configurata in settings")

        client = OpenAI(api_key=openai_api_key)

        # Costruisci prompt con contenuto articolo
        links_section = ""
        if article_data.get('links_content'):
            links_section = "\n\nContenuto aggiuntivo dai link riferiti:\n"
            for i, link_data in enumerate(article_data['links_content'], 1):
                link_content = truncate_ai_source_text(
                    link_data.get('content', ''),
                    self.logger,
                    label=f"Contenuto link fallback {i}"
                )
                links_section += f"\n--- Link {i}: {link_data['url']} ---\n"
                if link_data.get('title'):
                    links_section += f"Titolo: {link_data['title']}\n"
                links_section += f"Contenuto: {link_content}\n"

        content = article_data.get('full_content', '')
        content = truncate_ai_source_text(content, self.logger)

        user_prompt = f"""Titolo originale: {article_data['title']}

Contenuto originale:
{content}
{links_section}

Rielabora questa notizia seguendo le istruzioni del sistema. Rispondi SOLO con JSON valido con i campi titolo, sommario, contenuto e tags."""

        # Chiamata a OpenAI (senza tool use per semplicità)
        user_prompt = truncate_ai_source_text(user_prompt, self.logger, label="Messaggio user openai_fallback")
        response = client.chat.completions.create(
            model="gpt-4-turbo-2024-04-09",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=4096,
            temperature=0.7
        )

        content = response.choices[0].message.content

        # Traccia utilizzo API
        try:
            from home.api_usage_tracker import APIUsageTracker
            APIUsageTracker.track_openai(
                operation='openai_fallback',
                model='gpt-4-turbo-2024-04-09',
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                related_article=None,
                success=True
            )
        except Exception as tracker_error:
            self.logger.warning(f"Errore nel tracciare utilizzo OpenAI: {tracker_error}")

        # Log utilizzo
        self.logger.info(f"OpenAI fallback completato: {response.usage.total_tokens} tokens")

        # Nessuna fonte web (OpenAI non ha tool use in questo fallback)
        return content, [], 'gpt-4-turbo-2024-04-09'

    def save_article_directly(self, article_data: Dict[str, Any]):
        """Salva articolo direttamente senza AI con protezione race condition"""
        from django.db import transaction

        # Controllo atomico per prevenire duplicati da race condition
        with transaction.atomic():
            # Lock a livello DB: controlla se esiste già per URL fonte o titolo
            # (per articoli senza fonte come editoriali usa il titolo)
            if article_data.get('url'):
                existing = Articolo.objects.select_for_update().filter(fonte=article_data['url']).first()
            else:
                # Per articoli senza fonte (editoriali), usa il titolo
                existing = Articolo.objects.select_for_update().filter(titolo=article_data['title']).first()

            if existing:
                self.logger.warning(f"Articolo già esistente (race condition evitata): {existing.titolo}")
                return

            # Applica polishing anche al salvataggio diretto
            polished_data = content_polisher.polish_article({
                'titolo': article_data['title'],
                'contenuto': article_data['full_content']
            })
            _, tags_estratti = extract_tags('', self.config.category)

            # Determina se deve essere auto-approvato
            auto_approve = self.should_auto_approve(self.config.category)

            # Estrai data evento se presente (per Eventi Carpi GraphQL)
            data_evento = None
            if article_data.get('event_start'):
                try:
                    from datetime import datetime
                    # Formato: "2025-10-28T10:00:00" o "2025-10-28"
                    event_start_str = article_data['event_start']
                    if 'T' in event_start_str:
                        data_evento = datetime.fromisoformat(event_start_str).date()
                    else:
                        data_evento = datetime.strptime(event_start_str, '%Y-%m-%d').date()
                except Exception as e:
                    self.logger.warning(f"Errore parsing data evento: {e}")

            articolo = Articolo(
                titolo=polished_data['titolo'],
                contenuto=polished_data['contenuto'],
                categoria=self.config.category,
                tags=tags_estratti,
                fonte=article_data['url'],
                foto=article_data.get('image_url'),
                foto_valida=True,
                data_evento=data_evento,  # Imposta data evento se disponibile
                approvato=auto_approve,  # Auto-approva se configurato
                data_pubblicazione=timezone.now()
            )
            articolo.save()
            self.logger.info(f"Articolo salvato direttamente con ID: {articolo.id}")
            download_article_image_in_background(
                articolo.id,
                article_data.get('image_url'),
                articolo.slug,
            )
    
    def start_monitoring(self, daemon: bool = False) -> bool:
        """Avvia il monitoraggio"""
        if self.is_running:
            self.logger.warning("Monitor già in esecuzione")
            return False

        if not self.acquire_lock():
            self.logger.error("Impossibile avviare monitor: lock non acquisibile")
            return False

        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=daemon)
        self.monitor_thread.start()
        self.logger.info(f"Monitor avviato ({'daemon' if daemon else 'background'}). Controllo ogni {self.check_interval} secondi")
        return True
    
    def stop_monitoring(self):
        """Ferma il monitoraggio"""
        self.is_running = False
        self.release_lock()
        self.logger.info("Monitor fermato")
    
    def _monitor_loop(self):
        """Loop principale del monitoraggio"""
        from django.db import close_old_connections, connection
        try:
            # Controllo iniziale
            try:
                self.logger.info("Controllo iniziale...")
                self.check_for_new_articles()
            except Exception as e:
                self.logger.error(f"Errore nel controllo iniziale: {e}")
            finally:
                connection.close()

            # Loop di monitoraggio
            while self.is_running:
                try:
                    self.logger.debug(f"Controllo alle {datetime.now().strftime('%H:%M:%S')}")
                    time.sleep(self.check_interval)

                    if self.is_running:
                        # Rinnova connessione DB per evitare "connection already closed" nei thread
                        close_old_connections()

                        # Ricarica configurazione dal database prima di ogni controllo
                        if not self._reload_config_from_db():
                            break  # Se il reload fallisce o il monitor è disattivato, esci

                        self.check_for_new_articles()
                except Exception as e:
                    self.logger.error(f"Errore nel loop: {e}")
                    time.sleep(60)
                finally:
                    connection.close()

        finally:
            self.release_lock()
            self.logger.info("Monitor loop terminato")
