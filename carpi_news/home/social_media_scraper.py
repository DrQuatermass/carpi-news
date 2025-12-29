"""
Social Media Profile Scraper
Estrae informazioni pubbliche da profili social (Instagram, Facebook, LinkedIn)
usando API ufficiali o scraping etico quando le API non sono disponibili
"""

import logging
import requests
import re
from typing import Dict, Optional
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)


class SocialMediaScraper:
    """
    Scraper per profili social che rispetta i TOS delle piattaforme
    Usa API ufficiali quando disponibili, altrimenti estrae solo metadati pubblici
    """

    def __init__(self):
        # API keys (opzionali, se non presenti usa scraping metadati)
        self.instagram_token = getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', None)
        self.facebook_token = getattr(settings, 'FACEBOOK_ACCESS_TOKEN', None)
        self.linkedin_token = getattr(settings, 'LINKEDIN_ACCESS_TOKEN', None)

    def extract_profile_info(self, url: str) -> Dict[str, str]:
        """
        Estrae informazioni da un profilo social

        Args:
            url: URL del profilo social

        Returns:
            Dict con informazioni estratte:
            {
                'platform': 'instagram'/'facebook'/'linkedin',
                'username': 'nome_utente',
                'name': 'Nome Completo',
                'bio': 'Biografia',
                'website': 'sito web linkato',
                'followers': 'numero followers',
                'verified': True/False,
                'category': 'categoria account'
            }
        """
        url_lower = url.lower()

        if 'instagram.com' in url_lower:
            return self._extract_instagram_info(url)
        elif 'facebook.com' in url_lower or 'fb.com' in url_lower:
            return self._extract_facebook_info(url)
        elif 'linkedin.com' in url_lower:
            return self._extract_linkedin_info(url)
        else:
            logger.warning(f"Piattaforma non supportata: {url}")
            return {'platform': 'unknown', 'error': 'Piattaforma non supportata'}

    def _extract_instagram_info(self, url: str) -> Dict[str, str]:
        """
        Estrae info da profilo Instagram

        Metodi (in ordine di priorità):
        1. Instagram Basic Display API (se token disponibile)
        2. Scraping metadati pubblici dalla pagina (fallback etico)
        """
        username = self._extract_instagram_username(url)

        if not username:
            return {'platform': 'instagram', 'error': 'Username non trovato nell\'URL'}

        # Metodo 1: API ufficiale (se disponibile)
        if self.instagram_token:
            logger.info(f"Usando Instagram API per @{username}")
            return self._instagram_api_method(username)

        # Metodo 2: Scraping metadati pubblici (fallback)
        logger.info(f"Instagram API non configurata, estraggo solo metadati pubblici per @{username}")
        return self._instagram_metadata_scraping(url, username)

    def _extract_instagram_username(self, url: str) -> Optional[str]:
        """Estrae username da URL Instagram"""
        # Formati supportati:
        # https://www.instagram.com/username/
        # https://instagram.com/username
        # https://www.instagram.com/username?param=value
        match = re.search(r'instagram\.com/([a-zA-Z0-9_.]+)', url)
        if match:
            username = match.group(1)
            # Rimuovi trailing slash o parametri
            username = username.rstrip('/').split('?')[0]
            return username
        return None

    def _instagram_metadata_scraping(self, url: str, username: str) -> Dict[str, str]:
        """
        Scraping etico di metadati pubblici Instagram
        Estrae solo informazioni dai meta tag Open Graph (dati pubblici)
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Estrai metadati Open Graph (sempre pubblici)
            og_data = {}
            for meta in soup.find_all('meta', property=re.compile(r'^og:')):
                property_name = meta.get('property', '').replace('og:', '')
                og_data[property_name] = meta.get('content', '')

            # Estrai meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            description = meta_desc.get('content', '') if meta_desc else ''

            # Estrai titolo
            title = soup.find('title')
            title_text = title.get_text().strip() if title else ''

            # Parse description per estrarre follower count (se presente)
            # Formato tipico: "123K Followers, 456 Following, 789 Posts - See Instagram photos..."
            followers = None
            if description:
                followers_match = re.search(r'([\d.]+[KMB]?)\s+Followers', description, re.IGNORECASE)
                if followers_match:
                    followers = followers_match.group(1)

            # Estrai nome dal title (formato: "Nome (@username) • Instagram photos and videos")
            name = None
            if title_text:
                name_match = re.search(r'^(.+?)\s*\(@', title_text)
                if name_match:
                    name = name_match.group(1).strip()

            result = {
                'platform': 'instagram',
                'username': username,
                'name': name or og_data.get('title', ''),
                'bio': description or og_data.get('description', ''),
                'image': og_data.get('image', ''),
                'url': url,
                'followers': followers,
                'method': 'metadata_scraping'
            }

            logger.info(f"Estratti metadati pubblici per @{username}: {result.get('name', 'N/A')}")
            return result

        except requests.RequestException as e:
            logger.error(f"Errore connessione Instagram per {username}: {e}")
            return {
                'platform': 'instagram',
                'username': username,
                'url': url,
                'error': f'Errore connessione: {str(e)}',
                'method': 'failed'
            }
        except Exception as e:
            logger.error(f"Errore parsing metadati Instagram per {username}: {e}")
            return {
                'platform': 'instagram',
                'username': username,
                'url': url,
                'error': f'Errore parsing: {str(e)}',
                'method': 'failed'
            }

    def _instagram_api_method(self, username: str) -> Dict[str, str]:
        """
        Usa Instagram Basic Display API per estrarre informazioni
        Richiede access token configurato
        """
        # Placeholder per futura implementazione con API ufficiale
        # Instagram Basic Display API richiede OAuth flow complesso
        logger.warning("Instagram API method non ancora implementato - usa metadata scraping")
        return {
            'platform': 'instagram',
            'username': username,
            'error': 'API method non implementato',
            'method': 'api_not_implemented'
        }

    def _extract_facebook_info(self, url: str) -> Dict[str, str]:
        """
        Estrae info da pagina Facebook
        Usa solo metadati pubblici Open Graph
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Estrai Open Graph data
            og_data = {}
            for meta in soup.find_all('meta', property=re.compile(r'^og:')):
                property_name = meta.get('property', '').replace('og:', '')
                og_data[property_name] = meta.get('content', '')

            return {
                'platform': 'facebook',
                'name': og_data.get('title', ''),
                'bio': og_data.get('description', ''),
                'url': og_data.get('url', url),
                'image': og_data.get('image', ''),
                'method': 'metadata_scraping'
            }

        except Exception as e:
            logger.error(f"Errore estrazione Facebook: {e}")
            return {
                'platform': 'facebook',
                'url': url,
                'error': str(e),
                'method': 'failed'
            }

    def _extract_linkedin_info(self, url: str) -> Dict[str, str]:
        """
        Estrae info da profilo LinkedIn
        LinkedIn ha protezioni anti-scraping molto forti
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')

            # LinkedIn fornisce pochi metadati pubblici senza login
            title = soup.find('title')
            title_text = title.get_text().strip() if title else ''

            return {
                'platform': 'linkedin',
                'name': title_text.replace(' | LinkedIn', ''),
                'url': url,
                'method': 'metadata_scraping',
                'note': 'LinkedIn richiede login per dettagli completi'
            }

        except Exception as e:
            logger.error(f"Errore estrazione LinkedIn: {e}")
            return {
                'platform': 'linkedin',
                'url': url,
                'error': str(e),
                'method': 'failed'
            }

    def format_for_article_context(self, profile_data: Dict[str, str]) -> str:
        """
        Formatta le informazioni estratte in testo leggibile per l'AI

        Args:
            profile_data: Dati estratti dal profilo

        Returns:
            Stringa formattata con le informazioni
        """
        if profile_data.get('error'):
            return f"Profilo {profile_data.get('platform', 'social')}: {profile_data.get('url', '')} (informazioni non disponibili)"

        lines = [f"=== PROFILO {profile_data.get('platform', 'SOCIAL').upper()} ==="]

        if profile_data.get('name'):
            lines.append(f"Nome: {profile_data['name']}")

        if profile_data.get('username'):
            lines.append(f"Username: @{profile_data['username']}")

        if profile_data.get('bio'):
            lines.append(f"Bio: {profile_data['bio']}")

        if profile_data.get('followers'):
            lines.append(f"Followers: {profile_data['followers']}")

        if profile_data.get('website'):
            lines.append(f"Sito web linkato: {profile_data['website']}")

        if profile_data.get('category'):
            lines.append(f"Categoria: {profile_data['category']}")

        lines.append(f"URL: {profile_data.get('url', '')}")

        return '\n'.join(lines)
