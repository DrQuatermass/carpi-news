"""
Template per i post Instagram di Ombra del Portico.

Produce un'immagine 1080x1080 in stile coerente con il Reel:
- Logo cream "Ombra del Portico" in alto
- Card quadrata con foto articolo + bordo oro
- Badge categoria
- Titolo Playfair Display (max 2 righe, ellipsis automatica)
- CTA "Scrivi LINK" con la spiegazione del DM automatico (dal 23/11/2026; prima "Leggi nel link in bio")
- Sfondo blurred dell'articolo stesso, scurito per leggibilita'

Punto d'ingresso pubblico:
    from home.instagram_templates import render_instagram_post
    out_path = render_instagram_post(image_path, slug, title, category)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# COSTANTI DI DESIGN (palette del sito, come il modulo facebook_reels)
# -----------------------------------------------------------------------------
SIZE = 1080          # post quadrato 1:1
CARTA = (247, 245, 239)        # fondo
INCHIOSTRO = (40, 42, 40)      # titolo e logo
VINO = (117, 45, 53)           # amaranto: etichetta categoria e pulsante
MUTED = (92, 96, 90)           # testo secondario
WHITE = (255, 255, 255)

# Layout: y assoluti dentro 1080x1080
LAYOUT = {
    "logo_h": 110,
    "logo_y": 30,
    "card_side": 580,
    "card_y": 160,
    "badge_y": 760,
    "title_size": 42,
    "title_y_start": 822,
    "title_y_end": 922,
    "cta_y": 985,
}


# Invito del DM automatico (home/views_webhooks.py): solo su Instagram, dove i link nelle
# didascalie e nei commenti non sono cliccabili. Post, Storie, Reel e copertine usano questi testi.
IG_CTA_PULSANTE = "Scrivi LINK"
IG_CTA_SPIEGAZIONE = "per l'articolo completo"
# Riga fissa sotto titolo e punti chiave del video Instagram (la schermata finale ha il pulsante)
IG_CTA_INVITO = "Scrivi LINK per l'articolo completo"
IG_CTA_DIDASCALIA = "Commenta LINK per l'articolo completo. Lo trovi anche nel link in bio."


def _project_base_dir() -> Path:
    return Path(settings.BASE_DIR)


def _font_path() -> Path:
    # Gelasio: libero (OFL), stesse misure di Georgia, il serif dei titoli del sito
    return _project_base_dir() / "home" / "static" / "home" / "fonts" / "Gelasio-Variable.ttf"


def _emoji_font_path() -> Optional[Path]:
    candidates = [
        Path("C:/Windows/Fonts/seguiemj.ttf"),
        Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _logo_path() -> Path:
    return _project_base_dir() / "home" / "static" / "home" / "images" / "portico_logo.png"


def _heart_cta_path() -> Path:
    return _project_base_dir() / "home" / "static" / "home" / "images" / "instagram_heart_cta.png"


def _output_dir() -> Path:
    """Cartella di output (mantiene la convenzione esistente)."""
    d = _project_base_dir() / "media" / "images" / "instagram_temp"
    d.mkdir(parents=True, exist_ok=True)
    return d


# -----------------------------------------------------------------------------
# PRIMITIVE DI RENDERING
# -----------------------------------------------------------------------------
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(_font_path()), size)
    except Exception:
        logger.warning("IG template: Gelasio non disponibile, fallback DejaVu Serif")
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _load_sans(size: int, candidates: list[str]) -> ImageFont.ImageFont:
    """Primo carattere senza grazie disponibile (Liberation Sans ha le misure di Arial)."""
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return _load_font(size)


def _load_cta_font(size: int) -> ImageFont.ImageFont:
    return _load_sans(size, [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ])


def _load_emoji_font(size: int) -> ImageFont.ImageFont:
    path = _emoji_font_path()
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            logger.warning("IG template: font emoji non caricabile, fallback al font principale")
    return _load_font(size)


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    return (
        code in (0x2764, 0xFE0F)
        or 0x1F300 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
    )


def _mixed_text_size(draw: ImageDraw.ImageDraw, text: str, text_font, emoji_font) -> tuple[int, int]:
    width = 0
    height = 0
    i = 0
    heart_token = "{heart}"
    while i < len(text):
        if text.startswith(heart_token, i):
            size = _heart_size(text_font)
            width += size + _heart_gap(text_font)
            height = max(height, size)
            i += len(heart_token)
            continue
        char = text[i]
        if ord(char) == 0xFE0F:
            i += 1
            continue
        font = emoji_font if _is_emoji_char(char) else text_font
        bbox = draw.textbbox((0, 0), char, font=font)
        width += bbox[2] - bbox[0]
        height = max(height, bbox[3] - bbox[1])
        i += 1
    return width, height


def _draw_mixed_text(layer: Image.Image, draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, text_font, emoji_font, fill) -> None:
    x, y = xy
    i = 0
    heart_token = "{heart}"
    while i < len(text):
        if text.startswith(heart_token, i):
            size = _heart_size(text_font)
            heart_y = y + max(0, int(getattr(text_font, "size", size) * 0.02))
            icon = _load_heart_icon(size, fill)
            layer.alpha_composite(icon, (int(x), int(heart_y)))
            x += size + _heart_gap(text_font)
            i += len(heart_token)
            continue
        char = text[i]
        if ord(char) == 0xFE0F:
            i += 1
            continue
        font = emoji_font if _is_emoji_char(char) else text_font
        draw.text((x, y), char, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), char, font=font)
        x += bbox[2] - bbox[0]
        i += 1


def _heart_size(text_font) -> int:
    return max(30, int(getattr(text_font, "size", 34) * 1.04))


def _heart_gap(text_font) -> int:
    return max(7, int(getattr(text_font, "size", 34) * 0.22))


def _make_colored_icon(icon: Image.Image, fill) -> Image.Image:
    alpha = icon.getchannel("A")
    colored = Image.new("RGBA", icon.size, fill)
    colored.putalpha(alpha)
    return colored


def _load_heart_icon(size: int, fill) -> Image.Image:
    try:
        icon = Image.open(_heart_cta_path()).convert("RGBA")
        bbox = icon.getbbox()
        if bbox:
            icon = icon.crop(bbox)
        icon.thumbnail((size, size), Image.LANCZOS)
        if fill[0] == 0 and fill[1] == 0 and fill[2] == 0:
            return _make_colored_icon(icon, fill)
        return icon
    except Exception:
        fallback = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fallback)
        draw.ellipse((0, 0, size, size), fill=(238, 64, 88, fill[3] if len(fill) > 3 else 255))
        return fallback


def _make_background(image: Image.Image) -> Image.Image:
    """Fondo pieno color carta, come il sito (prima: foto sfocata e scurita)."""
    return Image.new("RGB", (SIZE, SIZE), CARTA)


def _make_card(image: Image.Image, side: int) -> Image.Image:
    """Card quadrata con foto articolo, angoli appena arrotondati, senza bordo."""
    img = image.convert("RGB")
    iw, ih = img.size
    s = min(iw, ih)
    img = img.crop((
        (iw - s) // 2, (ih - s) // 2,
        (iw - s) // 2 + s, (ih - s) // 2 + s,
    ))
    img = img.resize((side, side), Image.LANCZOS)
    radius = 8
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (side, side)], radius=radius, fill=255)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _make_logo(target_height: int) -> Optional[Image.Image]:
    """Logo PNG nero su trasparente ricolorato inchiostro."""
    try:
        logo = Image.open(_logo_path()).convert("RGBA")
    except Exception as e:
        logger.warning(f"IG template: logo non caricabile {_logo_path()}: {e}")
        return None
    _, _, _, alpha = logo.split()
    new = Image.new("RGBA", logo.size, INCHIOSTRO + (0,))
    new.putalpha(alpha)
    w, h = new.size
    return new.resize((int(w * target_height / h), target_height), Image.LANCZOS)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 2):
    """Wrappa testo a max_lines righe; tronca con ellipsis se eccede."""
    words = text.split()
    lines: list[str] = []
    current = ""
    dummy = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(dummy)
    for w in words:
        test = (current + " " + w).strip()
        if d.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
                if len(lines) >= max_lines:
                    lines[-1] = lines[-1].rstrip(".,;:") + "..."
                    return lines
            current = w
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


# -----------------------------------------------------------------------------
# COMPOSIZIONE FINALE
# -----------------------------------------------------------------------------
def render_instagram_post(
    image_path: Path,
    slug: str,
    title: str,
    category: str = "Notizie",
    cta_line_1: str = IG_CTA_PULSANTE,
    cta_line_2: str = "",
    cta_hint: str = IG_CTA_SPIEGAZIONE,
) -> Optional[Path]:
    """
    Genera il template Instagram 1080x1080 a partire dall'immagine dell'articolo.

    Args:
        image_path: Path filesystem dell'immagine sorgente (gia' scaricata)
        slug: slug dell'articolo per il nome del file output
        title: titolo articolo (usato nell'overlay)
        category: categoria articolo (badge in alto sopra il titolo)

    Returns:
        Path del file JPG generato, oppure None se errore.
    """
    try:
        source = Image.open(image_path)

        bg = _make_background(source).convert("RGBA")
        card = _make_card(source, LAYOUT["card_side"])
        bg.alpha_composite(card, ((SIZE - LAYOUT["card_side"]) // 2, LAYOUT["card_y"]))

        # Logo
        logo = _make_logo(LAYOUT["logo_h"])
        if logo is not None:
            bg.alpha_composite(logo, ((SIZE - logo.size[0]) // 2, LAYOUT["logo_y"]))

        # Layer overlay testuale
        overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Badge categoria: amaranto con testo bianco, come le etichette del sito
        cat_font = _load_cta_font(26)
        cat_text = (category or "Notizie").upper()
        bbox = draw.textbbox((0, 0), cat_text, font=cat_font)
        cw = bbox[2] - bbox[0]
        ch = bbox[3] - bbox[1]
        pad = 22
        bw = cw + pad * 2
        bh = ch + 22
        bx = (SIZE - bw) // 2
        by = LAYOUT["badge_y"]
        draw.rounded_rectangle(
            [(bx, by), (bx + bw, by + bh)],
            radius=bh // 2, fill=VINO + (255,),
        )
        draw.text((bx + pad, by + 8), cat_text, font=cat_font, fill=WHITE + (255,))

        # Titolo (max 2 righe, centrato nel band)
        title_font = _load_font(LAYOUT["title_size"])
        lines = _wrap_text(title, title_font, max_width=SIZE - 100, max_lines=2)
        line_h = int(LAYOUT["title_size"] * 1.25)
        total_h = line_h * len(lines)
        band_top = LAYOUT["title_y_start"]
        band_bottom = LAYOUT["title_y_end"]
        y = band_top + (band_bottom - band_top - total_h) // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            lw = bbox[2] - bbox[0]
            x = (SIZE - lw) // 2
            draw.text((x, y), line, font=title_font, fill=INCHIOSTRO + (255,))
            y += line_h

        # CTA: pulsante amaranto pieno, angoli quasi squadrati, senza ombra (come il sito)
        cta_font = _load_cta_font(32)
        emoji_font = _load_emoji_font(34)
        cta_lines = [line.strip() for line in [cta_line_1, cta_line_2] if line.strip()]
        line_h = 42
        if cta_lines:
            widths = [_mixed_text_size(draw, line, cta_font, emoji_font)[0] for line in cta_lines]
            max_line_w = max(widths)
            pad_x = 38
            pad_y = 16
            pill_w = min(SIZE - 150, max_line_w + pad_x * 2)
            pill_h = len(cta_lines) * line_h + pad_y * 2
            pill_x = (SIZE - pill_w) // 2
            pill_y = 940 if cta_hint else 948   # piu' su quando sotto c'e' la spiegazione
            draw.rounded_rectangle(
                [(pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h)],
                radius=6,
                fill=VINO + (255,),
            )

            for idx, line in enumerate(cta_lines):
                line_w, _ = _mixed_text_size(draw, line, cta_font, emoji_font)
                x = (SIZE - line_w) // 2
                y = pill_y + pad_y + idx * line_h
                _draw_mixed_text(
                    overlay,
                    draw,
                    (x, y),
                    line,
                    cta_font,
                    emoji_font,
                    WHITE + (255,),
                )

            # Riga di spiegazione sotto il pulsante: cosa succede se si scrive LINK
            if cta_hint:
                hint_font = _load_sans(26, [
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                    "C:/Windows/Fonts/arial.ttf",
                    "/System/Library/Fonts/Supplemental/Arial.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                ])
                hb = draw.textbbox((0, 0), cta_hint, font=hint_font)
                draw.text(((SIZE - (hb[2] - hb[0])) // 2, pill_y + pill_h + 10), cta_hint,
                          font=hint_font, fill=MUTED + (255,))

        final = Image.alpha_composite(bg, overlay).convert("RGB")
        out_path = _output_dir() / f"{slug}_ig.jpg"
        final.save(out_path, "JPEG", quality=92, optimize=True)
        logger.info(f"IG template generato: {out_path} ({out_path.stat().st_size // 1024} KB)")
        return out_path

    except Exception as e:
        logger.error(f"IG template: errore generazione per slug={slug}: {e}", exc_info=True)
        return None


# -----------------------------------------------------------------------------
# CAROSELLO (dal 26/11/2026): al posto della foto singola quando l'articolo ha i punti chiave
# -----------------------------------------------------------------------------
# Una foto sola basta: copertina con foto e titolo, una scheda di testo per punto chiave
# (gli stessi del video, Articolo.reel_punti) e la scheda finale con l'invito a scrivere LINK.
# Formato 4:5, il piu' alto ammesso nei caroselli. Niente numeri sulle schede: i punti non
# sono una classifica e i puntini in basso dicono gia' a che scheda si e' (scelta di Sven).
CAROSELLO_W, CAROSELLO_H = 1080, 1350
CAROSELLO_MARGINE = 90
CAROSELLO_MAX_PUNTI = 3
CAROSELLO_SCORRI = "Scorri  →"
CAROSELLO_FINALE = ("Per l'articolo completo",)
CAROSELLO_FINALE_DOVE = ("nei commenti", "Te lo mandiamo in privato.", "Lo trovi anche nel link in bio.")
PUNTINO_SPENTO = (205, 201, 190)


def punti_carosello(testo: str) -> list[str]:
    """I punti chiave (uno per riga) da mettere sulle schede, al massimo CAROSELLO_MAX_PUNTI."""
    return [p.strip() for p in (testo or "").splitlines() if p.strip()][:CAROSELLO_MAX_PUNTI]


def _carosello_base(logo_h: int, logo_y: int):
    base = Image.new("RGBA", (CAROSELLO_W, CAROSELLO_H), CARTA + (255,))
    logo = _make_logo(logo_h)
    if logo is not None:
        base.alpha_composite(logo, ((CAROSELLO_W - logo.size[0]) // 2, logo_y))
    return base, ImageDraw.Draw(base)


def _testo_centrato(draw, testo: str, font, y: int, fill) -> None:
    b = draw.textbbox((0, 0), testo, font=font)
    draw.text(((CAROSELLO_W - (b[2] - b[0])) // 2, y), testo, font=font, fill=fill + (255,))


def _puntini(draw, indice: int, totale: int) -> None:
    raggio, passo, y = 7, 30, CAROSELLO_H - 70
    x0 = (CAROSELLO_W - passo * (totale - 1)) // 2
    for i in range(totale):
        colore = VINO if i == indice else PUNTINO_SPENTO
        x = x0 + i * passo
        draw.ellipse([x - raggio, y - raggio, x + raggio, y + raggio], fill=colore + (255,))


def _foto_copertina(image: Image.Image, w: int, h: int) -> Image.Image:
    """Foto ritagliata a w x h con la regola del sito: le verticali si tagliano verso l'alto."""
    from .image_variants import _center_crop_box

    img = image.convert("RGB")
    img = img.crop(_center_crop_box(img.width, img.height, w / h)).resize((w, h), Image.LANCZOS)
    maschera = Image.new("L", (w, h), 0)
    ImageDraw.Draw(maschera).rounded_rectangle([(0, 0), (w, h)], radius=10, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, (0, 0), maschera)
    return out


def _scheda_copertina(source: Image.Image, title: str, category: str, totale: int) -> Image.Image:
    base, draw = _carosello_base(110, 40)
    foto_w, foto_h, foto_y = CAROSELLO_W - 120, 640, 185
    base.alpha_composite(_foto_copertina(source, foto_w, foto_h), (60, foto_y))

    cat_font = _load_cta_font(28)
    cat_text = (category or "Notizie").upper()
    b = draw.textbbox((0, 0), cat_text, font=cat_font)
    bw, bh = b[2] - b[0] + 48, b[3] - b[1] + 24
    bx, by = (CAROSELLO_W - bw) // 2, foto_y + foto_h + 36
    draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=bh // 2, fill=VINO + (255,))
    draw.text((bx + 24, by + 9), cat_text, font=cat_font, fill=WHITE + (255,))

    title_font = _load_font(56)
    y = by + bh + 30
    for riga in _wrap_text(title, title_font, CAROSELLO_W - 2 * CAROSELLO_MARGINE, max_lines=4):
        _testo_centrato(draw, riga, title_font, y, INCHIOSTRO)
        y += 68

    _testo_centrato(draw, CAROSELLO_SCORRI, _load_cta_font(30), CAROSELLO_H - 150, VINO)
    _puntini(draw, 0, totale)
    return base.convert("RGB")


def _scheda_punto(testo: str, title: str, indice: int, totale: int) -> Image.Image:
    base, draw = _carosello_base(80, 50)
    larghezza = CAROSELLO_W - 2 * CAROSELLO_MARGINE
    font = _load_font(98)
    righe = _wrap_text(testo, font, larghezza, max_lines=7)
    if len(righe) > 5:
        font = _load_font(80)
        righe = _wrap_text(testo, font, larghezza, max_lines=8)
    passo = int(font.size * 1.22)
    alto, basso = 190, CAROSELLO_H - 250     # fascia tra logo e piede: il testo sta al centro
    y = alto + (basso - alto - (60 + passo * len(righe))) // 2
    draw.line([(CAROSELLO_MARGINE, y), (CAROSELLO_MARGINE + 120, y)], fill=VINO + (255,), width=6)
    y += 60
    for riga in righe:
        draw.text((CAROSELLO_MARGINE, y), riga, font=font, fill=INCHIOSTRO + (255,))
        y += passo

    piede_font = _load_cta_font(26)
    y = CAROSELLO_H - 210
    for riga in _wrap_text(title, piede_font, larghezza, max_lines=2):
        draw.text((CAROSELLO_MARGINE, y), riga, font=piede_font, fill=MUTED + (255,))
        y += 34
    _puntini(draw, indice, totale)
    return base.convert("RGB")


def _scheda_finale(indice: int, totale: int) -> Image.Image:
    base, draw = _carosello_base(150, 230)
    font = _load_font(64)
    y = 520
    for riga in CAROSELLO_FINALE:
        _testo_centrato(draw, riga, font, y, INCHIOSTRO)
        y += 74

    btn_font = _load_cta_font(54)
    b = draw.textbbox((0, 0), IG_CTA_PULSANTE, font=btn_font)
    bw, bh = b[2] - b[0] + 110, 120
    bx, by = (CAROSELLO_W - bw) // 2, 700
    draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=8, fill=VINO + (255,))
    draw.text((bx + 55, by + 28), IG_CTA_PULSANTE, font=btn_font, fill=WHITE + (255,))

    # "nei commenti" completa la frase del pulsante; sotto, piu' piccolo, cosa succede dopo
    _testo_centrato(draw, CAROSELLO_FINALE_DOVE[0], _load_font(64), 850, INCHIOSTRO)
    dove_font = _load_cta_font(30)
    for i, riga in enumerate(CAROSELLO_FINALE_DOVE[1:]):
        _testo_centrato(draw, riga, dove_font, 985 + i * 46, MUTED)
    _testo_centrato(draw, "ombradelportico.it", _load_font(34), CAROSELLO_H - 190, INCHIOSTRO)
    _puntini(draw, indice, totale)
    return base.convert("RGB")


