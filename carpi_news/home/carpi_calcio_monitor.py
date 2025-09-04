import requests
import time
import threading
import logging
from datetime import datetime
from bs4 import BeautifulSoup
import hashlib
from django.utils import timezone
from urllib.parse import urljoin

from home.models import Articolo
from django.conf import settings

# Configura logging
logger = logging.getLogger(__name__)


class CarpiCalcioMonitor:
    def __init__(self, check_interval=900):
        """
        Monitora specificamente il sito www.carpicalcio.it/news/ per nuove notizie
        
        Args:
            check_interval: Intervallo di controllo in secondi (default: 15 minuti)
        """
        self.base_url = "https://www.carpicalcio.it"
        self.news_url = "https://www.carpicalcio.it/news/"
        self.check_interval = check_interval
        self.is_running = False
        self.monitor_thread = None
        
        # Headers per sembrare un browser normale
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
    
    def scrape_carpi_calcio_news(self):
        """
        Scrape specificamente le notizie di Carpi Calcio
        """
        try:
            logger.info(f"Scraping notizie Carpi Calcio: {self.news_url}")
            
            # Effettua la richiesta
            response = requests.get(self.news_url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Selettori specifici per carpicalcio.it
            news_items = []
            selectors_to_try = [
                '.news-item',           # Possibili selettori
                '.article-preview', 
                '.post',
                'article',
                '.news-card',
                '.content-item',
                'div[class*="news"]',
                'div[class*="article"]'
            ]
            
            # Prova ogni selettore
            for selector in selectors_to_try:
                items = soup.select(selector)
                if items:
                    news_items.extend(items)
            
            # Rimuovi duplicati per URL (più preciso del controllo HTML)
            seen_urls = set()
            unique_items = []
            for item in news_items:
                # Trova il link nell'elemento per usarlo come chiave univoca
                link_elem = item.find('a', href=True)
                if link_elem:
                    url = link_elem.get('href')
                    if url.startswith('/'):
                        url = urljoin(self.base_url, url)
                    
                    if url not in seen_urls:
                        seen_urls.add(url)
                        unique_items.append(item)
            news_items = unique_items
            
            # Se non trova notizie con selettori specifici, cerca contenitori generici
            if not news_items:
                news_items = soup.select('div, article, section')
                # Filtra per contenitori che contengono link e testo
                filtered_items = []
                for item in news_items:
                    links = item.find_all('a', href=True)
                    text = item.get_text(strip=True)
                    if links and len(text) > 50:  # Ha link e contenuto significativo
                        filtered_items.append(item)
                news_items = filtered_items[:20]  # Limita a primi 20
            
            new_articles = []
            
            for item in news_items:
                try:
                    # Cerca link nell'elemento
                    link_elem = item.find('a', href=True)
                    if not link_elem:
                        continue
                    
                    # URL dell'articolo
                    article_url = link_elem.get('href')
                    if article_url.startswith('/'):
                        article_url = urljoin(self.base_url, article_url)
                    elif not article_url.startswith('http'):
                        continue
                    
                    # Estrai titolo - prova diverse strategie
                    title = None
                    
                    # 1. Testo del link
                    if link_elem.get_text(strip=True):
                        title = link_elem.get_text(strip=True)
                    
                    # 2. Title attribute del link
                    elif link_elem.get('title'):
                        title = link_elem.get('title')
                    
                    # 3. Cerca titoli nei children
                    else:
                        title_selectors = ['h1', 'h2', 'h3', 'h4', '.title', '.headline', '.news-title']
                        for selector in title_selectors:
                            title_elem = item.select_one(selector)
                            if title_elem and title_elem.get_text(strip=True):
                                title = title_elem.get_text(strip=True)
                                break
                    
                    if not title:
                        title = f"Notizia Carpi Calcio"
                    
                    # Pulisci il titolo
                    title = title.encode('ascii', 'ignore').decode('ascii').strip()
                    title = title[:200] if len(title) > 200 else title
                    
                    # Estrai preview/contenuto
                    content_preview = item.get_text(strip=True)
                    content_preview = content_preview.encode('ascii', 'ignore').decode('ascii')
                    
                    # Verifica lunghezza minima
                    if len(content_preview) < 30:
                        continue
                    
                    # Aggiungi direttamente alla lista (il controllo duplicati avviene nel database)
                    new_articles.append({
                        'title': title,
                        'url': article_url,
                        'preview': content_preview[:500]  # Primi 500 caratteri
                    })
                    logger.debug(f"Articolo trovato: {title}")
                
                except Exception as e:
                    logger.warning(f"Errore nel processare elemento notizia: {e}")
                    continue
            
            logger.info(f"Trovati {len(new_articles)} articoli Carpi Calcio")
            return new_articles
            
        except Exception as e:
            logger.error(f"Errore nello scraping di Carpi Calcio: {e}")
            return []
    
    def get_full_article_content(self, article_url):
        """
        Scarica il contenuto completo di un articolo
        """
        try:
            response = requests.get(article_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Rimuovi elementi non necessari
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'menu']):
                tag.decompose()
            
            # Cerca contenuto principale
            content_selectors = [
                '.article-content',
                '.post-content', 
                '.content',
                '.entry-content',
                'main',
                'article',
                '.news-body'
            ]
            
            content = ""
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    content = content_elem.get_text(strip=True)
                    break
            
            # Se non trova contenuto specifico, usa tutto il body
            if not content or len(content) < 100:
                body = soup.find('body')
                if body:
                    content = body.get_text(strip=True)
            
            # Pulisci il contenuto
            content = content.encode('ascii', 'ignore').decode('ascii')
            
            return content if len(content) > 100 else None
            
        except Exception as e:
            logger.error(f"Errore nel recuperare contenuto completo da {article_url}: {e}")
            return None
    
    def check_for_new_articles(self):
        """Controlla il sito per nuovi articoli"""
        try:
            articles = self.scrape_carpi_calcio_news()
            
            if articles:
                logger.info(f"Elaborando {len(articles)} articoli...")
                
                for article_data in articles:
                    self.process_new_article(article_data)
            else:
                logger.debug("Nessun articolo trovato")
                
        except Exception as e:
            logger.error(f"Errore nel controllo articoli: {e}")
    
    def process_new_article(self, article_data):
        """Processa un nuovo articolo creando un articolo rielaborato"""
        try:
            logger.info(f"Processando nuovo articolo: {article_data['title']}")
            
            # Controllo duplicati usando il campo fonte (più affidabile)
            existing_by_fonte = Articolo.objects.filter(
                fonte=article_data['url']
            ).exists()
            
            if existing_by_fonte:
                # Articolo già esistente - non logga per evitare spam
                pass
                return
            
            # Scarica contenuto completo
            full_content = self.get_full_article_content(article_data['url'])
            
            if full_content:
                article_data['full_content'] = full_content
            else:
                # Usa la preview se non riesce a scaricare il contenuto completo
                article_data['full_content'] = article_data['preview']
            
            # Genera articolo rielaborato con AI
            result = self.genera_articolo_sportivo(article_data)
            logger.info(f"Articolo sportivo generato: {result}")
            
        except Exception as e:
            logger.error(f"Errore nel processare articolo {article_data['title']}: {e}")
    
    def genera_articolo_sportivo(self, article_data):
        """Genera un articolo sportivo rielaborato usando AI"""
        try:
            from anthropic import Anthropic
            
            client = Anthropic(
                api_key=settings.ANTHROPIC_API_KEY
            )
            
            # Prompt ottimizzato per evitare ripetizioni
            system_prompt = """Sei Gianni Brera giornalista sportivo per "Ombra del Portico". Rielabora la notizia del Carpi Calcio con stile professionale, appassionato e ironico. 
            
            Formato richiesto:
            - Inizia direttamente con un titolo coinvolgente (senza simboli)
            - Scrivi l'articolo in 2-3 paragrafi fluidi
            - Linguaggio coinvolgente per i tifosi locali
            - Focus su Carpi e i suoi giocatori
            - Termina con la fonte tra parentesi"""
            
            user_content = f"""Rielabora questa notizia del Carpi Calcio:

{article_data['full_content']}

Fonte: {article_data['url']}"""
            
            message = client.messages.create(
                system=system_prompt,
                max_tokens=4096,
                messages=[{
                    "role": "user", 
                    "content": user_content
                }],
                model="claude-sonnet-4-20250514",
            )
            
            # Estrai il testo dall'articolo generato
            articolo_testo = message.content[0].text
            logger.info(f"Articolo sportivo rielaborato: {len(articolo_testo)} caratteri")
            
            # Estrai il titolo (prima riga) e contenuto (resto)
            linee = articolo_testo.split('\n', 1)
            if len(linee) >= 2:
                titolo = linee[0].replace('#', '').replace('*', '').strip()[:200]
                contenuto = linee[1].strip()  # Solo il contenuto senza il titolo
            else:
                titolo = article_data['title'][:200]
                contenuto = articolo_testo
            
            # Salva nel database
            articolo = Articolo(
                titolo=titolo,
                contenuto=contenuto,
                categoria="Sport",
                fonte=article_data['url'],  # Salva URL di origine
                approvato=False,  # Richiede approvazione manuale
                data_pubblicazione=timezone.now()
            )
            articolo.save()
            
            # La notifica email viene inviata automaticamente tramite il segnale post_save
            return f"Articolo sportivo salvato con ID: {articolo.id}"
            
        except Exception as e:
            return f"Errore nella generazione dell'articolo sportivo: {e}"
    
    def start_monitoring(self):
        """Avvia il monitoraggio in un thread separato"""
        if self.is_running:
            logger.warning("Il monitor Carpi Calcio è già in esecuzione")
            return
        
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"Monitor Carpi Calcio avviato. Controllo ogni {self.check_interval} secondi")
    
    def stop_monitoring(self):
        """Ferma il monitoraggio"""
        self.is_running = False
        logger.info("Monitor Carpi Calcio fermato")
    
    def _monitor_loop(self):
        """Loop principale del monitoraggio"""
        # Controllo iniziale
        try:
            logger.info("Controllo iniziale Carpi Calcio...")
            self.check_for_new_articles()
        except Exception as e:
            logger.error(f"Errore nel controllo iniziale: {e}")
        
        # Loop di monitoraggio
        while self.is_running:
            try:
                logger.debug(f"Controllo Carpi Calcio alle {datetime.now().strftime('%H:%M:%S')}")
                time.sleep(self.check_interval)
                if self.is_running:  # Controlla se è ancora attivo dopo il sleep
                    self.check_for_new_articles()
            except Exception as e:
                logger.error(f"Errore nel loop di monitoraggio Carpi Calcio: {e}")
                time.sleep(60)  # Attendi un minuto prima di riprovare


def start_carpi_calcio_monitor(check_interval=900):
    """
    Funzione di utilità per avviare il monitor Carpi Calcio
    
    Args:
        check_interval: Intervallo di controllo in secondi (default: 15 minuti)
    """
    monitor = CarpiCalcioMonitor(check_interval)
    monitor.start_monitoring()
    return monitor


# Esempio di utilizzo
if __name__ == "__main__":
    monitor = start_carpi_calcio_monitor(600)  # 10 minuti
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop_monitoring()
        logger.info("Monitor Carpi Calcio fermato dall'utente")