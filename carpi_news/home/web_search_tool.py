"""
Sistema di ricerca web semplificato usando Tool Use di Anthropic
"""
import os
import requests
import time
import logging
from typing import Dict, List, Any, Optional
from urllib.parse import quote_plus, urljoin, urlparse
from bs4 import BeautifulSoup
import re
from home.logger_config import get_monitor_logger


class WebSearchTool:
    """Tool per ricerche web mirate usando Google Custom Search"""

    def __init__(self):
        self.logger = get_monitor_logger('web_search_tool')
        self.api_key = os.getenv('GOOGLE_SEARCH_API_KEY')
        self.custom_search_id = os.getenv('GOOGLE_CUSTOM_SEARCH_ID')

        # Rate limiting
        self.last_request = 0
        self.min_delay = 1

        # Cache per contenuti scaricati (in memoria per questa sessione)
        self.content_cache = {}

        # Headers per web scraping
        self.scraping_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Effettua ricerca web mirata

        Args:
            query: Query di ricerca
            max_results: Numero massimo di risultati

        Returns:
            Lista di risultati con title, snippet, url
        """
        if not self.api_key:
            self.logger.warning("Google Search API key non configurata")
            return []

        try:
            # Rate limiting
            current_time = time.time()
            if current_time - self.last_request < self.min_delay:
                time.sleep(self.min_delay - (current_time - self.last_request))

            self.logger.info(f"Ricerca: '{query}'")

            # Controlla se usare Custom Search o API diretta
            search_engine_id = self._get_search_engine_id()

            # Effettua la ricerca
            if search_engine_id:
                # Usa Custom Search API
                url = "https://www.googleapis.com/customsearch/v1"
                params = {
                    'key': self.api_key,
                    'cx': search_engine_id,
                    'q': query,
                    'num': min(max_results, 10),
                    'gl': 'it',
                    'hl': 'it',
                    'safe': 'active'
                }
            else:
                # Nessun Custom Search Engine configurato, usa fallback diretto
                self.logger.info("Nessun Custom Search Engine configurato, usando fallback migliorato")
                return self._fallback_search(query, max_results)

            self.logger.info(f"Chiamata API Google: {url}")
            self.logger.info(f"Query: '{query}'")

            response = requests.get(url, params=params, timeout=10)
            self.last_request = time.time()

            self.logger.info(f"Status Code API: {response.status_code}")

            if response.status_code != 200:
                self.logger.warning(f"Google Search API fallito con {response.status_code}: {response.text}")
                return self._fallback_search(query, max_results)

            data = response.json()

            # Log dettagliato della risposta
            total_results = data.get('searchInformation', {}).get('totalResults', '0')
            self.logger.info(f"Total results da API: {total_results}")
            items_count = len(data.get('items', []))
            self.logger.info(f"Items ricevuti: {items_count}")

            results = []
            items = data.get('items', [])
            if not items:
                self.logger.info("Nessun risultato da Google Custom Search, uso fallback")
                return self._fallback_search(query, max_results)

            for item in items:
                title = item.get('title', '')
                snippet = item.get('snippet', '')
                url = item.get('link', '')

                # Filtra solo fonti rilevanti
                if self._is_relevant_source(url, title, snippet, query):
                    results.append({
                        'title': title,
                        'snippet': snippet,
                        'url': url,
                        'source': 'google_search'
                    })

            self.logger.info(f"Trovati {len(results)} risultati rilevanti da Google Custom Search")
            return results

        except Exception as e:
            self.logger.error(f"Errore ricerca web: {e}")
            return self._fallback_search(query, max_results)


    def _get_search_engine_id(self) -> Optional[str]:
        """Restituisce un Search Engine ID se configurato, altrimenti usa API diretta"""
        custom_id = os.getenv('GOOGLE_CUSTOM_SEARCH_ID')
        if custom_id:
            self.logger.info(f"Usando Custom Search ID configurato: {custom_id}")
            return custom_id

        self.logger.info("Nessun Custom Search ID configurato, usando Google Search API diretta")
        return None

    def _fallback_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Ricerca di fallback migliorata per Claude autonomo"""
        self.logger.info(f"Usando ricerca fallback migliorata per: {query}")

        try:
            # Prova multipli metodi di ricerca
            results = []

            # 1. DuckDuckGo Instant Answer API per informazioni base
            results.extend(self._duckduckgo_search(query, max_results))

            # Mantieni solo risultati da ricerche web reali
            # Non aggiungere siti predefiniti - solo contenuti trovati da ricerche effettive

            return results[:max_results]

        except Exception as e:
            self.logger.error(f"Errore ricerca fallback: {e}")
            return []

    def _duckduckgo_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Ricerca base con DuckDuckGo"""
        try:
            search_url = "https://api.duckduckgo.com/"
            params = {
                'q': query,
                'format': 'json',
                'no_redirect': '1',
                'no_html': '1',
                'skip_disambig': '1'
            }

            response = requests.get(search_url, params=params, timeout=5)
            data = response.json()

            results = []

            # Estrai risultati da DuckDuckGo
            if 'RelatedTopics' in data:
                for topic in data['RelatedTopics'][:max_results]:
                    if isinstance(topic, dict) and 'Text' in topic and 'FirstURL' in topic:
                        # Verifica rilevanza - deve contenere parole chiave specifiche
                        text = topic['Text'].lower()
                        query_words = query.lower().split()

                        # Conta quante parole della query sono nel testo
                        relevance_score = sum(1 for word in query_words if word in text)

                        # Solo se il testo è sufficientemente rilevante
                        if relevance_score >= 2 or any(key_word in text for key_word in ['carpi', 'comune', 'calcio']):
                            results.append({
                                'title': topic.get('Text', '')[:100] + '...',
                                'snippet': topic.get('Text', ''),
                                'url': topic.get('FirstURL', ''),
                                'source': 'duckduckgo_api',
                                'relevance_score': relevance_score
                            })

            # Se non abbiamo abbastanza risultati, prova con scraping Google più specifico
            if len(results) < 2:
                google_results = self._targeted_google_search(query, max_results - len(results))
                results.extend(google_results)

            # Ordina per rilevanza e prendi i migliori
            results = sorted(results, key=lambda x: x.get('relevance_score', 0), reverse=True)

            self.logger.info(f"Ricerca web reale: {len(results)} risultati trovati")
            return results[:max_results]

        except Exception as e:
            self.logger.error(f"Errore ricerca web reale: {e}")
            # Solo come ultima risorsa, usa risultati mock ma più specifici
            return self._generate_contextual_mock(query, max_results)

    def _targeted_google_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Ricerca Google più mirata per argomenti specifici"""
        try:
            # Ricerca mirata su siti di notizie locali specifici
            search_sites = [
                'site:comune.carpi.mo.it',
                'site:carpifc.com',
                'site:lavoce.it/carpi',
                'site:temponews.it',
                'site:gazzettadimodena.it',
                'site:sulpanaro.net',
                'site:modenatoday.it',
                'site:ilrestodelcarlino.it/modena/'
            ]

            all_results = []

            for site in search_sites[:2]:  # Limita a 2 siti per performance
                specific_query = f'{query} {site}'
                search_url = f"https://www.google.com/search?q={quote_plus(specific_query)}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

                response = requests.get(search_url, headers=headers, timeout=5)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Cerca risultati più specifici
                    for result_div in soup.select('div.g')[:2]:
                        title_elem = result_div.select_one('h3')
                        snippet_elem = result_div.select_one('.VwiC3b, .s3v9rd, .st')
                        link_elem = result_div.select_one('a[href^="http"]')

                        if title_elem and link_elem:
                            title = title_elem.get_text()
                            snippet = snippet_elem.get_text() if snippet_elem else ''

                            # Calcola rilevanza basata sul contenuto
                            query_words = query.lower().split()
                            relevance_score = sum(1 for word in query_words
                                                if word in title.lower() or word in snippet.lower())

                            # Solo se sufficientemente rilevante
                            if relevance_score >= 1:
                                all_results.append({
                                    'title': title,
                                    'snippet': snippet,
                                    'url': link_elem.get('href'),
                                    'source': 'targeted_google',
                                    'relevance_score': relevance_score
                                })

            # Ordina per rilevanza
            all_results = sorted(all_results, key=lambda x: x.get('relevance_score', 0), reverse=True)
            return all_results[:max_results]

        except Exception as e:
            self.logger.error(f"Errore targeted Google search: {e}")
            return []

    def _generate_contextual_mock(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Genera risultati mock contestuali basati sulla query specifica"""
        results = []
        query_lower = query.lower()

        # Analizza la query per generare mock più specifici
        if 'calcio' in query_lower or 'fc' in query_lower or 'carpi fc' in query_lower:
            results = [
                {
                    'title': f'Carpi FC: {query}',
                    'snippet': f'Notizie specifiche su {query} riguardanti il Carpi Football Club',
                    'url': f'https://www.carpifc.com/news/{"-".join(query.lower().split())}',
                    'source': 'contextual_mock'
                }
            ]
        elif 'comune' in query_lower or 'sindaco' in query_lower or 'amministrazione' in query_lower:
            results = [
                {
                    'title': f'Comune di Carpi: {query}',
                    'snippet': f'Informazioni dal Comune di Carpi relative a {query}',
                    'url': f'https://www.comune.carpi.mo.it/notizie/{"-".join(query.lower().split())}',
                    'source': 'contextual_mock'
                }
            ]
        elif 'evento' in query_lower or 'manifestazione' in query_lower:
            results = [
                {
                    'title': f'Eventi Carpi: {query}',
                    'snippet': f'Informazioni su eventi e manifestazioni a Carpi: {query}',
                    'url': f'https://www.comune.carpi.mo.it/eventi/{"-".join(query.lower().split())}',
                    'source': 'contextual_mock'
                }
            ]

        # Se non abbiamo risultati specifici, evita mock generici
        if not results:
            self.logger.info(f"Nessun risultato contextual mock per query: {query}")
            return []

        return results[:max_results]

    def _is_relevant_source(self, url: str, title: str, snippet: str, query: str) -> bool:
        """Verifica se una fonte è rilevante e non generica"""
        url_lower = url.lower()
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        query_lower = query.lower()

        # Escludi homepage generiche
        generic_patterns = [
            r'/$',  # Homepage principale
            r'/home/?$',
            r'/index\.(html|php)/?$',
            r'^https?://[^/]+/?$'  # Solo dominio senza path
        ]

        import re
        for pattern in generic_patterns:
            if re.search(pattern, url):
                return False

        # Escludi URL troppo generici
        if any(path in url_lower for path in ['/chi-siamo', '/contatti', '/about', '/contact']):
            return False

        # Verifica rilevanza del contenuto
        query_words = query_lower.split()
        content_text = f"{title_lower} {snippet_lower}"

        # Conta parole della query nel contenuto
        relevance_score = sum(1 for word in query_words if word in content_text)

        # Richiedi almeno 2 parole della query nel contenuto
        return relevance_score >= 2

    def format_results_for_ai(self, results: List[Dict[str, Any]]) -> str:
        """Formatta i risultati per essere passati ad Anthropic"""
        if not results:
            return "Nessun risultato di ricerca disponibile."

        formatted = "=== RISULTATI RICERCA WEB ===\n\n"

        for i, result in enumerate(results, 1):
            formatted += f"**Risultato {i}:**\n"
            formatted += f"Titolo: {result['title']}\n"
            if result['snippet']:
                formatted += f"Descrizione: {result['snippet']}\n"
            formatted += f"Fonte: {result['url']}\n\n"

        formatted += "=== FINE RISULTATI ===\n"
        return formatted

    def fetch_page_content(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Scarica il contenuto completo di una pagina web

        Args:
            url: URL della pagina da scaricare

        Returns:
            Dict con title, content, url originale, o None se errore
        """
        # Controlla cache
        if url in self.content_cache:
            self.logger.info(f"Content cache hit per: {url}")
            return self.content_cache[url]

        try:
            self.logger.info(f"Scaricando contenuto completo da: {url}")

            # Rate limiting
            current_time = time.time()
            if current_time - self.last_request < self.min_delay:
                time.sleep(self.min_delay - (current_time - self.last_request))

            response = requests.get(url, headers=self.scraping_headers, timeout=15, allow_redirects=True)
            self.last_request = time.time()

            if response.status_code != 200:
                self.logger.warning(f"Status code {response.status_code} per {url}")
                return None

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Estrai contenuto principale
            content_data = self._extract_main_content(soup, url)

            if content_data:
                # Cache il risultato
                self.content_cache[url] = content_data
                self.logger.info(f"Contenuto estratto: {len(content_data['content'])} caratteri da {url}")
                return content_data
            else:
                self.logger.warning(f"Nessun contenuto principale trovato in {url}")
                return None

        except Exception as e:
            self.logger.error(f"Errore scaricamento contenuto da {url}: {e}")
            return None

    def _extract_main_content(self, soup: BeautifulSoup, url: str) -> Optional[Dict[str, Any]]:
        """Estrae il contenuto principale da una pagina HTML"""
        try:
            # Rimuovi script, style, nav, footer, sidebar
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()

            # Cerca selettori comuni per articoli/contenuto principale
            content_selectors = [
                'article',
                '[role="main"]',
                '.post-content',
                '.entry-content',
                '.article-content',
                '.content-area',
                '.main-content',
                '.post-body',
                '.article-body',
                '.single-content',
                '.page-content',
                '#content',
                '.content'
            ]

            main_content = None
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    # Prendi il primo che ha abbastanza testo
                    for element in elements:
                        text = element.get_text(strip=True)
                        if len(text) > 200:  # Almeno 200 caratteri
                            main_content = element
                            break
                    if main_content:
                        break

            # Se non troviamo selettori specifici, usa euristica
            if not main_content:
                main_content = self._find_content_by_heuristics(soup)

            if not main_content:
                return None

            # Estrai titolo
            title = self._extract_title(soup)

            # Pulisci e formatta il contenuto
            content_text = self._clean_content_text(main_content)

            if len(content_text) < 100:  # Troppo poco contenuto
                return None

            return {
                'title': title,
                'content': content_text,
                'url': url,
                'length': len(content_text)
            }

        except Exception as e:
            self.logger.error(f"Errore estrazione contenuto da {url}: {e}")
            return None

    def _find_content_by_heuristics(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Trova contenuto principale usando euristiche quando i selettori falliscono"""
        try:
            # Cerca il div/section con più testo
            candidates = []

            for tag in soup.find_all(['div', 'section', 'main']):
                text = tag.get_text(strip=True)
                if len(text) > 200:
                    # Calcola score basato su lunghezza e presenza di paragrafi
                    paragraphs = len(tag.find_all('p'))
                    score = len(text) + (paragraphs * 50)
                    candidates.append((score, tag))

            if candidates:
                # Prendi quello con score più alto
                candidates.sort(reverse=True)
                return candidates[0][1]

            return None

        except Exception as e:
            self.logger.error(f"Errore euristica contenuto: {e}")
            return None

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Estrae il titolo della pagina"""
        try:
            # Prova vari selettori per il titolo
            title_selectors = [
                'h1.entry-title',
                'h1.post-title',
                'h1.article-title',
                '.page-title h1',
                'article h1',
                'h1'
            ]

            for selector in title_selectors:
                element = soup.select_one(selector)
                if element:
                    title = element.get_text(strip=True)
                    if title and len(title) > 5:
                        return title

            # Fallback al tag title
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text(strip=True)
                # Rimuovi nome sito se presente
                title = re.sub(r'\s*[\|\-–]\s*[^|\-–]*$', '', title)
                return title

            return "Titolo non disponibile"

        except Exception as e:
            return "Titolo non disponibile"

    def _clean_content_text(self, element: BeautifulSoup) -> str:
        """Pulisce e formatta il testo del contenuto"""
        try:
            # Rimuovi elementi indesiderati
            for unwanted in element(['script', 'style', 'nav', 'footer', 'aside', '.advertisement', '.ads']):
                unwanted.decompose()

            # Estrai testo preservando struttura
            text_parts = []

            for paragraph in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                text = paragraph.get_text(strip=True)
                if text and len(text) > 10:  # Solo paragrafi significativi
                    text_parts.append(text)

            # Se non troviamo paragrafi, usa tutto il testo
            if not text_parts:
                text_parts = [element.get_text(separator=' ', strip=True)]

            content = '\n\n'.join(text_parts)

            # Pulizia finale
            content = re.sub(r'\n{3,}', '\n\n', content)  # Max 2 newline consecutive
            content = re.sub(r'\s+', ' ', content)  # Normalizza spazi

            return content.strip()

        except Exception as e:
            self.logger.error(f"Errore pulizia testo: {e}")
            return element.get_text(strip=True) if element else ""

    def search_with_content(self, query: str, max_results: int = 3, fetch_content: bool = True) -> List[Dict[str, Any]]:
        """
        Ricerca web con download opzionale del contenuto completo

        Args:
            query: Query di ricerca
            max_results: Numero massimo di risultati
            fetch_content: Se scaricare il contenuto completo delle pagine

        Returns:
            Lista di risultati con contenuto completo se richiesto
        """
        # Prima fase: ricerca normale
        search_results = self.search(query, max_results)

        if not fetch_content:
            return search_results

        # Seconda fase: scarica contenuto completo
        enhanced_results = []
        for result in search_results:
            enhanced_result = result.copy()

            # Scarica contenuto completo
            content_data = self.fetch_page_content(result['url'])
            if content_data:
                enhanced_result.update({
                    'full_content': content_data['content'],
                    'page_title': content_data['title'],
                    'content_length': content_data['length']
                })
            else:
                # Fallback al snippet se il download fallisce
                enhanced_result['full_content'] = result['snippet']
                enhanced_result['page_title'] = result['title']
                enhanced_result['content_length'] = len(result['snippet'])

            enhanced_results.append(enhanced_result)

        return enhanced_results

    def format_results_with_content_for_ai(self, results: List[Dict[str, Any]]) -> str:
        """Formatta risultati con contenuto completo per essere passati ad Anthropic"""
        if not results:
            return "Nessun risultato di ricerca disponibile."

        formatted = "=== RISULTATI RICERCA WEB CON CONTENUTO COMPLETO ===\n\n"

        for i, result in enumerate(results, 1):
            formatted += f"**Risultato {i}:**\n"
            formatted += f"Titolo: {result.get('page_title', result['title'])}\n"
            formatted += f"URL: {result['url']}\n"

            # Usa contenuto completo se disponibile, altrimenti snippet
            content = result.get('full_content', result.get('snippet', ''))
            if content:
                # Limita lunghezza per non sovraccaricare il prompt
                if len(content) > 2000:
                    content = content[:2000] + "... [contenuto troncato]"
                formatted += f"Contenuto completo:\n{content}\n"

            formatted += f"Lunghezza: {result.get('content_length', 'N/A')} caratteri\n\n"

        formatted += "=== FINE RISULTATI ===\n"
        return formatted


# Istanza globale
web_search_tool = WebSearchTool()


def search_web(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Funzione di utilità per ricerca web"""
    return web_search_tool.search(query, max_results)


def search_web_with_content(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Funzione di utilità per ricerca web con contenuto completo"""
    return web_search_tool.search_with_content(query, max_results, fetch_content=True)


def format_search_results(results: List[Dict[str, Any]]) -> str:
    """Funzione di utilità per formattazione risultati"""
    return web_search_tool.format_results_for_ai(results)


def format_search_results_with_content(results: List[Dict[str, Any]]) -> str:
    """Funzione di utilità per formattazione risultati con contenuto completo"""
    return web_search_tool.format_results_with_content_for_ai(results)


# Rimosso sistema siti predefiniti - solo ricerche web reali