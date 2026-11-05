"""Localizzazione degli articoli: comune per il filtro, luogo e coordinate per la mappa.

Due livelli:
1. testo (gratis): il comune trovato con le parole chiave di seo_locations, coordinate del comune.
2. ai: un modello piccolo legge l'articolo e dice dove succede il fatto (posto, indirizzo, comune);
   le coordinate vengono da Nominatim (OpenStreetMap), con cache in GeocodeCache.

Gli articoli con luogo_origine='manuale' non vengono mai toccati.
Comando: python manage.py localizza_articoli (cron ogni 10 minuti, piu' --tutti per l'arretrato).
"""
import json
import logging
import math
import re
import time

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

from home.seo_locations import MUNICIPALITIES, detect_municipality

logger = logging.getLogger(__name__)

MODELLO = 'claude-haiku-4-5-20251001'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
# Policy Nominatim: User-Agent che identifica l'applicazione, massimo 1 richiesta al secondo
NOMINATIM_HEADERS = {'User-Agent': 'OmbraDelPortico/1.0 (+https://ombradelportico.it)'}
DISTANZA_MAX_KM = 25  # un punto piu' lontano di cosi' dal suo comune e' un omonimo sbagliato

_ultima_richiesta = [0.0]

PROMPT = """Leggi questo articolo di un giornale locale di Carpi (Modena) e di' dove succede il fatto principale.

TITOLO: {titolo}
SOMMARIO: {sommario}
TESTO: {testo}

Rispondi solo con un oggetto JSON, senza altro testo:
{{"comune": "...", "frazione": "...", "luogo": "...", "indirizzo": "..."}}

- comune: il comune italiano dove avviene il fatto (es. "Carpi", "Soliera", "Novi di Modena", "Modena", "Bologna"). Se riguarda tutta la provincia o la regione, il capoluogo. Se non si capisce, "".
- frazione: frazione o quartiere, se l'articolo lo dice (es. "Fossoli", "Cortile"), altrimenti "".
- luogo: il posto preciso con un nome proprio, se l'articolo lo nomina (es. "Teatro Comunale", "Palazzo dei Pio", "stadio Cabassi", "parco della Resistenza"), altrimenti "". Non nomi generici come "semaforo", "centro storico", "scuole".
- indirizzo: via e numero civico solo se scritti nell'articolo, altrimenti "".
Non inventare: se un dato non c'e' nel testo, lascia la stringa vuota."""


