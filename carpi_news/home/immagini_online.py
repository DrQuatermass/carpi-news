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
                  'shutterstock', 'gettyimages', 'istockphoto', 'alamy', 'depositphotos', 'dreamstime', 'adobestock',
                  'vecteezy', 'freepik', '123rf', 'pixabay', 'pexels', 'unsplash')
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


MODELLO_QUERY = 'claude-haiku-4-5-20251001'

PROMPT_QUERY = """Devo cercare su Google Immagini una foto per questo articolo di un giornale locale di Carpi (Modena).

TITOLO: {titolo}
TESTO: {testo}

Scrivi due ricerche brevi (2-5 parole ciascuna) che descrivono COSA si vede nella foto giusta:
1. il soggetto preciso con il luogo, se conta (es. "parrocchetti monaco Carpi", "Teatro Comunale Carpi", "ospedale Ramazzini Carpi");
2. il soggetto generico, senza luogo (es. "parrocchetto monaco", "sipario teatro", "pronto soccorso ospedale").
Usa i nomi delle cose, dei posti e degli eventi, non le parole del titolo come "cinque", "tra", "difendere".
Per un comunicato politico su un tema, cerca il tema (es. "sanità pubblica ospedale"), non il partito.
Rispondi solo con un array JSON di due stringhe, senza altro testo."""


def query_con_ai(titolo, testo='', articolo=None):
    """Due ricerche brevi scelte da un modello piccolo; [] se la chiamata non va (~0,1 centesimi)."""
    import json
    from django.conf import settings
    if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return []
    try:
        import anthropic
        testo = re.sub(r'\s+', ' ', strip_tags(testo or '')).strip()[:2000]
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        r = client.messages.create(model=MODELLO_QUERY, max_tokens=100, messages=[
            {'role': 'user', 'content': PROMPT_QUERY.format(titolo=strip_tags(titolo or ''), testo=testo)}])
        try:
            from home.api_usage_tracker import APIUsageTracker
            APIUsageTracker.track_anthropic('query_immagine', MODELLO_QUERY, r.usage.input_tokens,
                                            r.usage.output_tokens, related_article=articolo)
        except Exception:
            pass
        m = re.search(r'\[.*\]', ''.join(getattr(b, 'text', '') for b in r.content), re.DOTALL)
        query = json.loads(m.group(0)) if m else []
        return [q.strip() for q in query if isinstance(q, str) and q.strip()][:2]
    except Exception as e:
        logger.warning("Query immagine con AI fallita: %s", e)
        return []


def cerca_per_articolo(titolo, testo='', max_risultati=8, articolo=None, operation='cerca_immagine'):
    """(query usate, candidati): prima le ricerche scelte dall'AI, poi il titolo ripulito come ripiego.

    Con il titolo intero Google Immagini cerca le singole parole ("Cinque pappagalli verdi tra gli
    alberi della Sanmarinese" dava libri e cataloghi); con il soggetto in poche parole i risultati
    sono pertinenti."""
    query = query_con_ai(titolo, testo, articolo) or [query_per_titolo(titolo)]
    usate, candidati, visti = [], [], set()
    for q in query:
        usate.append(q)
        for c in _cerca(q, max_risultati, articolo, operation):
            if c['url'] not in visti:
                visti.add(c['url'])
                candidati.append(c)
        if len(candidati) >= max_risultati:
            break
    return usate, candidati[:max_risultati]


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


def prima_immagine(titolo, testo='', articolo=None, operation='immagine_email'):
    """URL della prima immagine utilizzabile per l'articolo, o None."""
    for c in cerca_per_articolo(titolo, testo, articolo=articolo, operation=operation)[1]:
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
