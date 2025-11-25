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


@register.filter
def image_srcset(image_url):
    """
    Genera attributo srcset per immagini responsive

    Usage:
        <img src="{{ article.foto }}" srcset="{{ article.foto|image_srcset }}">
    """
    if not image_url:
        return ""

    # Supporta sia Oggi.png che Oggi.webp
    if 'Oggi.webp' in image_url or 'Oggi.png' in image_url:
        # Rimuovi Oggi.webp o Oggi.png per ottenere base URL
        base_url = image_url.replace('Oggi.webp', '').replace('Oggi.png', '')
        return f"{base_url}Oggi-400w.webp 400w, {base_url}Oggi-600w.webp 600w, {base_url}Oggi-800w.webp 800w"

    return ""


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
    # Gestisce sia URL relativi che completi (con https://ombradelportico.it)
    if '/media/' in webp_url or '/static/' in webp_url:
        from django.conf import settings
        from pathlib import Path

        # Converti URL in path assoluto (gestisce sia /media/ che https://.../media/)
        if '/media/' in webp_url:
            # Estrai solo il path dopo /media/
            media_path = webp_url.split('/media/')[-1]
            webp_path = Path(settings.MEDIA_ROOT) / media_path
        else:  # /static/
            # Estrai solo il path dopo /static/
            static_path = webp_url.split('/static/')[-1]
            webp_path = Path(settings.BASE_DIR) / 'home' / 'static' / static_path

        # Se il file WebP non esiste, ritorna l'originale
        if not webp_path.exists():
            return image_url  # Fallback to original PNG/JPG

    return webp_url
