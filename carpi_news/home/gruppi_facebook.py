"""Condivisione a mano nei gruppi Facebook.

Da aprile 2024 Meta non permette alle app di pubblicare nei gruppi. Qui si prepara il testo
(riassunto e link tracciato); dalla pagina admin "Condividi nei gruppi"
(GruppoFacebookAdmin.condividi_view) un clic lo copia e apre un gruppo di partenza con la
finestra del post pronta. Gli altri gruppi si aggiungono su Facebook con "Aggiungi gruppi"
(fino a 10 per post): il link e' uno solo e i lettori non si distinguono piu' per gruppo.
"""
import html
import re

from .share_links import build_short_share_url

PLATFORM = 'facebook_gruppo'  # utm_source dei link nei gruppi
MEDIUM = 'gruppi'  # utm_medium: un solo testo (e link) per articolo, uguale in tutti i gruppi


def link_gruppi(articolo):
    """Short link /s/<token>/ che porta all'articolo con utm_source=facebook_gruppo&utm_medium=gruppi."""
    return build_short_share_url(articolo, PLATFORM, MEDIUM)


def _riassunto(testo, massimo=220):
    testo = re.sub(r'(?is)<(style|script|head|title)\b.*?</\1>', ' ', testo or '')
    testo = html.unescape(re.sub(r'<[^>]+>', ' ', testo))
    testo = re.sub(r'\s+', ' ', testo).strip()
    if len(testo) <= massimo:
        return testo
    taglio = testo[:massimo]
    fine_frase = max(taglio.rfind('. '), taglio.rfind('! '), taglio.rfind('? '))
    if fine_frase > massimo // 2:
        return taglio[:fine_frase + 1]
    return taglio.rsplit(' ', 1)[0] + '...'


def testo_condivisione(articolo, link=None):
    """Testo pronto da incollare nei gruppi (si posta come Pagina): riassunto e link.
    Dal 26/11/2026 senza il titolo in testa: lo mostra gia' la scheda del link, come nel post
    della Pagina. Resta il titolo solo se l'articolo non ha sommario."""
    parti = [_riassunto(articolo.sommario) or articolo.titolo]
    parti.append(link or link_gruppi(articolo))
    return '\n\n'.join(parti)
