"""
Sitemap ping notification system for Google and Bing indexing
Notifies search engines when new articles are published

Questo è il metodo ufficiale raccomandato da Google dopo la deprecazione di WebSub/PubSubHubbub.
"""
import requests
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


def ping_google_sitemap(sitemap_url=None):
    """
    Notifica Google di aggiornamenti al sitemap

    Questo è il metodo ufficiale raccomandato da Google per notificare nuovi contenuti.
    Google scaricherà il sitemap e scoprirà i nuovi URL.

    Args:
        sitemap_url: URL del sitemap (default: sitemap principale)

    Returns:
        bool: True se la notifica è stata inviata con successo, False altrimenti
    """
    if sitemap_url is None:
        sitemap_url = "https://ombradelportico.it/sitemap.xml"

    # URL encode del sitemap
    encoded_sitemap = quote(sitemap_url, safe='')
    ping_url = f"https://www.google.com/ping?sitemap={encoded_sitemap}"

    try:
        response = requests.get(ping_url, timeout=10)

        if response.status_code == 200:
            logger.info(f"Google sitemap ping inviato con successo per {sitemap_url}")
            return True
        else:
            logger.warning(f"Google sitemap ping: risposta inattesa {response.status_code}")
            return False

    except requests.RequestException as e:
        logger.error(f"Errore ping Google sitemap: {str(e)}")
        return False


def ping_bing_sitemap(sitemap_url=None):
    """
    Notifica Bing di aggiornamenti al sitemap

    Bing supporta il ping sitemap senza API key.
    In genere è più veloce di Google nell'indicizzazione.

    Args:
        sitemap_url: URL del sitemap (default: sitemap principale)

    Returns:
        bool: True se la notifica è stata inviata con successo, False altrimenti
    """
    if sitemap_url is None:
        sitemap_url = "https://ombradelportico.it/sitemap.xml"

    # URL encode del sitemap
    encoded_sitemap = quote(sitemap_url, safe='')
    ping_url = f"https://www.bing.com/ping?sitemap={encoded_sitemap}"

    try:
        response = requests.get(ping_url, timeout=10)

        if response.status_code == 200:
            logger.info(f"Bing sitemap ping inviato con successo per {sitemap_url}")
            return True
        else:
            logger.warning(f"Bing sitemap ping: risposta inattesa {response.status_code}")
            return False

    except requests.RequestException as e:
        logger.error(f"Errore ping Bing sitemap: {str(e)}")
        return False


def notify_search_engines(sitemap_url=None):
    """
    Notifica tutti i motori di ricerca configurati
    Invia ping sia a Google che a Bing

    Args:
        sitemap_url: URL del sitemap (default: sitemap principale)

    Returns:
        dict: Dizionario con risultati per ogni motore di ricerca
    """
    results = {
        'google': ping_google_sitemap(sitemap_url),
        'bing': ping_bing_sitemap(sitemap_url)
    }

    success_count = sum(1 for success in results.values() if success)
    logger.info(f"Sitemap ping completato: {success_count}/{len(results)} motori notificati con successo")

    return results


def notify_all_sitemaps():
    """
    Notifica tutti i sitemap configurati a tutti i motori di ricerca
    Utile per aggiornamenti massivi o manutenzione

    Returns:
        dict: Dizionario con risultati per ogni sitemap
    """
    sitemaps = [
        'https://ombradelportico.it/sitemap.xml',
        # Aggiungi altri sitemap se necessario
        # 'https://ombradelportico.it/sitemap-news.xml',
    ]

    results = {}
    for sitemap_url in sitemaps:
        results[sitemap_url] = notify_search_engines(sitemap_url)

    return results
