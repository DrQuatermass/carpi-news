"""
Template tags per gestire immagini WebP con fallback
"""
from django import template
from pathlib import Path
import os

register = template.Library()

@register.simple_tag
def webp_image(image_url, alt_text="", css_class="", fetchpriority="", loading="lazy"):
    """
    Genera un tag picture con WebP e fallback PNG/JPG

    Usage:
        {% webp_image article.foto "Alt text" "css-class" "high" "eager" %}
    """
    if not image_url:
        return ""

    # Converti URL in path WebP
    webp_url = get_webp_url(image_url)

    # Genera HTML con picture tag
    html = '<picture>'

    # Source WebP
    html += f'<source srcset="{webp_url}" type="image/webp">'

    # Fallback originale
    img_attrs = f'src="{image_url}" alt="{alt_text}"'

    if css_class:
        img_attrs += f' class="{css_class}"'
    if fetchpriority:
        img_attrs += f' fetchpriority="{fetchpriority}"'
    if loading:
        img_attrs += f' loading="{loading}"'

    html += f'<img {img_attrs}>'
    html += '</picture>'

    return html


@register.filter
def to_webp(image_url):
    """
    Converte un URL immagine in URL WebP

    Usage:
        {{ article.foto|to_webp }}
    """
    return get_webp_url(image_url)


def get_webp_url(image_url):
    """Helper per convertire URL in WebP solo per immagini locali"""
    if not image_url:
        return ""

    # Se è già WebP, ritorna com'è
    if image_url.endswith('.webp'):
        return image_url

    # SOLO per immagini locali (non esterne!)
    # Non convertire immagini di Twitter, ModenaToday, ecc.
    if image_url.startswith('http') and not 'ombradelportico.it' in image_url:
        return image_url  # Ritorna originale per immagini esterne

    # Sostituisci estensione con .webp usando string replace (non Path!)
    # Path() non funziona con URL (rompe https://)
    import re
    webp_url = re.sub(r'\.(png|jpg|jpeg|PNG|JPG|JPEG)$', '.webp', image_url)

    # Per immagini locali (/media/ o /static/), controlla se il file WebP esiste
    if webp_url.startswith('/media/') or webp_url.startswith('/static/'):
        from django.conf import settings
        from pathlib import Path

        # Converti URL in path assoluto
        if webp_url.startswith('/media/'):
            webp_path = Path(settings.MEDIA_ROOT) / webp_url.replace('/media/', '')
        else:  # /static/
            webp_path = Path(settings.BASE_DIR) / 'home' / 'static' / webp_url.replace('/static/', '')

        # Se il file WebP non esiste, ritorna l'originale
        if not webp_path.exists():
            return image_url  # Fallback to original PNG/JPG

    return webp_url
