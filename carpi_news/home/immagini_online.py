"""Ricerca di un'immagine in rete per un articolo (Google Custom Search, searchType=image).

Usata dal monitor email quando il comunicato non ha foto allegate e dal tasto
"Cerca immagine online" nell'admin articolo. Costo: una query Google per ricerca
(100 gratis al giorno, poi 5 dollari ogni 1000), tracciata in APIUsage.
Attenzione ai diritti: sono foto trovate in rete, non nostre; meglio quelle delle pagine
ufficiali (comune, enti, associazioni) che compaiono per prime.
"""
import logging
import os
import re

import requests
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

# Immagini che non si possono scaricare o non sono foto della notizia
DOMINI_ESCLUSI = ('fbsbx.com', 'lookaside', 'instagram.', 'tiktok', 'gstatic.com', 'googleusercontent',
                  'shutterstock', 'gettyimages', 'istockphoto', 'alamy', 'depositphotos', 'dreamstime', 'adobestock')
LARGHEZZA_MIN = 600


def query_per_titolo(titolo):
    """Titolo ripulito: niente virgolette, prefissi tipo "CARPI," dei comunicati, massimo ~12 parole."""
    t = strip_tags(titolo or '')
    # "Richiesta pubblicazione comunicato stampa | Ginnastica Carpi": resta solo la parte utile
    pezzi = [p for p in re.split(r'\s*[|:–]\s*', t)
             if p.strip() and not re.match(r'\s*(richiesta (di )?pubblicazione|comunicato stampa|fw|fwd|r|re|i)\b',
                                           p, re.IGNORECASE)]
    t = ' '.join(pezzi) or t
    t = re.sub(r'[“”"«»|]', ' ', t)
    parole = t.split()[:12]
    q = ' '.join(parole)
    if 'carpi' not in q.lower():
        q += ' Carpi'
    return q


def cerca_immagini(query, max_risultati=8, articolo=None, operation='cerca_immagine'):
    """Lista di candidati {url, thumb, larghezza, altezza, pagina, titolo}; [] se la ricerca non va.

    Con un titolo lungo Google spesso non trova nulla: secondo tentativo con le prime 6 parole."""
    candidati = _cerca(query, max_risultati, articolo, operation)
    parole = query.split()
    if not candidati and len(parole) > 7:
        corta = ' '.join(parole[:6])
        if 'carpi' in query.lower() and 'carpi' not in corta.lower():
            corta += ' Carpi'
        candidati = _cerca(corta, max_risultati, articolo, operation)
    return candidati


def _cerca(query, max_risultati, articolo, operation):
    key = os.getenv('GOOGLE_SEARCH_API_KEY')
    cx = os.getenv('GOOGLE_CUSTOM_SEARCH_ID')
    if not key or not cx or not query:
        logger.warning("Ricerca immagini non configurata (GOOGLE_SEARCH_API_KEY / GOOGLE_CUSTOM_SEARCH_ID)")
        return []
    successo, errore = True, ''
    try:
        r = requests.get('https://www.googleapis.com/customsearch/v1', timeout=12, params={
            'key': key, 'cx': cx, 'q': query, 'searchType': 'image', 'num': 10,
            'gl': 'it', 'hl': 'it', 'safe': 'active', 'imgType': 'photo',
        })
        r.raise_for_status()
        items = r.json().get('items', [])
    except Exception as e:
        logger.warning("Ricerca immagini fallita per %r: %s", query, e)
        items, successo, errore = [], False, str(e)[:200]
    try:
        from home.api_usage_tracker import APIUsageTracker
        APIUsageTracker.track_google_search(operation, 1, related_article=articolo, success=successo,
                                            error_message=errore)
    except Exception:
        pass

    candidati = []
    for it in items:
        url = it.get('link', '')
        img = it.get('image', {})
        if not url.startswith('http') or any(d in url.lower() for d in DOMINI_ESCLUSI):
            continue
        if (img.get('width') or 0) < LARGHEZZA_MIN:
            continue
        candidati.append({
            'url': url,
            'thumb': img.get('thumbnailLink') or url,
            'larghezza': img.get('width'),
            'altezza': img.get('height'),
            'pagina': img.get('contextLink', ''),
            'titolo': it.get('title', ''),
        })
    return candidati[:max_risultati]


def immagine_raggiungibile(url):
    """True se l'URL risponde con un'immagine (molti siti bloccano l'hotlink o rispondono HTML)."""
    try:
        r = requests.get(url, timeout=10, stream=True, headers={'User-Agent': 'Mozilla/5.0 (OmbraDelPortico)'})
        ok = r.status_code == 200 and r.headers.get('Content-Type', '').startswith('image/')
        r.close()
        return ok
    except Exception:
        return False


def prima_immagine(query, articolo=None, operation='immagine_email'):
    """URL della prima immagine utilizzabile, o None."""
    for c in cerca_immagini(query, articolo=articolo, operation=operation):
        if immagine_raggiungibile(c['url']):
            return c['url']
    return None


def usa_immagine(articolo, url):
    """Scarica l'immagine in /media/ e la mette come foto dell'articolo. Ritorna il nuovo valore di foto."""
    from home.universal_news_monitor import download_and_save_image

    import hashlib
    # Nome file legato all'URL: con il solo slug il file esistente verrebbe riusato e la foto non cambierebbe
    base = (articolo.slug or f'articolo-{articolo.pk}')[:60]
    locale = download_and_save_image(url, f"{base}-{hashlib.sha1(url.encode()).hexdigest()[:8]}")
    if not locale or not locale.startswith('/media/'):
        raise ValueError("Impossibile scaricare l'immagine (il sito la blocca o non è un'immagine)")
    articolo.foto = locale
    articolo.foto_valida = True
    # Il segnale post_save rigenera le versioni 16:9, 4:3, 1:1 quando cambia la foto
    articolo.save(update_fields=['foto', 'foto_valida'])
    return locale
