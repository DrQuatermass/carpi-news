from django import template

register = template.Library()


@register.filter
def truncate_sentences(value, max_chars):
    """
    Tronca alla fine dell'ultima frase completa entro max_chars.
    Fallback: tronca all'ultima parola entro max_chars.
    Non supera MAI max_chars (vincolo per meta description <=160).
    """
    if not value:
        return ''
    value = str(value)
    if len(value) <= max_chars:
        return value
    # Prima cerca entro max_chars
    finestra = value[:max_chars]
    ultimo_punto = max(
        finestra.rfind('. '),
        finestra.rfind('! '),
        finestra.rfind('? '),
    )
    if ultimo_punto > max_chars // 3:
        return finestra[:ultimo_punto + 1].strip()
    # Fallback: tronca all'ultima parola
    return finestra.rsplit(' ', 1)[0].rstrip('.,;:') + '…'


@register.filter
def categoria_slug(value):
    """Slug URL per una categoria, per link a /categoria/<slug>/."""
    from home.models import Articolo

    if value == 'Rubriche':
        return 'rubriche'
    return Articolo.CATEGORIA_SLUG_MAP.get(value, 'attualita')
