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
    Converte un URL immagine in URL WebP o usa il proxy per immagini esterne

    Usage:
        {{ article.foto|to_webp }}
    """
    if not image_url:
        return ""

    # Per immagini esterne, usa il proxy
    # Escludi immagini locali (localhost, 127.0.0.1) e del nostro dominio
    if image_url.startswith('http'):
        is_external = (
            'ombradelportico.it' not in image_url and
            'localhost' not in image_url and
            '127.0.0.1' not in image_url
        )
        if is_external:
            from urllib.parse import quote
            encoded_url = quote(image_url, safe='')
            return f"/image-proxy/?url={encoded_url}&w=800"

    return get_webp_url(image_url)


@register.filter
def image_srcset(image_url, sizes="default"):
    """
    Genera attributo srcset per immagini responsive
    Usa il proxy per immagini esterne, versioni multiple per immagini interne

    Usage:
        <img src="{{ article.foto }}" srcset="{{ article.foto|image_srcset }}">
        <img src="{{ article.foto }}" srcset="{{ article.foto|image_srcset:'large' }}">

    Args:
        sizes: 'default' (400/600/800) o 'large' (400/600/800/1200)
    """
    if not image_url:
        return ""

    # Determina le larghezze da generare
    widths = [400, 600, 800, 1200] if sizes == "large" else [400, 600, 800]

    # Supporta sia Oggi.png che Oggi.webp
    if 'Oggi.webp' in image_url or 'Oggi.png' in image_url:
        # Rimuovi Oggi.webp o Oggi.png per ottenere base URL
        base_url = image_url.replace('Oggi.webp', '').replace('Oggi.png', '')
        srcset_parts = [f"{base_url}Oggi-{w}w.webp {w}w" for w in widths]
        return ", ".join(srcset_parts)

    # Per immagini esterne, usa il proxy per diverse dimensioni
    # Escludi localhost e domini interni dal proxy
    internal_domains = ['ombradelportico.it', 'localhost', '127.0.0.1']
    is_external = image_url.startswith('http') and not any(domain in image_url for domain in internal_domains)

    if is_external:
        from urllib.parse import quote
        encoded_url = quote(image_url, safe='')
        # Genera srcset con proxy per diverse larghezze
        srcset_parts = [f"/image-proxy/?url={encoded_url}&w={w} {w}w" for w in widths]
        return ", ".join(srcset_parts)

    # Per immagini interne, cerca versioni responsive esistenti
    if '/media/' in image_url or '/static/' in image_url:
        from pathlib import Path
        from django.conf import settings
        import os

        # Se l'URL contiene il dominio, rimuovilo per avere solo il path
        clean_url = image_url
        if 'ombradelportico.it' in image_url or 'localhost' in image_url or '127.0.0.1' in image_url:
            # Estrai solo il path dopo il dominio (supporta anche localhost:8000)
            import re
            domain_match = re.search(r'(?:ombradelportico\.it|localhost(?::\d+)?|127\.0\.0\.1(?::\d+)?)(/.+)$', image_url)
            if domain_match:
                clean_url = domain_match.group(1)

        # Estrai nome file senza estensione
        import re
        match = re.search(r'(.+/)([^/]+)\.(webp|png|jpg|jpeg)$', clean_url, re.IGNORECASE)
        if match:
            base_path = match.group(1)
            filename = match.group(2)

            # Verifica se esistono versioni responsive sul filesystem
            srcset_parts = []
            # Limita alle larghezze disponibili (non cercare 1200w se sizes='default')
            available_widths = widths
            for width in available_widths:
                responsive_filename = f"{filename}-{width}w.webp"

                # Converti URL in path filesystem
                if '/media/' in image_url:
                    # Rimuovi /media/ e lo slash finale da base_path
                    relative_path = base_path.replace('/media/', '').rstrip('/')
                    file_path = Path(settings.MEDIA_ROOT) / relative_path / responsive_filename
                else:  # /static/
                    # Rimuovi /static/ e lo slash finale da base_path
                    relative_path = base_path.replace('/static/', '').rstrip('/')
                    file_path = Path(settings.BASE_DIR) / 'home' / 'static' / relative_path / responsive_filename

                # Aggiungi solo se il file esiste
                if file_path.exists():
                    responsive_url = f"{base_path}{responsive_filename}"
                    srcset_parts.append(f"{responsive_url} {width}w")

            if srcset_parts:
                return ", ".join(srcset_parts)

            # Fallback: se nessuna versione responsive esiste, usa l'immagine originale
            return f"{image_url} {max(widths)}w"

    return ""


@register.filter
def proxy_url(image_url):
    """
    Restituisce URL proxied per immagini esterne (da usare nell'attributo src).
    Per immagini interne ritorna l'URL originale invariato.

    Usage:
        <img src="{{ article.foto|proxy_url }}">
    """
    if not image_url:
        return image_url
    if image_url.startswith('http') or image_url.startswith('https'):
        internal_domains = ['ombradelportico.it', 'localhost', '127.0.0.1']
        if not any(domain in image_url for domain in internal_domains):
            from urllib.parse import quote
            encoded_url = quote(image_url, safe='')
            return f"/image-proxy/?url={encoded_url}&w=600"
    return image_url


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
