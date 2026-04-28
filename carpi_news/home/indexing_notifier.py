"""
Sistema di notifica ibrido per indicizzazione articoli.
Combina Google Indexing API e IndexNow per massima copertura.
"""
import os
import json
import logging
import requests
from typing import Optional, Dict, Any
from datetime import datetime
from google.oauth2 import service_account
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)


class IndexingNotifier:
    """Gestisce notifiche di indicizzazione verso Google e altri motori di ricerca."""

    def __init__(self):
        self.site_url = os.getenv('SITE_URL', 'https://ombradelportico.it')
        self.indexnow_key = os.getenv('INDEXNOW_KEY')
        self.google_credentials_path = os.getenv('GOOGLE_INDEXING_CREDENTIALS')

    def notify_article_published(self, article_url: str) -> Dict[str, Any]:
        """
        Notifica la pubblicazione di un articolo a tutti i motori di ricerca.

        Args:
            article_url: URL completo dell'articolo

        Returns:
            Dict con risultati delle notifiche
        """
        results = {
            'indexnow': {'success': False, 'message': ''},
            'google': {'success': False, 'message': ''}
        }

        # IndexNow (Google, Bing, Yandex)
        if self.indexnow_key:
            try:
                results['indexnow'] = self._notify_indexnow(article_url)
            except Exception as e:
                logger.error(f"Errore IndexNow: {e}")
                results['indexnow']['message'] = str(e)
        else:
            results['indexnow']['message'] = 'INDEXNOW_KEY non configurata'

        # Google Indexing API - DISABILITATA per contenuti news
        # Documentazione ufficiale Google (sett 2025): API supporta SOLO JobPosting e BroadcastEvent
        # Per news usare: IndexNow (già attivo), Google News Sitemap, NewsArticle schema markup
        # Fonte: https://developers.google.com/search/apis/indexing-api/v3/quota-pricing
        results['google']['message'] = 'API non supportata per news (solo JobPosting/BroadcastEvent) - usa IndexNow'
        results['google']['success'] = False

        # Codice disabilitato per evitare penalizzazioni:
        # if self.google_credentials_path and os.path.exists(self.google_credentials_path):
        #     try:
        #         results['google'] = self._notify_google_indexing_api(article_url)
        #     except Exception as e:
        #         logger.error(f"Errore Google Indexing API: {e}")
        #         results['google']['message'] = str(e)
        # else:
        #     results['google']['message'] = 'Credentials Google non configurate'

        # Log risultati
        success_count = sum(1 for r in results.values() if r['success'])
        logger.info(f"Notifica indicizzazione per {article_url}: {success_count}/2 successi")

        return results

    def _notify_indexnow(self, url: str) -> Dict[str, Any]:
        """
        Notifica IndexNow tramite Yandex (condiviso con Bing e altri motori).
        Yandex endpoint funziona senza pre-verifica, Bing richiede Webmaster Tools.
        Docs: https://www.indexnow.org/documentation
        """
        # Usa Yandex come endpoint primario (funziona senza verifica preventiva)
        # Le notifiche vengono condivise con tutti i motori IndexNow (Bing, etc)
        endpoint = "https://yandex.com/indexnow"

        payload = {
            "host": self.site_url.replace('https://', '').replace('http://', ''),
            "key": self.indexnow_key,
            "keyLocation": f"{self.site_url}/{self.indexnow_key}.txt",
            "urlList": [url]
        }

        response = requests.post(
            endpoint,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        if response.status_code in [200, 202]:
            logger.info(f"IndexNow: URL {url} notificato con successo via Yandex")
            return {'success': True, 'message': 'Notificato a IndexNow (Yandex, Bing, altri motori)'}
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            logger.warning(f"IndexNow fallito: {error_msg}")
            return {'success': False, 'message': error_msg}

    def _notify_google_indexing_api(self, url: str, action: str = 'URL_UPDATED') -> Dict[str, Any]:
        """
        Notifica Google Indexing API.
        Docs: https://developers.google.com/search/apis/indexing-api/v3/quickstart

        Args:
            url: URL da notificare
            action: 'URL_UPDATED' o 'URL_DELETED'
        """
        # Carica credenziali service account
        credentials = service_account.Credentials.from_service_account_file(
            self.google_credentials_path,
            scopes=['https://www.googleapis.com/auth/indexing']
        )

        # Refresh token se necessario
        if not credentials.valid:
            credentials.refresh(Request())

        # Endpoint API
        endpoint = 'https://indexing.googleapis.com/v3/urlNotifications:publish'

        # Payload
        payload = {
            'url': url,
            'type': action
        }

        # Richiesta
        response = requests.post(
            endpoint,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {credentials.token}'
            },
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            logger.info(f"Google Indexing API: URL {url} notificato con successo")
            return {'success': True, 'message': 'Notificato a Google Indexing API'}
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            logger.warning(f"Google Indexing API fallito: {error_msg}")
            return {'success': False, 'message': error_msg}

    def notify_article_deleted(self, article_url: str) -> Dict[str, Any]:
        """Notifica la rimozione di un articolo (solo Google Indexing API supporta rimozioni)."""
        results = {
            'google': {'success': False, 'message': ''}
        }

        if self.google_credentials_path and os.path.exists(self.google_credentials_path):
            try:
                results['google'] = self._notify_google_indexing_api(article_url, action='URL_DELETED')
            except Exception as e:
                logger.error(f"Errore notifica rimozione Google: {e}")
                results['google']['message'] = str(e)
        else:
            results['google']['message'] = 'Credentials Google non configurate'

        return results


# Istanza globale
notifier = IndexingNotifier()
