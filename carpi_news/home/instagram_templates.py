"""
Template per i post Instagram di Ombra del Portico.

Produce un'immagine 1080x1080 in stile coerente con il Reel:
- Logo cream "Ombra del Portico" in alto
- Card quadrata con foto articolo + bordo oro
- Badge categoria
- Titolo Playfair Display (max 2 righe, ellipsis automatica)
- CTA "Leggi nel link in bio" in pillola bianca
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# COSTANTI DI DESIGN (coerenti col modulo facebook_reels)
# -----------------------------------------------------------------------------
SIZE = 1080          # post quadrato 1:1
BRAND_GOLD = (212, 175, 55)
DARK_BG = (15, 20, 30)
WHITE = (255, 255, 255)
CREAM = (245, 240, 225)

# Layout: y assoluti dentro 1080x1080
LAYOUT = {
    "logo_h": 110,
    "logo_y": 30,
    "card_side": 580,
    "card_y": 160,
    "badge_y": 760,
    "title_size": 40,
    "title_y_start": 822,
    "title_y_end": 900,
    "cta_y": 985,
}


def _project_base_dir() -> Path:
    return Path(settings.BASE_DIR)


def _font_path() -> Path:
    return _project_base_dir() / "home" / "static" / "home" / "fonts" / "PlayfairDisplay-Bold.ttf"


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
        logger.warning("IG template: Playfair non disponibile, fallback DejaVu Serif Bold")
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _load_cta_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return _load_font(size)


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


def _draw_mixed_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, text_font, emoji_font, fill) -> None:
    x, y = xy
    i = 0
    heart_token = "{heart}"
    while i < len(text):
        if text.startswith(heart_token, i):
            size = _heart_size(text_font)
            heart_y = y + max(0, int(getattr(text_font, "size", size) * 0.18))
            heart_fill = (238, 64, 88, fill[3] if len(fill) > 3 else 255)
            if fill[0] == 0 and fill[1] == 0 and fill[2] == 0:
                heart_fill = fill
            _draw_heart(draw, (int(x), int(heart_y)), size, heart_fill)
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
    return max(18, int(getattr(text_font, "size", 34) * 0.72))


def _heart_gap(text_font) -> int:
    return max(7, int(getattr(text_font, "size", 34) * 0.22))


def _draw_heart(draw: ImageDraw.ImageDraw, xy: tuple[int, int], size: int, fill) -> None:
    x, y = xy
    radius = size * 0.28
    left = (x + size * 0.08, y + size * 0.02, x + size * 0.08 + radius * 2, y + size * 0.02 + radius * 2)
    right = (x + size * 0.42, y + size * 0.02, x + size * 0.42 + radius * 2, y + size * 0.02 + radius * 2)
    draw.ellipse(left, fill=fill)
    draw.ellipse(right, fill=fill)
    draw.polygon(
        [
            (x + size * 0.03, y + size * 0.32),
            (x + size * 0.97, y + size * 0.32),
            (x + size * 0.50, y + size * 0.98),
        ],
        fill=fill,
    )


def _make_background(image: Image.Image) -> Image.Image:
    """Versione blurred + scurita dell'immagine articolo, ritagliata a quadrato 1080x1080."""
    img = image.convert("RGB")
    iw, ih = img.size
    # Ritaglio quadrato centrato
    side = min(iw, ih)
    img = img.crop((
        (iw - side) // 2, (ih - side) // 2,
        (iw - side) // 2 + side, (ih - side) // 2 + side,
    ))
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(radius=22))
    dark = Image.new("RGB", img.size, DARK_BG)
    return Image.blend(img, dark, alpha=0.6)


def _make_card(image: Image.Image, side: int) -> Image.Image:
    """Card quadrata con foto articolo, bordo oro arrotondato."""
    img = image.convert("RGB")
    iw, ih = img.size
    s = min(iw, ih)
    img = img.crop((
        (iw - s) // 2, (ih - s) // 2,
        (iw - s) // 2 + s, (ih - s) // 2 + s,
    ))
    img = img.resize((side, side), Image.LANCZOS)
    radius = 32
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (side, side)], radius=radius, fill=255)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    draw = ImageDraw.Draw(out)
    draw.rounded_rectangle(
        [(1, 1), (side - 2, side - 2)],
        radius=radius, outline=BRAND_GOLD + (255,), width=4,
    )
    return out


def _make_logo(target_height: int) -> Optional[Image.Image]:
    """Logo PNG nero su trasparente ricolorato cream."""
    try:
        logo = Image.open(_logo_path()).convert("RGBA")
    except Exception as e:
        logger.warning(f"IG template: logo non caricabile {_logo_path()}: {e}")
        return None
    _, _, _, alpha = logo.split()
    new = Image.new("RGBA", logo.size, CREAM + (0,))
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
    cta_line_1: str = "Link in bio",
    cta_line_2: str = "{heart} per riceverlo nei DM",
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

        # Badge categoria
        cat_font = _load_font(28)
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
            radius=bh // 2, fill=BRAND_GOLD + (255,),
        )
        draw.text((bx + pad, by + 6), cat_text, font=cat_font, fill=DARK_BG + (255,))

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
            for ox, oy in [(2, 2), (-2, 2), (2, -2), (-2, -2)]:
                draw.text((x + ox, y + oy), line, font=title_font, fill=(0, 0, 0, 220))
            draw.text((x, y), line, font=title_font, fill=WHITE + (255,))
            y += line_h

        # CTA a due righe, centrata nel terzo inferiore e leggibile su foto.
        cta_font = _load_cta_font(33)
        emoji_font = _load_emoji_font(34)
        cta_lines = [cta_line_1, cta_line_2]
        line_h = 44
        widths = [_mixed_text_size(draw, line, cta_font, emoji_font)[0] for line in cta_lines]
        box_y = 912
        for idx, line in enumerate(cta_lines):
            line_w, _ = _mixed_text_size(draw, line, cta_font, emoji_font)
            x = (SIZE - line_w) // 2
            y = box_y + 18 + idx * line_h
            for ox, oy in [(2, 2), (-2, 2), (2, -2), (-2, -2)]:
                _draw_mixed_text(
                    draw,
                    (x + ox, y + oy),
                    line,
                    cta_font,
                    emoji_font,
                    (0, 0, 0, 230),
                )
            _draw_mixed_text(
                draw,
                (x, y),
                line,
                cta_font,
                emoji_font,
                WHITE + (255,),
            )

        final = Image.alpha_composite(bg, overlay).convert("RGB")
        out_path = _output_dir() / f"{slug}_ig.jpg"
        final.save(out_path, "JPEG", quality=92, optimize=True)
        logger.info(f"IG template generato: {out_path} ({out_path.stat().st_size // 1024} KB)")
        return out_path

    except Exception as e:
        logger.error(f"IG template: errore generazione per slug={slug}: {e}", exc_info=True)
        return None
