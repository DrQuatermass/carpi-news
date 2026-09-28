"""Rielaborazione AI di un articolo esistente con le regole del monitor che l'ha prodotto.

Usata da:
- tasto "Rielabora con AI" accanto ad Approvato (notizie grezze dei monitor con
  rielaborazione su richiesta, ma anche qualsiasi altro articolo);
- tasto "Rigenera Articolo con AI" (stessa pipeline + richieste di modifica).

Passa da UniversalNewsMonitor.generate_ai_article, quindi usa lo stesso provider
(AI_ARTICLE_PROVIDER / ai_provider del monitor), lo stesso system prompt, la ricerca web
e l'output JSON che compila titolo, titolo SEO, sommario, contenuto, tag e spunto social.
"""
import logging
import re
import threading
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

logger = logging.getLogger(__name__)

PROMPT_DEFAULT = (
    "Sei un giornalista esperto di Ombra del Portico, testata locale di Carpi. "
    "Rielabora questa notizia per il giornale locale: mantieni tutti i fatti, non inventare nulla."
)

CACHE_KEY = 'rielaborazione_in_corso_{}'


def _dominio(url):
    return (urlparse(url).netloc or '').lower().removeprefix('www.') if url else ''


def trova_monitor(articolo):
    """Il monitor d'origine; per gli articoli nati prima del collegamento, quello
    con lo stesso dominio della fonte."""
    from home.models import MonitorConfig

    if articolo.monitor_origine_id:
        return articolo.monitor_origine
    dom = _dominio(articolo.fonte)
    if not dom:
        return None
    candidati = [m for m in MonitorConfig.objects.all() if _dominio(m.base_url) == dom]
    candidati.sort(key=lambda m: (not m.is_active, not m.ai_system_prompt))
    return candidati[0] if candidati else None


def _site_config(articolo, monitor):
    from home.universal_news_monitor import SiteConfig

    if monitor:
        sc = monitor.to_site_config()
        sc.config['use_ai_generation'] = True
        sc.config['ai_api_key'] = settings.ANTHROPIC_API_KEY
        if not sc.config.get('ai_system_prompt'):
            sc.config['ai_system_prompt'] = PROMPT_DEFAULT
        if monitor.scraper_type != 'html':
            # Lo scraper non serve per rielaborare: evita init che richiedono credenziali
            sc = SiteConfig(name=sc.name,
                            base_url=sc.base_url or getattr(settings, 'SITE_URL', 'https://ombradelportico.it'),
                            scraper_type='html', category=sc.category, **sc.config)
        return sc
    return SiteConfig(
        name='Rielaborazione manuale',
        base_url=getattr(settings, 'SITE_URL', 'https://ombradelportico.it'),
        scraper_type='html',
        category=articolo.categoria,
        use_ai_generation=True,
        enable_web_search=True,
        ai_system_prompt=PROMPT_DEFAULT,
        ai_api_key=settings.ANTHROPIC_API_KEY,
    )


def rielabora_articolo(articolo_id, richieste_modifica=None):
    """Rielabora in modo sincrono (1-3 minuti). Ritorna il messaggio della pipeline."""
    from home.models import Articolo
    from home.universal_news_monitor import UniversalNewsMonitor

    articolo = Articolo.objects.select_related('monitor_origine').get(pk=articolo_id)
    monitor = trova_monitor(articolo)
    ai_monitor = UniversalNewsMonitor(_site_config(articolo, monitor))

    testo = re.sub(r'<[^>]+>', ' ', articolo.contenuto or '')
    testo = re.sub(r'[ \t]+', ' ', testo)
    testo = re.sub(r'\n\s*\n+', '\n\n', testo).strip()

    article_data = {
        'title': articolo.titolo,
        'url': articolo.fonte or '',
        'full_content': testo,
        'image_url': articolo.foto,
        'category_override': articolo.categoria,
        'richieste_modifica': richieste_modifica if richieste_modifica is not None else articolo.richieste_modifica,
    }
    if articolo.data_evento:
        article_data['event_start'] = articolo.data_evento.isoformat()

    logger.info(
        f"Rielaborazione articolo {articolo.id} con le regole di "
        f"{monitor.name if monitor else 'default (nessun monitor)'}"
    )
    return ai_monitor.generate_ai_article(article_data, existing_articolo_id=articolo.id)


def avvia_rielaborazione(articolo_id, richieste_modifica=None):
    """Avvia la rielaborazione in background. False se ce n'e' gia' una in corso."""
    chiave = CACHE_KEY.format(articolo_id)
    if not cache.add(chiave, True, timeout=600):
        return False

    def _run():
        from home.models import Articolo
        from home.email_notifications import send_article_approval_notification

        try:
            esito = rielabora_articolo(articolo_id, richieste_modifica)
            logger.info(f"Rielaborazione articolo {articolo_id}: {esito}")
            if esito.startswith('Articolo AI aggiornato'):
                send_article_approval_notification(Articolo.objects.get(pk=articolo_id))
        except Exception as e:
            logger.error(f"Rielaborazione articolo {articolo_id} fallita: {e}", exc_info=True)
        finally:
            cache.delete(chiave)
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()
    return True


def in_corso(articolo_id):
    return bool(cache.get(CACHE_KEY.format(articolo_id)))


# --- Link firmato per il tasto "Rielabora" nelle email -------------------------------
# Il link apre una pagina di conferma (GET senza effetti: i controlli antispam dei client
# di posta aprono i link da soli); la rielaborazione parte solo col POST di conferma.
TOKEN_SALT = 'rielabora-da-email'
TOKEN_MAX_AGE = 14 * 24 * 3600


def token_email(articolo_id):
    from django.core.signing import TimestampSigner
    return TimestampSigner(salt=TOKEN_SALT).sign(str(articolo_id))


def articolo_id_da_token(token):
    """Id dell'articolo, oppure None se il token e' falso o scaduto."""
    from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
    try:
        return int(TimestampSigner(salt=TOKEN_SALT).unsign(token, max_age=TOKEN_MAX_AGE))
    except (BadSignature, SignatureExpired, ValueError):
        return None