def render_instagram_carousel(
    image_path: Path,
    slug: str,
    title: str,
    category: str = "Notizie",
    punti: Optional[list[str]] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """
    Genera le schede del carosello: `<slug>_ig_c1.jpg` (copertina), una per punto, la finale.
    Lista vuota se mancano i punti o se qualcosa va storto: chi chiama ripiega sulla foto singola.
    """
    punti = [p for p in (punti or []) if p][:CAROSELLO_MAX_PUNTI]
    if len(punti) < 2:
        return []
    try:
        source = Image.open(image_path)
        totale = len(punti) + 2
        schede = [_scheda_copertina(source, title, category, totale)]
        schede += [_scheda_punto(p, title, i + 1, totale) for i, p in enumerate(punti)]
        schede.append(_scheda_finale(totale - 1, totale))

        cartella = Path(output_dir) if output_dir else _output_dir()
        cartella.mkdir(parents=True, exist_ok=True)
        percorsi = []
        for i, scheda in enumerate(schede, 1):
            percorso = cartella / f"{slug}_ig_c{i}.jpg"
            scheda.save(percorso, "JPEG", quality=92, optimize=True)
            percorsi.append(percorso)
        logger.info(f"IG carosello generato: {len(percorsi)} schede per slug={slug}")
        return percorsi
    except Exception as e:
        logger.error(f"IG carosello: errore generazione per slug={slug}: {e}", exc_info=True)
        return []
