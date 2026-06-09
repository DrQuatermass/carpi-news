import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.contrib.staticfiles import finders

logger = logging.getLogger(__name__)

TRUSTED_IMAGE_DOMAINS = ("voce.it", "ombradelportico.it")


def normalize_image_url(image_url):
    from .models import Articolo

    return Articolo._normalize_image_url(image_url)


def _static_path(relative_path):
    found_path = finders.find(relative_path)
    if found_path:
        return Path(found_path)

    static_root = getattr(settings, "STATIC_ROOT", None)
    if static_root:
        path = Path(static_root) / relative_path
        if path.exists():
            return path

    return Path(settings.BASE_DIR) / "home" / "static" / relative_path


def _local_foto_path(foto):
    if foto.startswith("/media/"):
        return Path(settings.MEDIA_ROOT) / foto.replace("/media/", "", 1)
    if foto.startswith("/static/"):
        return _static_path(foto.replace("/static/", "", 1))
    return None


def _is_trusted_url(url):
    host = urlparse(url).netloc.lower()
    return any(domain in host for domain in TRUSTED_IMAGE_DOMAINS)


def validate_articolo_images(articolo, *, save=True):
    """
    Valida immagini articolo fuori dal render e aggiorna foto_valida.

    Ritorna True quando l'immagine esterna e' valida, e False quando fallisce.
    Immagini locali mancanti vengono azzerate per permettere il fallback.
    """
    update_values = {}
    foto_valida = True

    if articolo.foto_upload:
        try:
            upload_name = articolo.foto_upload.name
            upload_path = Path(articolo.foto_upload.path)
        except (ValueError, AttributeError, OSError):
            upload_name = ""
            upload_path = None

        if upload_name and upload_path and not upload_path.exists():
            logger.warning("Immagine caricata non trovata: %s (articolo: %s)", upload_name, articolo.titolo)
            articolo.foto_upload = None
            update_values["foto_upload"] = ""

    if articolo.foto:
        foto = str(articolo.foto).strip()

        if foto.startswith("/media/") or foto.startswith("/static/"):
            path = _local_foto_path(foto)
            if path and not path.exists():
                logger.warning("Immagine locale non trovata: %s (articolo: %s)", foto, articolo.titolo)
                articolo.foto = ""
                update_values["foto"] = ""
        elif foto.startswith("http://") or foto.startswith("https://"):
            validated_url = normalize_image_url(foto)
            if validated_url != foto:
                articolo.foto = validated_url
                update_values["foto"] = validated_url

            if not _is_trusted_url(validated_url):
                try:
                    response = requests.head(validated_url, timeout=3, allow_redirects=True)
                    foto_valida = response.status_code == 200
                except requests.RequestException as exc:
                    logger.warning("Validazione URL immagine fallita per articolo %s: %s", articolo.pk, exc)
                    foto_valida = False

    if articolo.foto_valida != foto_valida:
        articolo.foto_valida = foto_valida
        update_values["foto_valida"] = foto_valida

    if save and articolo.pk and update_values:
        type(articolo).objects.filter(pk=articolo.pk).update(**update_values)

    return foto_valida
