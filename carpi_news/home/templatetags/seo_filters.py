from django import template

register = template.Library()


@register.filter
def truncate_sentences(value, max_chars):
    """Tronca alla fine dell'ultima frase completa entro max_chars."""
    if not value:
        return ''
    value = str(value)
    if len(value) <= max_chars:
        return value
    troncato = value[:max_chars]
    ultimo_punto = max(
        troncato.rfind('. '),
        troncato.rfind('! '),
        troncato.rfind('? '),
    )
    if ultimo_punto > max_chars // 3:
        return troncato[:ultimo_punto + 1].strip()
    return troncato.rsplit(' ', 1)[0].rstrip('.,;:') + '…'
