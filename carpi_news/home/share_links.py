import secrets
import string
from urllib.parse import urlencode, urljoin

from django.conf import settings
from django.urls import reverse

from .models import ShortLink


TOKEN_ALPHABET = string.ascii_letters + string.digits


def _site_url() -> str:
    configured = getattr(settings, "SITE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    try:
        from django.contrib.sites.models import Site

        domain = Site.objects.get_current().domain
        scheme = "http" if getattr(settings, "DEBUG", False) else "https"
        return f"{scheme}://{domain}".rstrip("/")
    except Exception:
        return "https://ombradelportico.it"


def build_share_url(articolo, platform: str, medium: str) -> str:
    """URL assoluto dell'articolo con parametri UTM standard."""
    path = reverse("dettaglio_articolo", kwargs={"slug": articolo.slug})
    query = urlencode({
        "utm_source": platform,
        "utm_medium": medium,
        "utm_campaign": "share",
    })
    return f"{urljoin(_site_url() + '/', path.lstrip('/'))}?{query}"


def _new_token(length: int = 6) -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


def get_or_create_short_link(articolo, platform: str, medium: str) -> ShortLink:
    short_link = ShortLink.objects.filter(
        articolo=articolo,
        platform=platform,
        medium=medium,
    ).first()
    if short_link:
        return short_link

    for _ in range(20):
        token = _new_token()
        if not ShortLink.objects.filter(token=token).exists():
            return ShortLink.objects.create(
                articolo=articolo,
                platform=platform,
                medium=medium,
                token=token,
            )
    raise RuntimeError("Impossibile generare un token short link univoco")


def build_short_share_url(articolo, platform: str, medium: str) -> str:
    short_link = get_or_create_short_link(articolo, platform, medium)
    return urljoin(_site_url() + "/", reverse("short_link_redirect", kwargs={"token": short_link.token}).lstrip("/"))
