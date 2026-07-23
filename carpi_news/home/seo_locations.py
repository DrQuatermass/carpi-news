import re
import unicodedata

from django.utils.html import strip_tags


MUNICIPALITIES = {
    "carpi": {
        "name": "Carpi",
        "addressLocality": "Carpi",
        "cap": "41012",
        "lat": "44.7829",
        "lng": "10.8857",
        "aliases": ["carpi", "carpigiano", "carpigiana"],
    },
    "soliera": {
        "name": "Soliera",
        "addressLocality": "Soliera",
        "cap": "41019",
        "lat": "44.7386",
        "lng": "10.9212",
        "aliases": ["soliera"],
    },
    "novi-di-modena": {
        "name": "Novi di Modena",
        "addressLocality": "Novi di Modena",
        "cap": "41016",
        "lat": "44.8896",
        "lng": "10.9006",
        "aliases": ["novi di modena", "novi", "rovereto sulla secchia", "sant'antonio in mercadello"],
    },
    "campogalliano": {
        "name": "Campogalliano",
        "addressLocality": "Campogalliano",
        "cap": "41011",
        "lat": "44.6889",
        "lng": "10.8422",
        "aliases": ["campogalliano", "saliceto buzzalino", "panzano"],
    },
    "modena": {
        "name": "Modena",
        "addressLocality": "Modena",
        "cap": "41121",
        "lat": "44.6471",
        "lng": "10.9252",
        "aliases": ["modena"],
    },
    "mirandola": {
        "name": "Mirandola",
        "addressLocality": "Mirandola",
        "cap": "41037",
        "lat": "44.8873",
        "lng": "11.0662",
        "aliases": ["mirandola"],
    },
    "concordia-sulla-secchia": {
        "name": "Concordia sulla Secchia",
        "addressLocality": "Concordia sulla Secchia",
        "cap": "41033",
        "lat": "44.9135",
        "lng": "10.9847",
        "aliases": ["concordia sulla secchia", "concordia"],
    },
    "san-prospero": {
        "name": "San Prospero",
        "addressLocality": "San Prospero",
        "cap": "41030",
        "lat": "44.7901",
        "lng": "11.0233",
        "aliases": ["san prospero"],
    },
    "cavezzo": {
        "name": "Cavezzo",
        "addressLocality": "Cavezzo",
        "cap": "41032",
        "lat": "44.8364",
        "lng": "11.0282",
        "aliases": ["cavezzo"],
    },
}

FRACTIONS = {
    "limidi": {
        "name": "Limidi",
        "municipality": "soliera",
        "aliases": ["limidi"],
    },
    "appalto": {
        "name": "Appalto",
        "municipality": "soliera",
        "aliases": ["appalto"],
    },
    "sozzigalli": {
        "name": "Sozzigalli",
        "municipality": "soliera",
        "aliases": ["sozzigalli"],
    },
    "cortile": {
        "name": "Cortile",
        "municipality": "carpi",
        "aliases": ["cortile"],
    },
    "gargallo": {
        "name": "Gargallo",
        "municipality": "carpi",
        "aliases": ["gargallo"],
    },
    "fossoli": {
        "name": "Fossoli",
        "municipality": "carpi",
        "aliases": ["fossoli"],
    },
    "migliarina": {
        "name": "Migliarina",
        "municipality": "carpi",
        "aliases": ["migliarina"],
    },
    "san-marino-di-carpi": {
        "name": "San Marino di Carpi",
        "municipality": "carpi",
        "aliases": ["san marino di carpi"],
    },
}

DEFAULT_MUNICIPALITY_KEY = "carpi"
MODENA_AUTONOMOUS_PATTERNS = (
    r"\ba\s+modena\b",
    r"\bdi\s+modena\s+citta\b",
    r"\bmodena\s+citta\b",
    r"\bcomune\s+di\s+modena\b",
    r"\bsindaco\s+di\s+modena\b",
    r"\bcentro\s+di\s+modena\b",
)
EXCLUDED_ALIAS_PATTERNS = {
    "novi": (
        r"\bnovi\s+sad\b",
    ),
}

# Alias che sono anche nomi comuni. L'occorrenza vale come localita' solo se
# non e' preceduta da articolo/preposizione ("nel cortile di Palazzo dei Pio")
# e non e' seguita dal complemento di specificazione di un altro luogo
# ("Cortile di Villa Berti"). Restano riconosciute "sagra a Cortile" e
# "Cortile di Carpi".
COMMON_NOUN_ALIASES = {
    "cortile": {
        "prefix": r"(?:in|nel|nello|nei|negli|il|lo|i|gli|un|uno|del|dello|dei|degli|dal|dallo|dai|al|allo|ai|sul|sullo|sui|questo|quel|suo|loro|proprio)\s+$",
        "suffix": r"\s+d(?:i|el|ella|ello|elle|ei|egli)\b(?!\s+carpi\b)",
    },
}


def _normalize_text(value):
    text = strip_tags(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[-_/]+", " ", text)
    return text.lower()


def _contains_alias(text, alias):
    alias = _normalize_text(alias)
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) is not None


def _word_chunks(value, first_words=200):
    words = re.findall(r"\S+", strip_tags(value or ""))
    first = " ".join(words[:first_words])
    rest = " ".join(words[first_words:])
    return first, rest


def _modena_is_autonomous(text):
    return any(re.search(pattern, text) for pattern in MODENA_AUTONOMOUS_PATTERNS)


def _place_data_from_fraction(fraction):
    municipality = MUNICIPALITIES[fraction["municipality"]]
    data = municipality.copy()
    data["name"] = fraction["name"]
    data["addressLocality"] = municipality["name"]
    return data


def _candidate_places():
    for fraction in FRACTIONS.values():
        for alias in fraction["aliases"]:
            yield alias, _place_data_from_fraction(fraction)

    for data in MUNICIPALITIES.values():
        for alias in data["aliases"]:
            yield alias, data


def _is_common_noun_use(text, match, rules):
    """True se l'occorrenza e' il nome comune e non la localita'."""
    preceding = text[max(0, match.start() - 20):match.start()]
    if re.search(rules["prefix"], preceding):
        return True
    following = text[match.end():match.end() + 30]
    return bool(re.match(rules["suffix"], following))


def _best_location_in_text(value):
    text = _normalize_text(value)
    if not text:
        return None

    matches = []
    for alias, data in _candidate_places():
        normalized_alias = _normalize_text(alias)
        if any(re.search(pattern, text) for pattern in EXCLUDED_ALIAS_PATTERNS.get(normalized_alias, ())):
            continue
        if data["addressLocality"] == "Modena" and normalized_alias == "modena" and not _modena_is_autonomous(text):
            continue

        pattern = rf"(?<!\w){re.escape(normalized_alias)}(?!\w)"
        common_noun = COMMON_NOUN_ALIASES.get(normalized_alias)
        for match in re.finditer(pattern, text):
            if common_noun and _is_common_noun_use(text, match, common_noun):
                continue
            matches.append((match.start(), -len(normalized_alias), data))

    if not matches:
        return None

    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[0][2]


def detect_municipality(article):
    first_body, rest_body = _word_chunks(getattr(article, "contenuto", ""))
    fields = [
        getattr(article, "slug", ""),
        getattr(article, "titolo", ""),
        getattr(article, "sommario", ""),
        first_body,
        rest_body,
    ]

    for field in fields:
        location = _best_location_in_text(field)
        if location:
            return location

    return MUNICIPALITIES[DEFAULT_MUNICIPALITY_KEY]
