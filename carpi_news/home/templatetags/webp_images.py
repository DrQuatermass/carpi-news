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
    """Helper per convertire URL in WebP"""
    if not image_url:
        return ""

    # Se è già WebP, ritorna com'è
    if image_url.endswith('.webp'):
        return image_url

    # Sostituisci estensione con .webp usando string replace (non Path!)
    # Path() non funziona con URL (rompe https://)
    import re
    webp_url = re.sub(r'\.(png|jpg|jpeg|PNG|JPG|JPEG)$', '.webp', image_url)

    return webp_url
