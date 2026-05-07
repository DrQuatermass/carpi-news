from django import template

register = template.Library()


@register.filter
def truncate_sentences(value, max_chars):
    """
    Tronca alla fine dell'ultima frase completa entro max_chars.
    Se non trova un punto entro max_chars, cerca fino a max_chars+40.
    Fallback: tronca all'ultima parola entro max_chars.
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
    # Lookahead: cerca fino a max_chars + 40
    finestra_ext = value[:max_chars + 40]
    for sep in ['. ', '! ', '? ']:
        pos = finestra_ext.find(sep, max_chars - 10)
        if pos != -1 and pos < max_chars + 40:
            return finestra_ext[:pos + 1].strip()
    # Fallback: tronca all'ultima parola
    return finestra.rsplit(' ', 1)[0].rstrip('.,;:') + '…'
