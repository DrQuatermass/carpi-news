from django.core.management.base import BaseCommand
from django.db import models
from django.core.cache import cache
from home.models import Articolo
import requests
import logging
from bs4 import BeautifulSoup
import urllib.parse
from home.monitor_configs import get_config
from home.universal_news_monitor import UniversalNewsMonitor


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Corregge le immagini non funzionanti degli articoli esistenti'

    def add_arguments(self, parser):
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='Solo controlla le immagini senza modificare nulla',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=5,
            help='Timeout in secondi per verificare le immagini (default: 5)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limita il numero di articoli da processare',
        )
        parser.add_argument(
            '--category',
            type=str,
            help='Filtra per categoria specifica',
        )
        parser.add_argument(
            '--article-id',
            type=int,
            help='Processa solo un articolo specifico (per test)',
        )

    def handle(self, *args, **options):
        # Filtri opzionali
        queryset = Articolo.objects.exclude(
            models.Q(foto__isnull=True) | models.Q(foto='') | models.Q(foto__exact='')
        )
        
        if options['article_id']:
            queryset = queryset.filter(id=options['article_id'])
            self.stdout.write(f"Processando solo articolo ID: {options['article_id']}")
        elif options['category']:
            queryset = queryset.filter(categoria=options['category'])
            self.stdout.write(f"Filtrando per categoria: {options['category']}")
        
        # Ordina prima del limit (solo se non è un articolo specifico)
        if not options['article_id']:
            queryset = queryset.order_by('-data_pubblicazione')
            
            if options['limit']:
                queryset = queryset[:options['limit']]
                self.stdout.write(f"Limitando a {options['limit']} articoli")
        
        total_count = queryset.count()
        if total_count == 0:
            self.stdout.write(self.style.SUCCESS('Nessun articolo con immagine trovato.'))
            return

        self.stdout.write(f'Controllo immagini per {total_count} articoli...')
        self.stdout.write(f'Timeout per ogni immagine: {options["timeout"]} secondi')
        
        if options['check_only']:
            self.stdout.write(self.style.WARNING('MODALITÀ SOLO CONTROLLO - Nessuna modifica verrà effettuata'))
        
        self.stdout.write('')
        
        broken_images = []
        working_images = []
        timeout_errors = []
        no_source_articles = []
        processed = 0
        
        for articolo in queryset:
            processed += 1
            foto_url = articolo.foto
            
            # Mostra progresso ogni 10 articoli
            if processed % 10 == 0:
                self.stdout.write(f'Processati {processed}/{total_count} articoli...')
            
            # Controlla se l'immagine è raggiungibile
            is_working = self._check_image_url(foto_url, options['timeout'])
            
            if is_working is None:
                # Timeout o errore di connessione
                timeout_errors.append({
                    'articolo': articolo,
                    'url': foto_url
                })
                self.stdout.write(
                    f'[TIMEOUT] {articolo.titolo[:40]}... - {foto_url[:60]}...'
                )
                
            elif is_working:
                # Immagine funzionante
                working_images.append(articolo)
                if processed <= 5:  # Mostra solo i primi 5 per non intasare
                    self.stdout.write(
                        f'[OK] {articolo.titolo[:40]}... - Immagine OK'
                    )
                    
            else:
                # Immagine non funzionante - controlla se ha fonte per recuperare
                if not articolo.fonte:
                    no_source_articles.append({
                        'articolo': articolo,
                        'url': foto_url
                    })
                    self.stdout.write(
                        f'[NO_SOURCE] {articolo.titolo[:40]}... - Nessuna fonte per recupero'
                    )
                else:
                    broken_images.append({
                        'articolo': articolo,
                        'url': foto_url
                    })
                    self.stdout.write(
                        f'[BROKEN] {articolo.titolo[:40]}... - {foto_url[:60]}...'
                    )
        
        # Statistiche finali
        self.stdout.write('')
        self.stdout.write('=== RISULTATI ===')
        self.stdout.write(f'Totale articoli processati: {processed}')
        self.stdout.write(f'Immagini funzionanti: {len(working_images)}')
        self.stdout.write(f'Immagini non funzionanti: {len(broken_images)}')
        self.stdout.write(f'Articoli senza fonte: {len(no_source_articles)}')
        self.stdout.write(f'Errori/timeout: {len(timeout_errors)}')
        
        # Se non è solo controllo, tenta di recuperare le immagini dalla fonte
        if not options['check_only'] and broken_images:
            self.stdout.write('')
            self.stdout.write(f'Tentativo di recupero di {len(broken_images)} immagini dalla fonte originale...')
            
            # URL del logo di fallback (stesso del metodo get_image_url del model)
            from django.templatetags.static import static
            fallback_url = static('home/images/portico_logo_nopayoff.svg')
            
            recovered_count = 0
            fallback_count = 0
            
            for item in broken_images:
                articolo = item['articolo']
                old_url = item['url']
                
                # Tenta di recuperare l'immagine dalla fonte
                self.stdout.write(f'  Tentando recupero da: {articolo.fonte}')
                new_image_url = self._recover_image_from_source(articolo, options['timeout'])
                
                if new_image_url and new_image_url != old_url:
                    self.stdout.write(f'  Nuova immagine trovata: {new_image_url[:80]}...')
                    
                    # Verifica che la nuova immagine funzioni - ma sii più permissivo
                    image_check = self._check_image_url(new_image_url, options['timeout'])
                    
                    # Se la verifica fallisce ma l'URL sembra valido, prova comunque
                    if image_check or (new_image_url.startswith('http') and not new_image_url.endswith('.svg')):
                        if not image_check:
                            self.stdout.write(f'  Verifica immagine fallita, ma URL sembra valido - proseguo')
                        
                        articolo.foto = new_image_url
                        articolo.save()
                        recovered_count += 1
                        self.stdout.write(
                            f'[RECOVERED] {articolo.titolo[:40]}... - Nuova immagine recuperata dalla fonte'
                        )
                        continue
                    else:
                        self.stdout.write(f'  Immagine trovata ma non funziona: {new_image_url[:80]}...')
                else:
                    if new_image_url:
                        self.stdout.write(f'  URL stesso dell\'immagine rotta')
                    else:
                        self.stdout.write(f'  Nessuna immagine trovata nella fonte')
                
                # Se non è riuscito a recuperare, usa il fallback
                articolo.foto = fallback_url
                articolo.save()
                fallback_count += 1
                self.stdout.write(
                    f'[FALLBACK] {articolo.titolo[:40]}... - Usato logo come fallback'
                )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nCompletato! Recuperate {recovered_count} immagini, '
                    f'{fallback_count} sostituite con logo.'
                )
            )
        elif options['check_only'] and broken_images:
            self.stdout.write('')
            self.stdout.write('Immagini che verrebbero corrette:')
            for item in broken_images[:10]:  # Mostra solo le prime 10
                self.stdout.write(f'  - {item["articolo"].titolo[:50]}...')
            if len(broken_images) > 10:
                self.stdout.write(f'  ... e altre {len(broken_images) - 10}')
                
            self.stdout.write(
                self.style.WARNING(
                    f'\nEsegui senza --check-only per correggere {len(broken_images)} immagini.'
                )
            )

    def _check_image_url(self, url, timeout=5):
        """
        Controlla se un URL di immagine è raggiungibile
        Returns: True se OK, False se broken, None se timeout/errore
        """
        if not url:
            return False
            
        # Controlla cache prima
        cache_key = f"image_check_{hash(url)}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            is_working = response.status_code == 200
            
            # Cache il risultato per 10 minuti
            cache.set(cache_key, is_working, 600)
            return is_working
            
        except requests.exceptions.Timeout:
            # Timeout specifico
            return None
        except requests.exceptions.RequestException:
            # Altri errori di connessione
            cache.set(cache_key, False, 300)  # Cache errori per 5 min
            return False
        except Exception as e:
            # Errori generici
            logger.warning(f"Errore nel controllo URL {url}: {e}")
            return None

    def _recover_image_from_source(self, articolo, timeout=10):
        """
        Tenta di recuperare l'immagine corretta dalla fonte originale dell'articolo
        """
        if not articolo.fonte:
            return None
            
        try:
            # Headers per sembrare un browser normale
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            
            response = requests.get(articolo.fonte, headers=headers, timeout=timeout, allow_redirects=True)
            
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Utilizza il metodo unificato che usa le configurazioni dei monitor esistenti
            return self._extract_image_with_monitor(articolo, soup, articolo.fonte)
                
        except Exception as e:
            logger.warning(f"Errore nel recupero immagine da {articolo.fonte}: {e}")
            return None

    def _extract_image_with_monitor(self, articolo, soup, base_url):
        """
        Utilizza i monitor esistenti per estrarre l'immagine in modo più aggressivo
        """
        try:
            # Lista di tutte le immagini trovate con diversi metodi
            candidate_images = []
            
            # Determina quale configurazione utilizzare in base alla fonte
            fonte_url = articolo.fonte.lower()
            config_name = None
            
            if 'voce.it' in fonte_url:
                config_name = 'voce_carpi'
            elif 'carpi-calcio.it' in fonte_url or 'carpicalcio.it' in fonte_url:
                config_name = 'carpi_calcio'
            elif 'comune.carpi.mo.it' in fonte_url:
                config_name = 'comune_carpi_graphql'
            elif 'temponews.it' in fonte_url:
                config_name = 'temponews'
            elif 'ansa.it' in fonte_url:
                config_name = 'ansa_carpi'
            
            # METODO 1: Usa configurazione specifica del monitor
            if config_name:
                try:
                    config = get_config(config_name)
                    content_selectors = config.config.get('content_selectors', [])
                    
                    # Cerca nel contenuto principale
                    for selector in content_selectors:
                        content_elem = soup.select_one(selector)
                        if content_elem:
                            for img in content_elem.find_all('img'):
                                extracted_url = self._extract_image_using_monitor_logic(img, base_url)
                                if extracted_url:
                                    candidate_images.append(('monitor_content', extracted_url))
                            break  # Usa solo il primo contenuto trovato
                            
                except Exception as e:
                    logger.debug(f"Errore configurazione monitor {config_name}: {e}")
            
            # METODO 2: Meta tag Open Graph e Twitter (priorità alta)
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                candidate_images.append(('og_image', og_image.get('content')))
                
            twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                candidate_images.append(('twitter_image', twitter_image.get('content')))
            
            # METODO 3: Selettori specifici per sito
            site_specific_selectors = self._get_site_specific_selectors(fonte_url)
            for selector_name, selector in site_specific_selectors:
                for elem in soup.select(selector):
                    if elem.name == 'img':
                        extracted_url = self._extract_image_using_monitor_logic(elem, base_url)
                        if extracted_url:
                            candidate_images.append((f'site_specific_{selector_name}', extracted_url))
                    else:
                        # Cerca img dentro l'elemento
                        for img in elem.find_all('img'):
                            extracted_url = self._extract_image_using_monitor_logic(img, base_url)
                            if extracted_url:
                                candidate_images.append((f'site_specific_{selector_name}_img', extracted_url))
            
            # METODO 4: Ricerca generale più aggressiva
            general_selectors = [
                ('featured', '.featured-image img, .post-thumbnail img, .wp-post-image','slide'),
                ('article_img', 'article img:first-of-type, .article img:first-of-type','slide'),
                ('content_img', '.content img:first-of-type, .post-content img:first-of-type, .entry-content img:first-of-type','slide'),
                ('main_img', 'main img:first-of-type','slide'),
                ('large_img', 'img[width="300"], img[width="400"], img[width="500"]','slide'),  # Immagini probabilmente grandi
            ]
            
            for selector_name, selector in general_selectors:
                for img in soup.select(selector):
                    extracted_url = self._extract_image_using_monitor_logic(img, base_url)
                    if extracted_url:
                        candidate_images.append((f'general_{selector_name}', extracted_url))
            
            # METODO 5: Tutte le immagini come ultimo resort
            all_images = soup.find_all('img')
            for img in all_images[:10]:  # Limita ai primi 10 per performance
                extracted_url = self._extract_image_using_monitor_logic(img, base_url)
                if extracted_url:
                    candidate_images.append(('all_images', extracted_url))
            
            # Priorità: 1) monitor_content, 2) og_image/twitter, 3) site_specific, 4) general, 5) all_images
            priority_order = ['monitor_content', 'og_image', 'twitter_image', 'site_specific', 'general', 'all_images']
            
            for priority in priority_order:
                for method, url in candidate_images:
                    if method.startswith(priority):
                        logger.info(f"Immagine trovata con metodo {method}: {url[:60]}...")
                        return url
            
            # Se nessuna immagine trovata
            logger.warning(f"Nessuna immagine trovata per {articolo.fonte}")
            return None
            
        except Exception as e:
            logger.error(f"Errore critico nell'estrazione immagine: {e}")
            return None

    def _extract_image_generic(self, soup, base_url):
        """Estrazione generica per siti sconosciuti"""
        # Meta tag Open Graph
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return og_image.get('content')
            
        # Meta tag Twitter
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            return twitter_image.get('content')
            
        # Prima immagine significativa nell'articolo usando UniversalNewsMonitor
        try:
            # Usa il monitor generico per l'estrazione
            from home.monitor_configs import GENERIC_HTML_CONFIG
            monitor = UniversalNewsMonitor(GENERIC_HTML_CONFIG)
            
            all_images = soup.find_all('img')
            for img in all_images:
                extracted_url = monitor._extract_image_from_html_elem(img)
                if extracted_url:
                    # Converti URL relativo in assoluto se necessario
                    if extracted_url.startswith('/'):
                        return urllib.parse.urljoin(base_url, extracted_url)
                    elif extracted_url.startswith('http'):
                        return extracted_url
                        
        except Exception as e:
            logger.warning(f"Errore nell'estrazione generica: {e}")
            
        return None

    def _extract_image_using_monitor_logic(self, img_elem, base_url):
        """
        Replica la logica di estrazione immagini dal UniversalNewsMonitor
        """
        if not img_elem:
            return None
            
        # Prende URL dell'immagine (priorità a data-src per lazy loading)
        img_src = (img_elem.get('data-src') or 
                  img_elem.get('data-lazy-src') or 
                  img_elem.get('src'))
        
        if not img_src or img_src.startswith('data:'):
            return None
        
        # Filtra immagini piccole (probabilmente icone/loghi)
        try:
            width = int(img_elem.get('width', '0'))
            height = int(img_elem.get('height', '0'))
            if width > 0 and height > 0 and (width < 80 or height < 60):
                return None
        except (ValueError, TypeError):
            pass
        
        # Filtra loghi e icone comuni
        if any(term in img_src.lower() for term in ['logo', 'icon', 'avatar', 'social', 'placeholder']):
            return None
        
        # Fix per URL con spazi (specifico per La Voce di Carpi)
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
        
        # Converte URL relativo in assoluto
        if img_src.startswith('/'):
            return urllib.parse.urljoin(base_url, img_src)
        elif img_src.startswith('http'):
            return img_src
        
        return None

    def _get_site_specific_selectors(self, fonte_url):
        """Restituisce selettori specifici per ogni sito"""
        if 'voce.it' in fonte_url:
            return [
                ('main_image', '.art-text img:first-of-type'),
                ('article_image', '.articolo-testo img:first-of-type'),
                ('responsive_image', 'img.img-responsive'),
                ('upload_image', 'img[src*="upload"]'),
                ('content_image', '[itemprop="articleBody"] img:first-of-type'),
            ]
        elif 'carpi-calcio.it' in fonte_url or 'carpicalcio.it' in fonte_url:
            return [
                ('featured_image', '.featured-image img, .post-thumbnail img'),
                ('wp_content', 'img[src*="wp-content"]'),
                ('article_content', '.article-content img:first-of-type'),
                ('post_content', '.post-content img:first-of-type'),
                ('wp_post_image', '.wp-post-image'),
            ]
        elif 'comune.carpi.mo.it' in fonte_url:
            return [
                ('field_image', '.field-name-field-immagine img'),
                ('node_image', '.node-article img:first-of-type'),
                ('sites_files', 'img[src*="sites/default/files"]'),
                ('content_image', '.content img:first-of-type'),
            ]
        elif 'temponews.it' in fonte_url:
            return [
                ('td_image', '.td-image-wrap img'),
                ('post_featured', '.post-featured-image img'),
                ('entry_content', '.entry-content img:first-of-type'),
                ('td_post_content', '.td-post-content img:first-of-type'),
                ('wp_post_image', '.wp-post-image'),
            ]
        elif 'ansa.it' in fonte_url:
            return [
                ('news_txt', '.news-txt img:first-of-type'),
                ('story_text', '.story-text img:first-of-type'),
                ('in_article', '#inArticle img:first-of-type'),
                ('ansa_story', '.story img:first-of-type'),
            ]
        else:
            # Selettori generici
            return [
                ('generic_featured', '.featured img, .featured-image img'),
                ('generic_article', 'article img:first-of-type'),
                ('generic_content', '.content img:first-of-type, .post-content img:first-of-type'),
            ]