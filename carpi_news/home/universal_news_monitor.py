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
from datetime import datetime
from bs4 import BeautifulSoup
from django.utils import timezone
from urllib.parse import urljoin, urlparse
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from django.conf import settings

from home.models import Articolo

# Import platform-specific locking
if platform.system() == 'Windows':
    import msvcrt
else:
    import fcntl

# Import configurazione logging centralizzata
from home.logger_config import get_monitor_logger
from home.content_polisher import content_polisher

# Il logger sarà configurato dinamicamente per ogni monitor


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
        
    @abstractmethod
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli dal sito"""
        pass
    
    @abstractmethod
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Ottiene il contenuto completo di un articolo"""
        pass


class HTMLScraper(BaseScraper):
    """Scraper per siti HTML generici"""
    
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape articoli tramite HTML con supporto RSS discovery"""
        articles = []

        # 1. Se RSS non è disabilitato, prova RSS discovery prima
        if not self.config.config.get('disable_rss', False):
            rss_articles = self._discover_articles_from_rss()
            articles.extend(rss_articles)

        # 2. Poi scrapa pagine HTML normalmente
        urls_to_scrape = [self.config.config.get('news_url', self.config.base_url)]
        
        # Aggiungi URLs aggiuntivi se configurati (escludendo RSS feed)
        additional_urls = self.config.config.get('additional_urls', [])
        for url in additional_urls:
            if not url.endswith('/feed/') and not url.endswith('.rss'):
                urls_to_scrape.append(url)
        
        for url in urls_to_scrape:
            try:
                self.logger.info(f"Scraping HTML: {url}")
                
                response = requests.get(url, headers=self.headers, timeout=15)
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
            
            response = requests.get(rss_url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            # Parse RSS feed
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            
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
                        image_url = None
                        if full_content:
                            # Cerca immagini nel contenuto completo
                            from bs4 import BeautifulSoup
                            content_soup = BeautifulSoup(full_content, 'html.parser')
                            img_elem = content_soup.find('img')
                            if img_elem:
                                image_url = self._extract_image_from_html_elem(img_elem)
                        
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
    
    def _extract_articles_from_page(self, soup: BeautifulSoup, selectors: List[str], page_url: str) -> List[Dict[str, Any]]:
        """Estrae articoli da una singola pagina"""
        articles = []
        news_items = []
        
        # Prova tutti i selettori per trovare elementi
        for selector in selectors:
            items = soup.select(selector)
            if items:
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
            link_elem = item.find('a', href=True)
            
        if not link_elem:
            return None
            
        article_url = link_elem.get('href')
        if article_url.startswith('http'):
            # URL assoluta, usa così com'è
            pass
        else:
            # URL relativa (/, ../, ./), usa urljoin per risolverla
            article_url = urljoin(self.config.base_url, article_url)
        
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
            return None
        
        # Applica filtro keywords anche per HTML scraping (controllo su contenuto completo)
        filter_keywords = self.config.config.get('content_filter_keywords', [])
        if filter_keywords:
            # Scarica contenuto completo per il filtro
            full_content = self.get_full_content(article_url)
            content_to_check = f"{title} {content_preview} {full_content or ''}".lower()
            has_keyword = any(keyword.lower() in content_to_check for keyword in filter_keywords)
            if not has_keyword:
                return None
        
        # Immagine
        image_url = self._extract_image_from_html(item)
        
        return {
            'title': title,
            'url': article_url,
            'preview': content_preview,
            'image_url': image_url,
            'full_content': None  # Sarà caricato se necessario
        }
    
    def _extract_image_from_html(self, item) -> Optional[str]:
        """Estrae URL immagine da elemento HTML usando selettori personalizzati se configurati"""
        # Usa selettori immagine personalizzati se configurati
        image_selectors = self.config.config.get('image_selectors', ['img'])

        for selector in image_selectors:
            img_elem = item.select_one(selector)
            if img_elem:
                image_url = self._extract_image_from_html_elem(img_elem)
                if image_url:
                    return image_url

        # Fallback al metodo standard
        img_elem = item.find('img')
        if not img_elem:
            return None
        return self._extract_image_from_html_elem(img_elem)
    
    def _extract_image_from_html_elem(self, img_elem) -> Optional[str]:
        """Estrae URL immagine da un elemento img specifico"""
        img_src = (img_elem.get('data-src') or 
                  img_elem.get('data-lazy-src') or 
                  img_elem.get('src'))
        
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
        
        if img_src.startswith('/'):
            return urljoin(self.config.base_url, img_src)
        elif img_src.startswith('http'):
            return img_src
        
        return None
    
    def get_full_content(self, article_url: str) -> Optional[str]:
        """Scarica contenuto completo da pagina HTML"""
        try:
            response = requests.get(article_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
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
                    break
            
            # Fallback
            if not content or len(content) < 100:
                body = soup.find('body')
                if body:
                    content = body.get_text(strip=True)
            
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
        response = requests.get(f"{api_url}?per_page={per_page}", 
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
        response = requests.get(api_url, headers=api_headers, timeout=15)
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
                media_response = requests.get(
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
        
        return {
            'title': title,
            'url': article_url,
            'preview': content_preview[:500],
            'image_url': image_url,
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
                
                if img_src.startswith('/'):
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
        
        # Se non abbiamo API key/playlist ma abbiamo video IDs di fallback, va bene
        if not self.api_key or not self.playlist_id:
            if not self.fallback_video_ids:
                raise ValueError("YouTubeAPIScraper richiede (api_key + playlist_id) o fallback_video_ids")
            else:
                self.logger.warning("YouTube API non configurata, usando modalità fallback con video IDs")
    
    def scrape_articles(self) -> List[Dict[str, Any]]:
        """Scrape video da playlist YouTube o usa fallback IDs"""
        
        # Se abbiamo API key e playlist, usa YouTube API
        if self.api_key and self.playlist_id and not self.api_key.startswith("AIzaSyDummy"):
            return self._scrape_from_api()
        
        # Altrimenti usa modalità fallback
        return self._scrape_from_fallback_ids()
    
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
                    article_data = {
                        'title': item['snippet']['title'][:200],
                        'url': f"https://www.youtube.com/watch?v={item['snippet']['resourceId']['videoId']}",
                        'preview': item['snippet']['description'][:500],
                        'image_url': item['snippet'].get('thumbnails', {}).get('medium', {}).get('url'),
                        'video_id': item['snippet']['resourceId']['videoId'],
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
    
    def get_video_transcript(self, video_id: str) -> Optional[str]:
        """Estrae trascrizione da video YouTube con rate limiting"""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            
            # Applica rate limiting se configurato
            delay = self.config.config.get('transcript_delay', 0)
            if delay > 0:
                self.logger.info(f"Applicando pausa di {delay} secondi prima della richiesta transcript")
                time.sleep(delay)
            
            self.logger.info(f"Estrazione transcript per video {video_id}")
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id, languages=['it'])
            text = " ".join([entry.text for entry in transcript])
            self.logger.info(f"Transcript estratto: {len(text)} caratteri")
            return text
            
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione transcript per {video_id}: {e}")
            return None


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
                query = {
                    'operationName': 'getNotizie',
                    'variables': {
                        'pageNumber': 1,
                        'pageSize': 12
                    },
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
            
            # Aggiungi informazioni pratiche
            if evento.get('dataOraInizio'):
                content_parts.append(f"Data inizio: {evento['dataOraInizio']}")
            if evento.get('dataOraFine'):
                content_parts.append(f"Data fine: {evento['dataOraFine']}")
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
            if event_image_url and 'api.wp.ai4smartcity.ai' in event_image_url:
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
            if immagine_url and 'api.wp.ai4smartcity.ai' in immagine_url:
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
    
    def download_and_save_image(self, api_image_url: str, unique_id: str) -> Optional[str]:
        """Scarica immagine dall'API e la salva localmente (evitando duplicati)"""
        if not api_image_url or 'api.wp.ai4smartcity.ai' not in api_image_url:
            return api_image_url
        
        try:
            # Scarica l'immagine dall'API
            response = requests.get(api_image_url, headers=self.graphql_headers, timeout=15)
            response.raise_for_status()
            
            # Calcola hash del contenuto
            image_content = response.content
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
            
            # Determina l'estensione dal content-type
            content_type = response.headers.get('content-type', '').lower()
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = '.jpg'
            elif 'png' in content_type:
                ext = '.png'
            elif 'webp' in content_type:
                ext = '.webp'
            else:
                ext = '.jpg'  # Default
            
            # Crea nome file basato sull'hash invece che UUID casuale
            filename = f"comune_carpi_{unique_id}_{image_hash[:12]}{ext}"
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

            # Cerca email non lette
            status, messages = mail.search(None, 'UNSEEN')

            if status == 'OK':
                email_ids = messages[0].split()
                self.logger.info(f"Trovate {len(email_ids)} email non lette")

                for email_id in email_ids[-10:]:  # Prendi massimo ultime 10 email
                    try:
                        article = self._process_email(mail, email_id)
                        if article:
                            articles.append(article)
                            # Marca come letta
                            mail.store(email_id, '+FLAGS', '\\Seen')
                    except Exception as e:
                        self.logger.error(f"Errore processamento email {email_id}: {e}")

            mail.close()
            mail.logout()

        except Exception as e:
            self.logger.error(f"Errore connessione IMAP: {e}")

        return articles

    def _process_email(self, mail, email_id) -> Optional[Dict[str, Any]]:
        """Processa singola email"""
        try:
            # Fetch email
            status, msg_data = mail.fetch(email_id, '(RFC822)')
            if status != 'OK':
                return None

            # Parse email
            email_message = self.email_lib.message_from_bytes(msg_data[0][1])

            # Estrai informazioni base
            subject = email_message.get('Subject', '')
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

            # Estrai e verifica link nel contenuto
            links_content = self._extract_and_fetch_links(content)

            self.logger.info(f"Email processata: {subject[:50]}... (Tipo: {content_type})")

            # Per tweet usa l'URL del tweet, per comunicati usa email://
            article_url = source_url if source_url else f"email://{email_id}"

            return {
                'title': subject,
                'content': content,
                'preview': content[:300] + '...' if len(content) > 300 else content,
                'url': article_url,
                'date': self._parse_email_date(date_received),
                'sender': sender,
                'image': image_url,
                'content_type': content_type,  # 'twitter' o 'comunicato'
                'category_override': category,  # Categoria specifica
                'links_content': links_content  # Contenuto dei link estratti
            }

        except Exception as e:
            self.logger.error(f"Errore processing email: {e}")
            return None

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
            # Estrai immagine Twitter e link al tweet usando HTML grezzo
            twitter_image = self._extract_twitter_image(raw_html or content)
            tweet_url = self._extract_tweet_url(raw_html or content)
            return 'twitter', 'Cronaca Social', twitter_image, tweet_url

        # Controlla se è comunicato formale
        is_comunicato = any(indicator in content_lower or indicator in subject_lower
                           for indicator in comunicato_indicators)

        if is_comunicato:
            # Estrai immagine standard, fonte vuota per comunicati
            standard_image = self._extract_first_image(content)
            return 'comunicato', 'Comunicati Stampa', standard_image, None

        # Default: tratta come comunicato generico
        return 'comunicato', 'Comunicati Stampa', self._extract_first_image(content), None

    def _extract_twitter_image(self, content: str) -> Optional[str]:
        """Estrae URL immagini da contenuto Twitter"""
        import re

        # Pattern per link immagini Twitter
        twitter_image_patterns = [
            r'pic\.twitter\.com/\w+',
            r'https://pic\.twitter\.com/\w+',
            r'http://pic\.twitter\.com/\w+',
            r'https://pbs\.twimg\.com/media/[\w-]+\.(?:jpg|jpeg|png|gif)'
        ]

        for pattern in twitter_image_patterns:
            matches = re.findall(pattern, content)
            if matches:
                url = matches[0]
                # Assicurati che abbia https://
                if not url.startswith('http'):
                    url = f'https://{url}'
                return url

        # Fallback: cerca immagini standard
        return self._extract_first_image(content)

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

                    response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
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
                        content = part.get_payload(decode=True).decode('utf-8', errors='replace')
                        # Converti HTML in testo leggibile, preservando il contenuto HTML per estrazione immagini
                        content = self._html_to_text(content)
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
                    content = email_message.get_payload(decode=True).decode('utf-8', errors='replace')
                    content = self._html_to_text(content)
                except (UnicodeDecodeError, AttributeError):
                    content = str(email_message.get_payload(decode=True), errors='replace')
                    content = self._html_to_text(content)
            elif content_type == "text/plain":
                try:
                    content = email_message.get_payload(decode=True).decode('utf-8', errors='replace')
                except (UnicodeDecodeError, AttributeError):
                    content = str(email_message.get_payload(decode=True), errors='replace')

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

            # Pulisci spazi multipli e newline
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()

            # Se il testo è troppo corto o sembra vuoto, prova estrazione alternativa
            if len(text) < 20:
                text = soup.get_text()
                text = re.sub(r'\s+', ' ', text).strip()

            return text

        except Exception as e:
            self.logger.error(f"Errore conversione HTML: {e}")
            # Fallback: restituisci HTML grezzo pulito
            import re
            clean_text = re.sub(r'<[^>]+>', ' ', html_content)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
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
        
        # Headers standard
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
        # Crea scraper appropriato
        self.scraper = self._create_scraper()
    
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
            
            if platform.system() == 'Windows':
                try:
                    msvcrt.locking(self.lock_fd, msvcrt.LK_NBLCK, 1)
                except OSError:
                    os.close(self.lock_fd)
                    self.lock_fd = None
                    raise
            else:
                fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            os.write(self.lock_fd, f"{os.getpid()}\n".encode())
            os.fsync(self.lock_fd)
            
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
                    try:
                        msvcrt.locking(self.lock_fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
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
            new_articles = self.scraper.scrape_articles()
            
            if new_articles:
                self.logger.info(f"Trovati {len(new_articles)} potenziali nuovi articoli")
                
                processed_count = 0
                for article_data in new_articles:
                    article_hash = self.get_article_hash(article_data['title'], article_data['url'])
                    
                    if article_hash not in self.seen_articles:
                        self.process_new_article(article_data)
                        self.seen_articles[article_hash] = datetime.now().isoformat()
                        processed_count += 1
                
                self.logger.info(f"Processati {processed_count} nuovi articoli")
            else:
                self.logger.debug("Nessun nuovo articolo trovato")
                
        except Exception as e:
            self.logger.error(f"Errore nel controllo articoli: {e}")
    
    def should_auto_approve(self, category: str) -> bool:
        """Determina se un articolo deve essere auto-approvato basandosi sulla configurazione"""
        # Solo la configurazione specifica del sito determina l'auto-approvazione
        return self.config.config.get('auto_approve', False)
    
    def process_new_article(self, article_data: Dict[str, Any]):
        """Processa un nuovo articolo"""
        try:
            self.logger.info(f"Processando nuovo articolo: {article_data['title']}")
            
            # Controllo duplicati
            existing = Articolo.objects.filter(fonte=article_data['url']).exists()
            if existing:
                # Articolo già esistente - non logga per evitare spam
                return
            
            # Ottieni contenuto completo se necessario
            if not article_data.get('full_content'):
                full_content = self.scraper.get_full_content(article_data['url'])
                if full_content:
                    article_data['full_content'] = full_content
                else:
                    article_data['full_content'] = article_data['preview']
            
            # Genera articolo con AI se configurato
            if self.config.config.get('use_ai_generation', False):
                result = self.generate_ai_article(article_data)
                self.logger.info(f"Articolo AI generato: {result}")
            else:
                # Salva direttamente senza AI
                self.save_article_directly(article_data)
            
        except Exception as e:
            self.logger.error(f"Errore nel processare articolo: {e}")
    
    def generate_ai_article(self, article_data: Dict[str, Any]) -> str:
        """Genera articolo con AI (da implementare in subclass o config)"""
        # Questa logica può essere personalizzata per sito
        try:
            from anthropic import Anthropic
            
            api_key = self.config.config.get('ai_api_key')
            if not api_key:
                raise ValueError("API key mancante per generazione AI")
            
            client = Anthropic(api_key=api_key)
            
            # Scegli prompt in base al tipo di contenuto
            content_type = article_data.get('content_type', 'comunicato')
            if content_type == 'twitter':
                system_prompt = self.config.config.get('ai_twitter_prompt',
                    self.config.config.get('ai_system_prompt',
                    """Sei un giornalista esperto. Rielabora questa notizia per il giornale locale."""))
            else:
                system_prompt = self.config.config.get('ai_system_prompt',
                    """Sei un giornalista esperto. Rielabora questa notizia per il giornale locale.""")
            
            # Costruisci contenuto con eventuali link
            links_section = ""
            if article_data.get('links_content'):
                links_section = "\n\nContenuto aggiuntivo dai link riferiti:\n"
                for i, link_data in enumerate(article_data['links_content'], 1):
                    links_section += f"\n--- Link {i}: {link_data['url']} ---\n"
                    if link_data.get('title'):
                        links_section += f"Titolo: {link_data['title']}\n"
                    links_section += f"Contenuto: {link_data['content']}\n"

            user_content = f"""
            Fonte: {article_data['url']}
            Titolo originale: {article_data['title']}

            Contenuto principale da rielaborare:
            {article_data['full_content']}
            {links_section}

            Rielabora questa notizia creando un articolo coinvolgente. Se ci sono link con contenuto aggiuntivo, integra le informazioni rilevanti per creare un articolo più completo e informativo.
            """
            
            message = client.messages.create(
                system=system_prompt,
                max_tokens=4096,
                messages=[{"role": "user", "content": user_content}],
                model="claude-sonnet-4-20250514",
            )
            
            articolo_testo = message.content[0].text
            
            # Estrai titolo e contenuto usando il content polisher
            titolo, contenuto = content_polisher.extract_clean_title_from_ai_response(articolo_testo)
            
            # Se l'estrazione fallisce, usa il metodo fallback
            if not titolo:
                titolo = content_polisher.clean_title(article_data['title'])[:200]
            if not contenuto:
                contenuto = content_polisher.clean_content(articolo_testo)
            
            # Applica polishing finale
            polished_data = content_polisher.polish_article({
                'titolo': titolo,
                'contenuto': contenuto
            })
            
            # Salva nel database
            # Usa categoria override se disponibile, altrimenti quella di default
            category = article_data.get('category_override', self.config.category)

            # Determina se deve essere auto-approvato
            auto_approve = self.should_auto_approve(category)

            articolo = Articolo(
                titolo=polished_data['titolo'],
                contenuto=polished_data['contenuto'],
                categoria=category,
                fonte=article_data['url'],
                foto=article_data.get('image_url'),
                approvato=auto_approve,  # Auto-approva se configurato
                data_pubblicazione=timezone.now()
            )
            articolo.save()
            
            return f"Articolo AI salvato con ID: {articolo.id}"
            
        except Exception as e:
            return f"Errore nella generazione AI: {e}"
    
    def save_article_directly(self, article_data: Dict[str, Any]):
        """Salva articolo direttamente senza AI"""
        # Applica polishing anche al salvataggio diretto
        polished_data = content_polisher.polish_article({
            'titolo': article_data['title'],
            'contenuto': article_data['full_content']
        })
        
        # Determina se deve essere auto-approvato
        auto_approve = self.should_auto_approve(self.config.category)
        
        articolo = Articolo(
            titolo=polished_data['titolo'],
            contenuto=polished_data['contenuto'],
            categoria=self.config.category,
            fonte=article_data['url'],
            foto=article_data.get('image_url'),
            approvato=auto_approve,  # Auto-approva se configurato
            data_pubblicazione=timezone.now()
        )
        articolo.save()
        self.logger.info(f"Articolo salvato direttamente con ID: {articolo.id}")
    
    def start_monitoring(self) -> bool:
        """Avvia il monitoraggio"""
        if self.is_running:
            self.logger.warning("Monitor già in esecuzione")
            return False
        
        if not self.acquire_lock():
            self.logger.error("Impossibile avviare monitor: lock non acquisibile")
            return False
        
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info(f"Monitor avviato. Controllo ogni {self.check_interval} secondi")
        return True
    
    def stop_monitoring(self):
        """Ferma il monitoraggio"""
        self.is_running = False
        self.release_lock()
        self.logger.info("Monitor fermato")
    
    def _monitor_loop(self):
        """Loop principale del monitoraggio"""
        try:
            # Controllo iniziale
            try:
                self.logger.info("Controllo iniziale...")
                self.check_for_new_articles()
            except Exception as e:
                self.logger.error(f"Errore nel controllo iniziale: {e}")
            
            # Loop di monitoraggio
            while self.is_running:
                try:
                    self.logger.debug(f"Controllo alle {datetime.now().strftime('%H:%M:%S')}")
                    time.sleep(self.check_interval)
                    if self.is_running:
                        self.check_for_new_articles()
                except Exception as e:
                    self.logger.error(f"Errore nel loop: {e}")
                    time.sleep(60)
                    
        finally:
            self.release_lock()
            self.logger.info("Monitor loop terminato")