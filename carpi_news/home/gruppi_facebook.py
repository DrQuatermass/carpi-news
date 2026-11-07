"""Condivisione a mano nei gruppi Facebook.

Da aprile 2024 Meta non permette alle app di pubblicare nei gruppi: qui si prepara
tutto (gruppi adatti, testo, link tracciato per gruppo) e la pubblicazione resta a mano
dalla pagina admin "Condividi nei gruppi" (GruppoFacebookAdmin.condividi_view).
"""
import html
import re

from .share_links import build_short_share_url

PLATFORM = 'facebook_gruppo'  # utm_source dei link nei gruppi; utm_medium = slug del gruppo

PUNTI_PAROLA, PUNTI_COMUNE, PUNTI_ZONA = 3, 2, 1
MOTIVI = {PUNTI_PAROLA: 'parla di', PUNTI_COMUNE: 'stesso comune', PUNTI_ZONA: 'gruppo di zona'}


def _testo_articolo(articolo):
    return ' '.join(filter(None, [articolo.titolo, articolo.sommario, articolo.luogo_nome,
                                  articolo.luogo_indirizzo])).lower()


def punteggio(articolo, gruppo, testo=None):
    """(punteggio, motivo): 3 se l'articolo nomina una parola chiave del gruppo,
    2 se il comune coincide, 1 per i gruppi di tutta la zona, 0 altrimenti.
    Un gruppo con parole chiave (frazione, quartiere) si propone solo se l'articolo le nomina:
    non tutte le notizie di Carpi interessano il gruppo di Fossoli."""
    testo = testo if testo is not None else _testo_articolo(articolo)
    parole = gruppo.lista_parole()
    for parola in parole:
        if re.search(r'\b' + re.escape(parola.lower()) + r'\b', testo):
            return PUNTI_PAROLA, f"{MOTIVI[PUNTI_PAROLA]} {parola}"
    if parole:
        return 0, ''
    comune_gruppo = gruppo.comune.strip().lower()
    if comune_gruppo and comune_gruppo == (articolo.comune or '').strip().lower():
        return PUNTI_COMUNE, MOTIVI[PUNTI_COMUNE]
    if not comune_gruppo:
        return PUNTI_ZONA, MOTIVI[PUNTI_ZONA]
    return 0, ''


def gruppi_ordinati(articolo, gruppi):
    """Lista di (gruppo, punteggio, motivo), i piu' adatti prima."""
    testo = _testo_articolo(articolo)
    righe = [(g, *punteggio(articolo, g, testo)) for g in gruppi]
    return sorted(righe, key=lambda r: (-r[1], r[0].nome.lower()))


def link_gruppo(articolo, gruppo):
    """Short link /s/<token>/ che porta all'articolo con utm_source=facebook_gruppo&utm_medium=<slug>."""
    return build_short_share_url(articolo, PLATFORM, gruppo.slug)


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


def testo_condivisione(articolo, gruppo, link=None):
    """Testo pronto da incollare nel gruppo. Dal profilo personale una riga di presentazione."""
    parti = []
    if not gruppo.come_pagina:
        parti.append("Dal giornale online di Carpi che curo, Ombra del Portico:")
    parti.append(articolo.titolo)
    riassunto = _riassunto(articolo.sommario)
    if riassunto and riassunto != articolo.titolo:
        parti.append(riassunto)
    parti.append(link or link_gruppo(articolo, gruppo))
    return '\n\n'.join(parti)