def _distanza_km(lat1, lng1, lat2, lng2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalizza(testo):
    import unicodedata
    testo = unicodedata.normalize('NFKD', testo or '')
    return ''.join(c for c in testo if not unicodedata.combining(c)).lower()


def comune_noto(nome):
    """Dati del comune se e' fra quelli di seo_locations, cercato per nome o alias."""
    chiave = slugify(nome or '')
    if chiave in MUNICIPALITIES:
        return MUNICIPALITIES[chiave]
    for dati in MUNICIPALITIES.values():
        if (nome or '').strip().lower() in dati['aliases']:
            return dati
    return None


def geocodifica(query, con_nome=False):
    """(lat, lng) da Nominatim, con cache anche dei risultati vuoti. None se non trovato.
    Con con_nome=True ritorna (lat, lng, display_name)."""
    from home.models import GeocodeCache

    query = re.sub(r'\s+', ' ', query).strip()[:255]
    if not query:
        return None
    cached = GeocodeCache.objects.filter(query=query).first()
    if cached:
        if cached.lat is None:
            return None
        return (cached.lat, cached.lng, cached.display_name) if con_nome else (cached.lat, cached.lng)

    attesa = 1.1 - (time.monotonic() - _ultima_richiesta[0])
    if attesa > 0:
        time.sleep(attesa)
    try:
        r = requests.get(NOMINATIM_URL, params={'q': query, 'format': 'jsonv2', 'limit': 1, 'countrycodes': 'it'},
                         headers=NOMINATIM_HEADERS, timeout=15)
        _ultima_richiesta[0] = time.monotonic()
        r.raise_for_status()
        risultati = r.json()
    except Exception as e:
        # Errore di rete: niente cache, si riprova al prossimo giro
        logger.warning("Nominatim non raggiungibile per %r: %s", query, e)
        raise
    if risultati:
        primo = risultati[0]
        lat, lng = float(primo['lat']), float(primo['lon'])
        nome = primo.get('display_name', '')[:500]
        GeocodeCache.objects.create(query=query, lat=lat, lng=lng, display_name=nome)
        return (lat, lng, nome) if con_nome else (lat, lng)
    GeocodeCache.objects.create(query=query)
    return None


def centro_comune(nome):
    dati = comune_noto(nome)
    if dati:
        return float(dati['lat']), float(dati['lng'])
    return geocodifica(f"{nome}, Italia")


def estrai_con_ai(articolo):
    """Dict comune/frazione/luogo/indirizzo letto dal modello, None se la chiamata fallisce."""
    import anthropic
    from home.api_usage_tracker import APIUsageTracker

    testo = re.sub(r'\s+', ' ', strip_tags(articolo.contenuto or '')).strip()[:4000]
    prompt = PROMPT.format(titolo=articolo.titolo, sommario=strip_tags(articolo.sommario or '')[:600], testo=testo)
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    risposta = client.messages.create(model=MODELLO, max_tokens=200, messages=[{'role': 'user', 'content': prompt}])
    try:
        APIUsageTracker.track_anthropic('localizzazione', MODELLO, risposta.usage.input_tokens,
                                        risposta.usage.output_tokens, related_article=articolo)
    except Exception as e:
        logger.warning("Tracking costi localizzazione fallito: %s", e)
    testo_risposta = ''.join(getattr(b, 'text', '') for b in risposta.content)
    m = re.search(r'\{.*\}', testo_risposta, re.DOTALL)
    if not m:
        return None
    try:
        dati = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return {k: str(dati.get(k) or '').strip()[:200] for k in ('comune', 'frazione', 'luogo', 'indirizzo')}


def localizza_da_testo(articolo):
    """Solo comune e coordinate del comune, con le parole chiave. Non salva."""
    dati = detect_municipality(articolo)
    articolo.comune = dati['addressLocality']
    articolo.luogo_nome = dati['name'] if dati['name'] != dati['addressLocality'] else ''
    articolo.luogo_indirizzo = ''
    articolo.lat, articolo.lng = float(dati['lat']), float(dati['lng'])
    articolo.luogo_preciso = False
    articolo.luogo_origine = 'testo'


def localizza_con_ai(articolo):
    """Comune, luogo e coordinate con l'AI e Nominatim. Non salva. False se l'AI non risponde."""
    dati = estrai_con_ai(articolo)
    if not dati:
        return False
    if not dati['comune']:
        # L'AI non lo sa dire: resta il comune delle parole chiave
        localizza_da_testo(articolo)
        articolo.luogo_origine = 'ai'
        return True

    noto = comune_noto(dati['comune'])
    comune = noto['addressLocality'] if noto else dati['comune']
    centro = centro_comune(comune)
    articolo.comune = comune
    articolo.luogo_nome = dati['luogo'] or dati['frazione']
    articolo.luogo_indirizzo = dati['indirizzo']
    articolo.luogo_preciso = False
    articolo.lat, articolo.lng = centro if centro else (None, None)

    # Dal piu' preciso al meno preciso; si scarta un punto troppo lontano dal comune (omonimi)
    tentativi = []
    if dati['indirizzo']:
        tentativi.append(f"{dati['indirizzo']}, {comune}")
    if dati['luogo']:
        tentativi.append(f"{dati['luogo']}, {dati['frazione'] + ', ' if dati['frazione'] else ''}{comune}")
    if dati['frazione']:
        tentativi.append(f"{dati['frazione']}, {comune}")
    for query in tentativi:
        trovato = geocodifica(query, con_nome=True)
        if not trovato:
            continue
        lat, lng, nome = trovato
        # Nominatim, se non trova la via nel comune, risponde con un'omonima altrove (via Tre
        # Febbraio di Modena per Carpi): il comune deve comparire nell'indirizzo trovato
        if _normalizza(comune) not in _normalizza(nome):
            continue
        if centro and _distanza_km(lat, lng, *centro) > DISTANZA_MAX_KM:
            continue
        articolo.lat, articolo.lng = lat, lng
        articolo.luogo_preciso = bool(dati['indirizzo'] or dati['luogo'])
        break
    articolo.luogo_origine = 'ai'
    return True


def coordinate_da_campi(articolo):
    """Ricalcola lat/lng da comune, luogo e indirizzo scritti a mano (admin). Non salva.
    Ritorna True se ha trovato un punto preciso."""
    comune = (comune_noto(articolo.comune) or {}).get('addressLocality') or articolo.comune
    if not comune:
        return False
    centro = centro_comune(comune)
    tentativi = [q for q in (
        f"{articolo.luogo_indirizzo}, {comune}" if articolo.luogo_indirizzo else '',
        f"{articolo.luogo_nome}, {comune}" if articolo.luogo_nome else '',
    ) if q]
    for query in tentativi:
        trovato = geocodifica(query, con_nome=True)
        if trovato and _normalizza(comune) in _normalizza(trovato[2]):
            articolo.lat, articolo.lng = trovato[0], trovato[1]
            articolo.luogo_preciso = True
            return True
    if centro:
        articolo.lat, articolo.lng = centro
    articolo.luogo_preciso = False
    return False


def localizza(articolo, usa_ai=True, salva=True):
    """Localizza un articolo (salvo luogo inserito a mano). Ritorna l'origine usata o None."""
    if articolo.luogo_origine == 'manuale':
        return None
    riuscito = False
    if usa_ai and settings.ANTHROPIC_API_KEY:
        try:
            riuscito = localizza_con_ai(articolo)
        except Exception as e:
            logger.warning("Localizzazione AI fallita per articolo %s: %s", articolo.pk, e)
    if not riuscito:
        localizza_da_testo(articolo)
    articolo.luogo_aggiornato = timezone.now()
    if salva:
        # update_fields: niente save() completo (rigenera slug, immagini, segnali social)
        type(articolo).objects.filter(pk=articolo.pk).update(
            comune=articolo.comune, luogo_nome=articolo.luogo_nome, luogo_indirizzo=articolo.luogo_indirizzo,
            lat=articolo.lat, lng=articolo.lng, luogo_preciso=articolo.luogo_preciso,
            luogo_origine=articolo.luogo_origine, luogo_aggiornato=articolo.luogo_aggiornato)
    return articolo.luogo_origine
