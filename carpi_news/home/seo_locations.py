import re
import unicodedata

from django.utils.html import strip_tags


MUNICIPALITIES = {
    "carpi": {
        "name": "Carpi",
        "cap": "41012",
        "lat": "44.7829",
        "lng": "10.8857",
        "aliases": ["carpi", "carpigiano", "carpigiana", "san marino di carpi"],
    },
    "soliera": {
        "name": "Soliera",
        "cap": "41019",
        "lat": "44.7386",
        "lng": "10.9212",
        "aliases": ["soliera", "limidi", "sozzigalli", "appalto"],
    },
    "novi-di-modena": {
        "name": "Novi di Modena",
        "cap": "41016",
        "lat": "44.8896",
        "lng": "10.9006",
        "aliases": ["novi di modena", "novi", "rovereto sulla secchia", "sant'antonio in mercadello"],
    },
    "campogalliano": {
        "name": "Campogalliano",
        "cap": "41011",
        "lat": "44.6889",
        "lng": "10.8422",
        "aliases": ["campogalliano", "saliceto buzzalino", "panzano"],
    },
    "modena": {
        "name": "Modena",
        "cap": "41121",
        "lat": "44.6471",
        "lng": "10.9252",
        "aliases": ["modena", "modenese"],
    },
    "mirandola": {
        "name": "Mirandola",
        "cap": "41037",
        "lat": "44.8873",
        "lng": "11.0662",
        "aliases": ["mirandola"],
    },
    "concordia-sulla-secchia": {
        "name": "Concordia sulla Secchia",
        "cap": "41033",
        "lat": "44.9135",
        "lng": "10.9847",
        "aliases": ["concordia sulla secchia", "concordia"],
    },
    "san-prospero": {
        "name": "San Prospero",
        "cap": "41030",
        "lat": "44.7901",
        "lng": "11.0233",
        "aliases": ["san prospero"],
    },
    "cavezzo": {
        "name": "Cavezzo",
        "cap": "41032",
        "lat": "44.8364",
        "lng": "11.0282",
        "aliases": ["cavezzo"],
    },
}

DEFAULT_MUNICIPALITY_KEY = "carpi"


def _normalize_text(value):
    text = strip_tags(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def _contains_alias(text, alias):
    alias = _normalize_text(alias)
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) is not None


def detect_municipality(article):
    parts = [
        getattr(article, "titolo", ""),
        getattr(article, "titolo_seo", ""),
        getattr(article, "tags", ""),
        getattr(article, "sommario", ""),
        getattr(article, "contenuto", ""),
    ]
    haystack = _normalize_text(" ".join(part for part in parts if part))

    for key, data in MUNICIPALITIES.items():
        if key == DEFAULT_MUNICIPALITY_KEY:
            continue
        if any(_contains_alias(haystack, alias) for alias in data["aliases"]):
            return data

    return MUNICIPALITIES[DEFAULT_MUNICIPALITY_KEY]
