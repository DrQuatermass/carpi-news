"""
WebSub (PubSubHubbub) notification system for Google indexing
Notifies Google immediately when new articles are published

NOTA: Questo modulo invia SOLO notifiche push a Google.
NON modifica il feed RSS per mantenere la compatibilità con IFTTT.
Le notifiche WebSub funzionano anche senza i tag atom:link nel feed.
"""
import requests
import logging

logger = logging.getLogger(__name__)


def notify_google_websub(feed_url=None):
    """
    Invia notifica WebSub a Google per indicizzazione rapida

    IMPORTANTE: Questa funzione invia SOLO una notifica HTTP POST a Google.
    Non richiede modifiche al feed RSS - Google riconoscerà comunque la notifica.

    Args:
        feed_url: URL del feed RSS/Atom (default: feed RSS principale)

    Returns:
        bool: True se la notifica è stata inviata con successo, False altrimenti
    """
    if feed_url is None:
        feed_url = "https://ombradelportico.it/feed/rss/"

    # Hub WebSub di Google (ex-PubSubHubbub)
    hub_url = "https://pubsubhubbub.appspot.com/"

    try:
        # Invia ping al hub WebSub
        # Google accetterà la notifica anche se il feed non ha i tag atom:link
        response = requests.post(
            hub_url,
            data={
                'hub.mode': 'publish',
                'hub.url': feed_url
            },
            timeout=10
        )

        if response.status_code == 204:
            logger.info(f"WebSub: notifica inviata con successo per {feed_url}")
            return True
        else:
            logger.warning(f"WebSub: risposta inattesa {response.status_code} per {feed_url}")
            return False

    except requests.RequestException as e:
        logger.error(f"WebSub: errore invio notifica per {feed_url}: {str(e)}")
        return False


def notify_all_feeds():
    """
    Notifica tutti i feed RSS configurati
    Utile quando vengono approvati più articoli contemporaneamente

    Returns:
        dict: Dizionario con risultati per ogni feed
    """
    feeds = {
        'rss': 'https://ombradelportico.it/feed/rss/',
        'atom': 'https://ombradelportico.it/feed/atom/',
        'recenti': 'https://ombradelportico.it/feed/recenti/',
    }

    results = {}
    for feed_name, feed_url in feeds.items():
        results[feed_name] = notify_google_websub(feed_url)

    return results
