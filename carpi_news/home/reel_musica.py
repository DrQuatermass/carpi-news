"""
Scelta del sottofondo di Storie e Reel.

Fino al 19/11/2026 il brano era sorteggiato tra tutti quelli della cartella, qualunque fosse
la notizia: un carnevale poteva finire su un lutto. Ora:
- ogni brano ha un tono (raccolto, sobrio, neutro, vivace) e l'articolo ne ammette solo alcuni:
  il tono lo sceglie l'AI nella stessa chiamata dei punti chiave (Articolo.reel_tono), e le
  regole su titolo e categoria restano come riserva;
- lo stesso articolo ha lo stesso brano su Facebook e su Instagram;
- dal 25/11/2026 i brani ruotano: il brano scelto si salva sull'articolo (Articolo.reel_brano)
  e tra quelli ammessi esce quello usato meno di recente, cosi' nessuno torna prima che siano
  usciti tutti gli altri dello stesso tono. Prima decideva un numero ricavato dallo slug e
  capitava lo stesso brano su articoli vicini.
Il brano parte dal suo inizio: la partenza a meta' (dopo l'introduzione) e' stata provata e
scartata lo stesso giorno.

I toni vengono da misure sui file (colpi ritmici, brillantezza, volume) incrociate con i nomi;
i due casi dubbi li ha ascoltati Sven. Un file nuovo messo nella cartella senza aggiungerlo qui
vale come "neutro".
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Optional

ESTENSIONI = {".mp3", ".wav", ".m4a", ".aac"}

# nome del file -> tono
BRANI = {
    "Taccuino di Vetro.mp3": "sobrio",
    "eliveta-corporate-491206.mp3": "sobrio",
    "penguinmusic-inspiring-minimal-434823.mp3": "sobrio",
    "ikoliks_aj-acoustic-spring-mothers-day-music-320427.mp3": "sobrio",
    # aggiunti il 19/11/2026 da Pixabay, scelti dai titoli e dai "mood" dichiarati (non ascoltati)
    "leberch-documentary-calm-614288.mp3": "sobrio",
    "alexgrohl-calm-documentary-629179.mp3": "sobrio",
    "the_mountain-documentary-483804.mp3": "sobrio",
    "leberch-atmospheric-documentary-626200.mp3": "sobrio",
    "grand_project-calm-waves-soft-piano-314968.mp3": "sobrio",
    "surprising_media-soft-light-on-water-487209.mp3": "sobrio",

    # raccolto: brani tristi, solo per i lutti
    "andriig-reflective-sad-music-618652.mp3": "raccolto",
    "leberch-our-story-in-the-past-sad-piano-615222.mp3": "raccolto",
    "sigmamusicart-sad-emotional-piano-background-music-462089.mp3": "raccolto",

    "artmylife-powerful-dramatic-trailer-514242.mp3": "neutro",
    "kontraa-water-afro-pop-music-445661.mp3": "neutro",
    "kornevmusic-upbeat-happy-corporate-487426.mp3": "neutro",
    "lightbeatsmusic-joyful-rhythm-walk-funk-513936.mp3": "neutro",
    "momotmusic-summer-pop-202294.mp3": "neutro",
    "poradovskyi-instagram-reels-marketing-music-469052.mp3": "neutro",
    "soundgallerybydmitrytaras-advertising-music-485233.mp3": "neutro",
    "yourtunes-background-inspiring-corporate-129486.mp3": "neutro",
    "the_mountain-documentary-storytelling-633373.mp3": "neutro",    # Pixabay lo dichiara "Happy, Uplifting"

    "alec_koff-carnaval-484622.mp3": "vivace",
    "alexzavesa-dance-playful-night-510786.mp3": "vivace",
    "artbybigvee-omalicha-nwa-360659.mp3": "vivace",
    "energysound-powerful-percussion-513717.mp3": "vivace",
    "energysound-stomp-action-music-513718.mp3": "vivace",
    "energysound-stomp-drum-percussion-513744.mp3": "vivace",
    "fassounds-fun-life-upbeat-commercial-hiphop-112188.mp3": "vivace",
    "gvidon-gvidon-medicine-364031.mp3": "vivace",
    "magpiemusic-action-trailer-promo-rock-513687.mp3": "vivace",
    "producesplatinum-vlog-hip-hop-483574.mp3": "vivace",
    "starostin-instagram-reels-marketing-music-287533.mp3": "vivace",
}

TONI_PER_CATEGORIA = {
    "cronaca": ("sobrio",),
    "attualità": ("sobrio", "neutro"),
    "politica": ("sobrio", "neutro"),
    "editoriale": ("sobrio", "neutro"),
    "l'eco del consiglio": ("sobrio", "neutro"),
    "cultura & eventi": ("neutro", "vivace"),
    "sport": ("neutro", "vivace"),
    "cosa fare oggi": ("neutro", "vivace"),
}
TONI_DI_RISERVA = ("sobrio", "neutro")      # categoria non prevista: mai il vivace

# Lutti, cronaca nera e giudiziaria finiscono spesso in Attualità: il titolo li riconosce.
# Un lutto ha un brano raccolto; un arresto o un incidente uno sobrio, non uno triste.
TITOLO_LUTTO = re.compile(
    r"\b(mort[oaie]|muor[ei]|morì|decedut|addio|lutto|funeral|vittim|femminicid|suicid|tragedi|scompars[oa])",
    re.IGNORECASE,
)
TITOLO_SOBRIO = re.compile(
    r"\b(incident|accoltell|omicid|violenz|aggression|aggredit|arrest|condann|carcere|malore|"
    r"investit|rapina|stupr|abus[oi])",
    re.IGNORECASE,
)


TONI = ("raccolto", "sobrio", "neutro", "vivace")


def toni_ammessi(articolo) -> tuple:
    """Il tono salvato sull'articolo (scelto dall'AI con i punti chiave, o a mano dall'admin);
    se manca, le regole su titolo e categoria."""
    salvato = (getattr(articolo, "reel_tono", "") or "").strip().lower()
    if salvato in TONI:
        return (salvato,)
    titolo = getattr(articolo, "titolo", "") or ""
    if TITOLO_LUTTO.search(titolo):
        return ("raccolto",)
    if TITOLO_SOBRIO.search(titolo):
        return ("sobrio",)
    categoria = (getattr(articolo, "categoria", "") or "").strip().lower()
    return TONI_PER_CATEGORIA.get(categoria, TONI_DI_RISERVA)


def scegli_brano(articolo, cartella: Path) -> Optional[Path]:
    """Brano per l'articolo, oppure None se la cartella non ha brani.

    Facebook e Instagram ottengono lo stesso brano: la prima scelta si salva sull'articolo.
    Tra i brani ammessi esce quello usato meno di recente (mai usati per primi)."""
    if not cartella.exists():
        return None
    brani = []
    for p in sorted(cartella.iterdir()):
        if not (p.is_file() and p.suffix.lower() in ESTENSIONI):
            continue
        brani.append((p, BRANI.get(p.name, "neutro")))
    if not brani:
        return None
    ammessi = toni_ammessi(articolo)
    # se mancano i brani del tono giusto (cartella incompleta): quelli sobri, poi tutti
    candidati = ([b for b in brani if b[1] in ammessi] or [b for b in brani if b[1] == "sobrio"] or brani)
    chiave = getattr(articolo, "slug", "") or getattr(articolo, "titolo", "") or ""
    if not getattr(articolo, "pk", None) or not hasattr(type(articolo), "objects"):
        return candidati[zlib.crc32(chiave.encode("utf-8")) % len(candidati)][0]
    try:
        return _a_rotazione(articolo, candidati, chiave)
    except Exception:  # la musica non deve mai fermare il video
        return candidati[zlib.crc32(chiave.encode("utf-8")) % len(candidati)][0]


def _a_rotazione(articolo, candidati, chiave) -> Path:
    from django.db.models import Max
    from django.utils import timezone

    Articolo = type(articolo)
    per_nome = {p.name: p for p, _ in candidati}

    def salvato():
        return Articolo.objects.filter(pk=articolo.pk).values_list("reel_brano", flat=True).first() or ""

    # gia' scelto (dall'altra piattaforma, o a una pubblicazione precedente): resta quello,
    # a meno che il tono sia stato cambiato e il brano non sia piu' tra gli ammessi
    nome = salvato()
    if nome in per_nome:
        return per_nome[nome]

    ultimo_uso = dict(
        Articolo.objects.filter(reel_brano__in=list(per_nome), reel_brano_scelto__isnull=False)
        .exclude(pk=articolo.pk)
        .values_list("reel_brano").annotate(ultimo=Max("reel_brano_scelto"))
    )
    mai_usati = sorted(n for n in per_nome if n not in ultimo_uso)
    if mai_usati:
        # tra i mai usati decide lo slug: stessa risposta per Facebook e Instagram anche se
        # arrivano insieme, ma non sempre il primo in ordine alfabetico
        scelto = mai_usati[zlib.crc32(chiave.encode("utf-8")) % len(mai_usati)]
    else:
        scelto = min(per_nome, key=lambda n: (ultimo_uso[n], n))

    aggiornati = Articolo.objects.filter(pk=articolo.pk).exclude(reel_brano__in=list(per_nome)).update(
        reel_brano=scelto, reel_brano_scelto=timezone.now())
    if not aggiornati:  # l'altra piattaforma ha salvato un attimo prima
        nome = salvato()
        scelto = nome if nome in per_nome else scelto
    articolo.reel_brano = scelto
    return per_nome[scelto]
