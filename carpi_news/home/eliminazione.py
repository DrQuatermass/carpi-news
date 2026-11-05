"""Cancellazione degli articoli con registro (ArticoloEliminato).

Ogni cancellazione di un Articolo, da qualsiasi punto (admin, comando, tasto nella mail), lascia
una riga in ArticoloEliminato grazie al segnale pre_delete: i monitor la usano per non
reimportare la stessa fonte e l'admin per contare quanto si e' scartato.

Con elimina_articolo / elimina_in_blocco si cancellano anche le immagini locali usate solo da
quell'articolo (con le versioni -400w/-600w/-800w generate per il sito).
"""
import logging
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

CAMPI_IMMAGINE = ('foto', 'foto_upload', 'image_16x9', 'image_4x3', 'image_1x1')
_stato = threading.local()


@contextmanager
def registro_gia_scritto():
    """Dentro questo blocco il segnale non registra: il registro lo scrive chi cancella in blocco."""
    _stato.salta = True
    try:
        yield
    finally:
        _stato.salta = False


def riga_registro(articolo, motivo):
    from home.models import ArticoloEliminato
    monitor = ''
    if articolo.monitor_origine_id:
        monitor = getattr(articolo.monitor_origine, 'name', '') or ''
    return ArticoloEliminato(
        articolo_id=articolo.pk, fonte=(articolo.fonte or '')[:500], titolo=(articolo.titolo or '')[:200],
        categoria=(articolo.categoria or '')[:100], monitor=monitor[:100],
        data_creazione=articolo.data_creazione, motivo=motivo)


def registra_da_segnale(sender, instance, **kwargs):
    """pre_delete di Articolo (collegato in signals.py)."""
    if getattr(_stato, 'salta', False):
        return
    try:
        riga_registro(instance, getattr(instance, '_motivo_eliminazione', 'admin')).save()
    except Exception as e:
        logger.warning("Registro eliminazione non scritto per articolo %s: %s", instance.pk, e)


def fonte_eliminata(url):
    """True se un articolo con questa fonte e' gia' stato cancellato (i monitor non lo reimportano)."""
    from home.models import ArticoloEliminato
    return bool(url) and ArticoloEliminato.objects.filter(fonte=url).exists()


# --- immagini -------------------------------------------------------------------------------

def _percorso_media(articolo, campo):
    """Percorso relativo a MEDIA_ROOT, o None se il campo e' vuoto o punta fuori (URL esterno)."""
    valore = getattr(articolo, campo, None)
    if not valore:
        return None
    grezzo = (getattr(valore, 'name', None) or str(valore)).strip()
    media_url = settings.MEDIA_URL or '/media/'
    if grezzo.startswith('http'):
        return None
    if grezzo.startswith(media_url):
        return grezzo[len(media_url):].lstrip('/')
    if grezzo.startswith('/'):
        return None
    return grezzo or None


def _usata_da_altri(rel, esclusi):
    from home.models import Articolo
    media = (settings.MEDIA_URL or '/media/').rstrip('/') + '/' + rel
    q = (Q(foto=rel) | Q(foto=media) | Q(foto__endswith=media) | Q(foto_upload=rel)
         | Q(image_16x9=rel) | Q(image_4x3=rel) | Q(image_1x1=rel))
    return Articolo.objects.filter(q).exclude(pk__in=esclusi).exists()


def file_da_cancellare(articoli):
    """{Path: byte} delle immagini locali usate solo da questi articoli, varianti responsive incluse."""
    radice = Path(settings.MEDIA_ROOT).resolve()
    ids = {a.pk for a in articoli}
    trovati = {}
    visti = set()
    for a in articoli:
        for campo in CAMPI_IMMAGINE:
            rel = _percorso_media(a, campo)
            if not rel or rel in visti:
                continue
            visti.add(rel)
            p = (radice / rel).resolve()
            if radice not in p.parents or not p.is_file() or _usata_da_altri(rel, ids):
                continue
            trovati[p] = p.stat().st_size
            for variante in p.parent.glob(f"{p.stem}-*w.webp"):
                if variante.stem[len(p.stem) + 1:-1].isdigit():
                    trovati[variante] = variante.stat().st_size
    return trovati


def _cancella_file(file):
    liberati = 0
    for p, size in file.items():
        try:
            p.unlink()
            liberati += size
        except OSError as e:
            logger.warning("File non cancellato %s: %s", p, e)
    return liberati


# --- cancellazione --------------------------------------------------------------------------

def elimina_articolo(articolo, motivo='admin'):
    """Cancella un articolo e le sue immagini esclusive, lasciando la riga nel registro."""
    file = file_da_cancellare([articolo])
    articolo._motivo_eliminazione = motivo
    articolo.delete()
    return _cancella_file(file)


def candidati_pulizia(giorni=7):
    """Non approvati creati da piu' di `giorni` giorni, esclusi pubbliredazionali e articoli gia'
    finiti sui social (i link brevi /s/ e i post puntano ancora li')."""
    from home.models import Articolo
    return (Articolo.objects
            .filter(approvato=False, is_pubbliredazionale=False,
                    data_creazione__lt=timezone.now() - timedelta(days=giorni))
            .filter(social_publications__isnull=True, short_links__isnull=True, redirects__isnull=True)
            .select_related('monitor_origine')
            .order_by('id'))


def elimina_in_blocco(queryset, motivo='pulizia', blocco=300, esegui=False, log=print):
    """Cancella a blocchi. Senza esegui=True conta soltanto. Ritorna (articoli, file, byte)."""
    from home.models import ArticoloEliminato
    ids = list(queryset.values_list('id', flat=True).distinct())
    tot_articoli = tot_file = tot_byte = 0
    for i in range(0, len(ids), blocco):
        articoli = list(queryset.model.objects.filter(pk__in=ids[i:i + blocco]).select_related('monitor_origine'))
        file = file_da_cancellare(articoli)
        tot_articoli += len(articoli)
        tot_file += len(file)
        if esegui:
            with transaction.atomic(), registro_gia_scritto():
                ArticoloEliminato.objects.bulk_create([riga_registro(a, motivo) for a in articoli])
                queryset.model.objects.filter(pk__in=[a.pk for a in articoli]).delete()
            tot_byte += _cancella_file(file)
        else:
            tot_byte += sum(file.values())
        log(f"{'Cancellati' if esegui else 'Da cancellare'}: {tot_articoli}/{len(ids)} articoli, "
            f"{tot_file} file, {tot_byte / 1e6:.1f} MB")
    return tot_articoli, tot_file, tot_byte
