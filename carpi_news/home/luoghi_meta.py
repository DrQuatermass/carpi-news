"""
Luogo da indicare a Meta quando si pubblica un Reel (parametro `location_id`).

Meta vuole l'identificativo numerico della Pagina Facebook del luogo (per un comune: la
pagina-citta', es. "Carpi, Italy"). L'app non ha il permesso di cercarli da sola
(`pages/search` risponde "Authorization Error"), quindi vanno copiati a mano qui: si apre
la pagina del luogo su Facebook e si prende il numero dall'indirizzo o da "Informazioni".

Chiave = slug del comune come lo scrive la localizzazione (`Articolo.comune`).
Carpi puo' stare anche nella variabile d'ambiente CARPI_PLACE_ID.
"""

from django.conf import settings
from django.utils.text import slugify

# Pagine "Città" prese il 19/11/2026 da instagram.com/explore/locations/<id>/ (stesso numero
# della pagina Facebook). Non ancora provate in una pubblicazione: se Meta ne rifiuta una,
# InstagramVideoPublisher ripete la richiesta senza luogo e lo scrive nel log.
PLACE_IDS = {
    "carpi": "102160809825899",
    "modena": "106508342720366",
    "campogalliano": "108519785839364",
    "soliera": "111566162193656",
    "novi-di-modena": "105823169458370",
}


def place_id_per(articolo) -> str:
    """Identificativo Meta del comune dell'articolo, stringa vuota se non lo conosciamo.

    Articolo senza comune: Carpi, come ipotesi di una testata di Carpi.
    Articolo di un comune senza identificativo: nessun luogo, meglio che uno sbagliato.
    """
    comune = slugify(getattr(articolo, "comune", "") or "") or "carpi"
    place_id = PLACE_IDS.get(comune, "")
    if not place_id and comune == "carpi":
        place_id = getattr(settings, "CARPI_PLACE_ID", "")
    return str(place_id or "")
