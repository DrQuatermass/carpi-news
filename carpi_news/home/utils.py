import re

from django.utils.text import slugify


def canonical_article_url(article):
    from django.urls import reverse

    return f"https://ombradelportico.it{reverse('dettaglio_articolo', args=[article.slug])}"


# Cluster consonantici leciti in italiano.
_VALID_CLUSTERS = {
    'sc', 'sp', 'st', 'sb', 'sd', 'sf', 'sg', 'sl', 'sm', 'sn', 'sr', 'sv',
    'pr', 'br', 'tr', 'dr', 'cr', 'gr', 'fr', 'pl', 'bl', 'fl', 'gl', 'cl',
    'gn', 'gli', 'ch', 'gh', 'qu', 'mb', 'mp', 'nt', 'nd', 'nc', 'ng',
    'rc', 'rd', 'rg', 'rl', 'rm', 'rn', 'rp', 'rs', 'rt', 'rv',
    'ld', 'lg', 'lt', 'lz', 'lv',
    'tt', 'pp', 'ss', 'rr', 'll', 'nn', 'mm', 'ff', 'cc', 'gg', 'bb', 'dd',
    'zz', 'vv',
    'scr', 'spl', 'spr', 'str', 'sbr', 'sdr', 'sgr',
}


def _has_bad_consonant_cluster(word: str) -> bool:
    word = word.lower()
    if re.search(r'\d', word):
        return False
    i = 0
    while i < len(word):
        j = i
        while j < len(word) and word[j] not in 'aeiouyhàèéìòù':
            j += 1
        cluster = word[i:j]
        if len(cluster) >= 3:
            if cluster[:3] not in _VALID_CLUSTERS and cluster[:2] not in _VALID_CLUSTERS:
                return True
        i = j + 1
    return False


def safe_slugify(text: str, max_length: int = 75) -> str:
    """
    Genera slug pulito troncato a parola intera, max max_length char.
    """
    slug = slugify(text or '', allow_unicode=False)
    if len(slug) <= max_length:
        return slug
    truncated = slug[:max_length]
    last_dash = truncated.rfind('-')
    if last_dash > 10:
        truncated = truncated[:last_dash]
    return truncated


_VALID_3CHAR_WORDS = {
    'tre', 'via', 'mio', 'mia', 'tuo', 'tua', 'sua', 'sui', 'lui', 'lei',
    'noi', 'voi', 'con', 'per', 'tra', 'fra', 'gia', 'piu', 'ben', 'mai',
    'qui', 'qua', 'pro', 'eta', 'oro', 'usa', 'art', 'web', 'app', 'tax',
    'job', 'top', 'big', 'pop', 'rap', 'mix', 'box', 'gas', 'sms', 'gps',
    'dvd', 'cd', 'pc', 'tv', 'iva', 'don', 'san', 'oss', 'fbi', 'ceo',
    'cfo', 'cto', 'srl', 'spa', 'eur', 'usd', 'gbp', 'min', 'max', 'sub',
    'set', 'red', 'rai', 'gym', 'pub', 'led',
}


_VALID_4CHAR_WORDS = {
    'casa', 'anno', 'cosa', 'vita', 'mano', 'parte', 'modo', 'fine',
    'caso', 'capo', 'mese', 'paese', 'mondo', 'punto', 'fatto', 'gente',
    'soli', 'oggi', 'ieri', 'sera', 'sole', 'mare', 'cielo',
    'idea', 'gioia', 'dono', 'foto', 'auto', 'moto', 'film', 'show',
    'gara', 'pace', 'volo', 'rosa', 'fior', 'rosso', 'verde', 'oltre',
    'fino', 'sopra', 'sotto', 'forse', 'mezzo', 'sempre', 'mille', 'cento',
    'venti', 'altre', 'altro', 'altri', 'altra', 'molto', 'molti', 'molte',
    'tanto', 'tanti', 'tutte', 'tutto', 'tutti', 'tutta', 'dopo',
    'prima', 'verso', 'circa', 'meno', 'piu', 'meglio', 'peggio', 'ecco',
    'come', 'dove', 'quando', 'perche', 'chi',
    '2023', '2024', '2025', '2026', '2027',
}


def is_slug_malformed(slug: str) -> tuple[bool, str]:
    """
    Ritorna (is_malformed, reason) per uno slug esistente.

    Regole:
    - vuoto o > 90 char = malformato
    - ultima parola < 3 char (non numero) = malformato
    - ultima parola di 3 char NON in whitelist = malformato
    - ultima parola di 4 char NON in whitelist E che termina con consonante = malformato
    - ultima parola di 5 char con doppia consonante finale = malformato
    - qualsiasi parola con cluster consonantici improbabili = malformato
    """
    if not slug:
        return True, 'vuoto'
    if len(slug) > 90:
        return True, f'troppo-lungo-{len(slug)}'

    parts = [p for p in slug.split('-') if p]
    if not parts:
        return True, 'no-parole'

    last = parts[-1].lower()
    if len(last) < 3 and not last.isdigit():
        return True, f'ultima-parola-troncata:{last}'

    if re.match(r'^\d+$', last):
        pass
    elif len(last) == 3 and last not in _VALID_3CHAR_WORDS:
        return True, f'ultima-sillaba-3-char:{last}'
    elif len(last) == 4 and last not in _VALID_4CHAR_WORDS:
        if last[-1] not in 'aeiouy':
            return True, f'ultima-sillaba-4-char:{last}'
    elif len(last) == 5 and last[-1] not in 'aeiouy' and last[-2] not in 'aeiouy':
        return True, f'ultima-sillaba-5-char:{last}'

    for word in parts:
        if re.search(r'\d', word):
            continue
        if len(word) >= 4 and _has_bad_consonant_cluster(word):
            return True, f'cluster-consonanti:{word}'

    return False, ''
