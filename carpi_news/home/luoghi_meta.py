"""
Luogo da indicare a Meta quando si pubblica (parametri `location_id` di Instagram e `place`
di Facebook): il posto preciso dell'articolo se lo conosciamo, altrimenti il suo comune.

Meta vuole l'identificativo numerico della pagina del luogo. L'app non ha il permesso di
cercarli da sola (`pages/search` risponde "Authorization Error"), quindi stanno qui, raccolti
a mano: si apre la pagina del luogo su Instagram (instagram.com/explore/locations/<id>/) e si
prende il numero dall'indirizzo; lo stesso numero apre la pagina su facebook.com/<id>.

Nessuna AI: il posto si riconosce dal nome gia' salvato dalla localizzazione
(`Articolo.luogo_nome`) e, in mancanza, dal titolo.
"""

import re
import unicodedata

from django.conf import settings
from django.utils.text import slugify

# Comuni: pagine "Città", verificate il 19/11/2026 su Instagram e su Facebook.
PLACE_IDS = {
    "carpi": "102160809825899",
    "modena": "106508342720366",
    "campogalliano": "108519785839364",
    "soliera": "111566162193656",
    "novi-di-modena": "105823169458370",
}
# La localizzazione a volte scrive come comune l'Unione (atti e servizi delle Terre d'Argine):
# non e' un luogo di Instagram, si usa Carpi, dove l'Unione ha sede (scelta di Sven, 19/11/2026)
PLACE_IDS["terre-dargine"] = PLACE_IDS["unione-terre-dargine"] = PLACE_IDS["unione-delle-terre-dargine"] = PLACE_IDS["carpi"]

# Posti precisi, raccolti il 20/11/2026: i piu' ricorrenti negli articoli degli ultimi 90 giorni.
# (identificativo, comune, nomi con cui compare in luogo_nome, nomi abbastanza univoci da cercarli
# anche nel titolo). Nomi in minuscolo e senza accenti. Tutti verificati su Facebook (la pagina si
# apre con il nome giusto), tranne i due segnati "solo Instagram".
LUOGHI = [
    ("974109402652626", "carpi", ["teatro comunale"], ["teatro comunale di carpi"]),
    ("1468125249915041", "carpi", ["palazzo dei pio", "palazzo pio", "castello dei pio"],
     ["palazzo dei pio", "castello dei pio"]),
    ("272634606465369", "carpi", ["castello dei ragazzi"], ["castello dei ragazzi"]),
    ("525993284446629", "carpi", ["cinema ariston", "teatro ariston", "cinema teatro ariston"],
     ["cinema ariston", "all ariston"]),
    ("272494523134292", "carpi", ["cinema corso"], ["cinema corso"]),
    ("555787404913885", "carpi", ["cinema eden"], ["cinema eden"]),
    ("1071506606039910", "carpi", ["terminal"], ["terre d argine innovation lab", "al terminal"]),
    ("168943639950317", "carpi", ["piazza martiri", "piazza dei martiri"], ["piazza martiri", "piazza dei martiri"]),
    ("1244030939070800", "carpi", ["centro storico"], []),
    ("248475199154069", "carpi", ["campo di fossoli", "campo di concentramento di fossoli"],
     ["campo di fossoli"]),
    ("255721507888851", "carpi", ["ospedale ramazzini", "ramazzini", "ospedale di carpi"],
     ["ospedale ramazzini", "al ramazzini"]),
    ("149007571817048", "carpi", ["borgogioioso"], ["borgogioioso"]),
    ("182732109270375", "carpi", ["circolo graziosi", "centro sociale graziosi"], ["circolo graziosi"]),
    ("453546040", "carpi", ["stadio cabassi", "stadio sandro cabassi"], ["stadio cabassi"]),     # solo Instagram
    ("268144680", "carpi", ["biblioteca loria", "auditorium loria", "auditorium della biblioteca loria",
                            "biblioteca multimediale arturo loria", "loria"],
     ["biblioteca loria", "auditorium loria", "alla loria"]),                                    # solo Instagram
    # frazioni
    ("124154964841376", "carpi", ["fossoli"], ["a fossoli"]),
    ("108255484224392", "soliera", ["limidi"], ["a limidi"]),
]


CATEGORIE_SENZA_POSTO = {"cosa fare oggi", "editoriale", "l'eco del consiglio"}


def _normale(testo: str) -> str:
    """Minuscolo, senza accenti e senza punteggiatura, con uno spazio tra le parole."""
    testo = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", testo).split())


def _contiene(testo: str, nome: str) -> bool:
    return f" {nome} " in f" {testo} "


def luogo_preciso(articolo) -> str:
    """Identificativo del posto dell'articolo, se e' tra quelli noti; altrimenti stringa vuota.

    Vince il nome piu' lungo, cosi' "campo di fossoli" batte "fossoli". Il posto deve essere
    del comune dell'articolo (un "Teatro Comunale" di Modena non e' quello di Carpi); se il
    comune manca si cerca solo nel titolo, con i nomi piu' univoci."""
    # Le rubriche che raccolgono piu' appuntamenti o piu' fatti non hanno un posto solo: la
    # localizzazione ne sceglie uno tra tanti, e taggarlo sarebbe sbagliato. Resta il comune.
    if (getattr(articolo, "categoria", "") or "").strip().lower() in CATEGORIE_SENZA_POSTO:
        return ""
    comune = slugify(getattr(articolo, "comune", "") or "")
    candidati = []
    nome_luogo = _normale(getattr(articolo, "luogo_nome", ""))
    if nome_luogo and comune:
        for place_id, del_comune, nomi, _ in LUOGHI:
            if del_comune == comune:
                candidati += [(len(n), place_id) for n in nomi if _contiene(nome_luogo, n)]
    if not candidati:
        titolo = _normale(getattr(articolo, "titolo", ""))
        for place_id, del_comune, _, nel_titolo in LUOGHI:
            if not comune or del_comune == comune:
                candidati += [(len(n), place_id) for n in nel_titolo if _contiene(titolo, n)]
    return max(candidati)[1] if candidati else ""


def place_id_per(articolo) -> str:
    """Identificativo Meta per l'articolo: il posto preciso se noto, altrimenti il comune.

    Articolo senza comune: Carpi, come ipotesi di una testata di Carpi.
    Articolo di un comune senza identificativo: nessun luogo, meglio che uno sbagliato."""
    preciso = luogo_preciso(articolo)
    if preciso:
        return preciso
    comune = slugify(getattr(articolo, "comune", "") or "") or "carpi"
    place_id = PLACE_IDS.get(comune, "")
    if not place_id and comune == "carpi":
        place_id = getattr(settings, "CARPI_PLACE_ID", "")
    return str(place_id or "")
