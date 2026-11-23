"""Conteggio di impression e clic dei banner, con i filtri contro i bot.

Dal 23/11/2026 un clic dal sito conta solo se lo stesso visitatore (IP + browser)
ha mandato l'impression di quel banner nelle ultime ore: il beacon parte dallo
script della pagina, quindi chi apre direttamente il link di tracciamento senza
caricare la pagina non viene contato. Dal 20/11 una rete di bot (Chrome 135-137
su Mac, IP a rotazione, nessun referer) apriva circa 90 volte al giorno il link
di ogni banner attivo.

I link della newsletter (``?src=newsletter``) non hanno impression: si contano
una volta per visitatore e banner ogni 24 ore, scartando i bot dichiarati.
"""
import hashlib

from django.core.cache import cache

BOT_KEYWORDS = (
    'bot', 'crawler', 'spider', 'scraper', 'curl', 'wget', 'python-requests',
    'headless', 'preview', 'scanner', 'facebookexternalhit',
)

# Durata della dedup delle impression (stesso visitatore, stesso banner)
IMPRESSION_DEDUP_SECONDI = 600
# Per quanto tempo dopo l'ultima impression un clic dal sito e' valido
CLIC_VALIDO_SECONDI = 3 * 3600
# Dedup dei clic: stesso visitatore, stesso banner
CLIC_DEDUP_SECONDI = 60
CLIC_NEWSLETTER_DEDUP_SECONDI = 24 * 3600

SRC_NEWSLETTER = 'newsletter'


def user_agent(request):
    return request.META.get('HTTP_USER_AGENT', '')


def is_bot(request):
    ua = user_agent(request).lower()
    return not ua or any(k in ua for k in BOT_KEYWORDS)


def visitatore(request):
    """Impronta stabile tra processi (hash() di Python cambia a ogni avvio)."""
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    ip = ip.split(',')[0].strip()
    ua = user_agent(request)[:200]
    return hashlib.sha1(f'{ip}|{ua}'.encode('utf-8', 'ignore')).hexdigest()[:20]


def segna_visto(request, banner_id):
    """Da chiamare a ogni beacon di impression, anche quando l'impression e' deduplicata."""
    cache.set(f'banner_visto:{banner_id}:{visitatore(request)}', True, CLIC_VALIDO_SECONDI)


def impression_da_contare(request, banner_id):
    """True la prima volta in 10 minuti per visitatore e banner."""
    return cache.add(f'banner_impr:{banner_id}:{visitatore(request)}', True, IMPRESSION_DEDUP_SECONDI)


def clic_da_contare(request, banner_id):
    """Decide se il clic sul link di tracciamento va contato."""
    if request.method != 'GET' or is_bot(request):
        return False
    chi = visitatore(request)
    if request.GET.get('src') == SRC_NEWSLETTER:
        return cache.add(f'banner_clic_nl:{banner_id}:{chi}', True, CLIC_NEWSLETTER_DEDUP_SECONDI)
    if not cache.get(f'banner_visto:{banner_id}:{chi}'):
        return False
    return cache.add(f'banner_clic:{banner_id}:{chi}', True, CLIC_DEDUP_SECONDI)
