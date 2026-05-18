"""
Generazione di video verticali e pubblicazione automatica come Storie Facebook.

Il modulo si occupa di:
1. Comporre un MP4 verticale 1080x1920 a partire da un Articolo (foto + titolo + CTA + logo).
2. Aggiungere una traccia audio royalty-free presa da `FACEBOOK_REEL_MUSIC_DIR`
   (fallback su pad ambient procedurale se nessun file e' disponibile).
3. Pubblicare il video sulla Pagina Facebook tramite Stories API (Graph v24.0).

Punto di ingresso pubblico:
    from home.facebook_reels import FacebookReelManager
    manager = FacebookReelManager()
    path = manager.generate(articolo)             # solo generazione locale
    result = manager.publish(articolo)            # generazione + upload story + publish

Dipendenze runtime (gia' in requirements.txt):
    Pillow, numpy, requests, imageio_ffmpeg

Il binario ffmpeg viene preso da imageio_ffmpeg per evitare dipendenze di sistema.
"""

from __future__ import annotations

import io
import logging
import math
import os
import random
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import requests
from django.conf import settings
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# COSTANTI DI DESIGN (allineate con identita' visiva ombradelportico.it)
# -----------------------------------------------------------------------------
WIDTH, HEIGHT = 1080, 1920
DEFAULT_FPS = 24

BRAND_GOLD = (212, 175, 55)
DARK_BG = (15, 20, 30)
WHITE = (255, 255, 255)
CREAM = (245, 240, 225)


# -----------------------------------------------------------------------------
# RISOLUZIONE PATH DEGLI ASSET (font, logo, ffmpeg)
# -----------------------------------------------------------------------------
def _project_base_dir() -> Path:
    """Restituisce BASE_DIR del progetto Django."""
    return Path(settings.BASE_DIR)


def _font_path() -> Path:
    """Path del font Playfair Display Bold dentro la struttura statica."""
    return _project_base_dir() / "home" / "static" / "home" / "fonts" / "PlayfairDisplay-Bold.ttf"


def _emoji_font_path() -> Optional[Path]:
    """Font emoji di sistema, se disponibile."""
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
    """Path del logo principale (illustrazione portico + wordmark + payoff)."""
    return _project_base_dir() / "home" / "static" / "home" / "images" / "portico_logo.png"


def _music_dir() -> Path:
    """Cartella della libreria musicale royalty-free."""
    custom = getattr(settings, "FACEBOOK_REEL_MUSIC_DIR", "")
    if custom:
        return Path(custom)
    return _project_base_dir() / "media" / "reel_music"


def _reels_output_dir(name: str = "reels") -> Path:
    """Cartella dove salvare i video generati (puliti dopo upload).

    Args:
        name: nome della sottocartella sotto media/ (es. 'reels', 'stories')
    """
    d = _project_base_dir() / "media" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ffmpeg_binary() -> str:
    """Path al binario ffmpeg bundlato da imageio_ffmpeg."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# -----------------------------------------------------------------------------
# CONFIGURAZIONE RUNTIME
# -----------------------------------------------------------------------------
@dataclass
class ReelConfig:
    duration_seconds: int = 15
    fps: int = DEFAULT_FPS
    crf: int = 23                 # qualita' H.264 (18-28; piu' basso = piu' qualita')
    preset: str = "veryfast"      # x264 preset
    audio_bitrate: str = "128k"
    video_fade_in_seconds: float = 0.6
    # Personalizzazione output: sottoclassi (es. InstagramStoryGenerator) cambiano questi
    cta_text: str = "Leggi su ombradelportico.it"
    cta_hint: str = ""                            # subtitle sotto la pillola (opzionale, lasciato per estensioni future)
    output_dir_name: str = "reels"   # cartella sotto media/

    @classmethod
    def from_settings(cls) -> "ReelConfig":
        return cls(
            duration_seconds=int(getattr(settings, "FACEBOOK_REEL_DURATION", 15)),
            fps=int(getattr(settings, "FACEBOOK_REEL_FPS", DEFAULT_FPS)),
        )


# =============================================================================
# GENERATORE VIDEO
# =============================================================================
class FacebookReelGenerator:
    """Costruisce un MP4 verticale 1080x1920 a partire da un Articolo."""

    def __init__(self, config: Optional[ReelConfig] = None):
        self.config = config or ReelConfig.from_settings()

    # --- API PUBBLICA --------------------------------------------------------
    # TTL del file generato: se un MP4 con stesso slug e' stato prodotto entro
    # questo intervallo, lo riusiamo invece di rigenerarlo. Serve a evitare di
    # encodare 2 volte lo stesso video quando IG Story e IG Reel condividono
    # la stessa output dir (oppure quando si fa retry di un publish fallito).
    GENERATED_REUSE_TTL_SECONDS = 600

    def generate(self, articolo) -> Optional[str]:
        """Genera il Reel per un articolo. Restituisce il path al MP4 oppure None se fallisce.

        Riusa il file esistente se generato di recente (vedi GENERATED_REUSE_TTL_SECONDS).
        """
        try:
            output_mp4 = _reels_output_dir(self.config.output_dir_name) / f"{articolo.slug}.mp4"

            # Reuse: se l'MP4 esiste e e' recente, salta encoding
            if output_mp4.exists():
                age_s = time.time() - output_mp4.stat().st_mtime
                if age_s <= self.GENERATED_REUSE_TTL_SECONDS:
                    size_kb = output_mp4.stat().st_size // 1024
                    logger.info(
                        f"Reel: riuso video esistente {output_mp4.name} "
                        f"({size_kb} KB, age={int(age_s)}s) -> nessuna rigenerazione"
                    )
                    return str(output_mp4)

            image_path = self._resolve_image_path(articolo)
            if not image_path:
                logger.warning(f"Reel: nessuna immagine valida per articolo '{articolo.titolo}'")
                return None

            with tempfile.TemporaryDirectory(prefix="reel_") as tmpdir:
                tmp = Path(tmpdir)
                frame_path = self._compose_frame(
                    image_path=image_path,
                    title=articolo.titolo,
                    category=articolo.categoria or "Notizie",
                    out_dir=tmp,
                )
                audio_path = self._prepare_audio(out_dir=tmp)
                self._encode_video(frame_path, audio_path, output_mp4)
                logger.info(f"Reel generato: {output_mp4} ({output_mp4.stat().st_size // 1024} KB)")
                return str(output_mp4)
        except Exception as e:
            logger.error(f"Reel: errore generazione per '{articolo.titolo}': {e}", exc_info=True)
            return None

    # --- HELPER IMMAGINE -----------------------------------------------------
    def _resolve_image_path(self, articolo) -> Optional[Path]:
        """
        Risolve il campo foto in un path locale. Se e' URL remoto lo scarica in temp.
        Restituisce None se non riusciamo a ottenere un'immagine valida.
        """
        if getattr(articolo, "foto_upload", None):
            try:
                uploaded = Path(articolo.foto_upload.path)
                if uploaded.exists():
                    return uploaded
            except (ValueError, AttributeError):
                pass

        if not articolo.foto:
            return None

        foto = str(articolo.foto).strip()

        # URL remoto: scarica
        if foto.startswith("http://") or foto.startswith("https://"):
            return self._download_image(foto)

        # Path statico locale (es. articoli "Cosa fare oggi" -> /static/home/images/Oggi.webp)
        if foto.startswith("/static/"):
            local = Path(settings.BASE_DIR) / "home" / "static" / foto.replace("/static/", "", 1)
            if local.exists():
                return local

        # Path media locale (/media/images/...)
        if foto.startswith("/media/"):
            local = Path(settings.MEDIA_ROOT) / foto.replace("/media/", "", 1)
            if local.exists():
                return local

        # Path relativo a MEDIA_URL personalizzato
        media_url = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")
        if foto.startswith(media_url + "/"):
            rel = foto[len(media_url) + 1:]
            local = Path(settings.MEDIA_ROOT) / rel
            if local.exists():
                return local

        # Tentativo come path filesystem assoluto
        p = Path(foto)
        if p.is_absolute() and p.exists():
            return p

        return None

    def _download_image(self, url: str) -> Optional[Path]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; OmbraDelPortico/1.0; +https://ombradelportico.it)",
                "Accept": "image/*",
            }
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            tmp = Path(tempfile.gettempdir()) / f"reel_src_{int(time.time())}.jpg"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            return tmp
        except Exception as e:
            logger.warning(f"Reel: download immagine fallito {url}: {e}")
            return None

    # --- COMPOSIZIONE FRAME --------------------------------------------------
    def _compose_frame(self, image_path: Path, title: str, category: str, out_dir: Path) -> Path:
        bg = self._make_background(image_path)
        card = self._make_card(image_path)
        logo = self._make_logo()
        overlay = self._make_overlay(title=title, category=category, logo=logo)

        frame = bg.convert("RGBA")
        cw, ch = card.size
        cx = (WIDTH - cw) // 2
        frame.alpha_composite(card, (cx, 330))
        frame.alpha_composite(overlay, (0, 0))

        frame_path = out_dir / "frame.jpg"
        frame.convert("RGB").save(frame_path, "JPEG", quality=92)
        return frame_path

    def _make_background(self, image_path: Path) -> Image.Image:
        img = Image.open(image_path).convert("RGB")
        # Crop in alto al 9:16 con riempimento (rimuove eventuali bande nere fonte)
        iw, ih = img.size
        target_ratio = WIDTH / HEIGHT
        src_ratio = iw / ih
        if src_ratio > target_ratio:
            new_w = int(ih * target_ratio)
            left = (iw - new_w) // 2
            img = img.crop((left, 0, left + new_w, ih))
        else:
            new_h = int(iw / target_ratio)
            top = (ih - new_h) // 2
            img = img.crop((0, top, iw, top + new_h))
        img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=22))
        dark = Image.new("RGB", img.size, DARK_BG)
        return Image.blend(img, dark, alpha=0.6)

    def _make_card(self, image_path: Path, card_w: int = 900, card_h: int = 900) -> Image.Image:
        img = Image.open(image_path).convert("RGB")
        iw, ih = img.size
        side = min(iw, ih)
        left = (iw - side) // 2
        top = (ih - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((card_w, card_h), Image.LANCZOS)

        radius = 32
        mask = Image.new("L", (card_w, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [(0, 0), (card_w, card_h)], radius=radius, fill=255
        )
        out = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        draw = ImageDraw.Draw(out)
        draw.rounded_rectangle(
            [(1, 1), (card_w - 2, card_h - 2)],
            radius=radius,
            outline=BRAND_GOLD + (255,),
            width=4,
        )
        return out

    def _make_logo(self, target_height: int = 240) -> Image.Image:
        """Carica il logo PNG (nero su trasparente) e lo ricolora cream per il fondo scuro."""
        logo = Image.open(_logo_path()).convert("RGBA")
        _, _, _, alpha = logo.split()
        recolored = Image.new("RGBA", logo.size, CREAM + (0,))
        recolored.putalpha(alpha)
        w, h = recolored.size
        new_w = int(w * target_height / h)
        return recolored.resize((new_w, target_height), Image.LANCZOS)

    def _make_overlay(self, title: str, category: str, logo: Image.Image) -> Image.Image:
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # LOGO in alto
        lw, _ = logo.size
        logo_x = (WIDTH - lw) // 2
        layer.alpha_composite(logo, (logo_x, 70))

        # Badge categoria
        cat_text = category.upper()
        cat_font = self._load_font(32)
        bbox = draw.textbbox((0, 0), cat_text, font=cat_font)
        cat_w = bbox[2] - bbox[0]
        cat_h = bbox[3] - bbox[1]
        pad = 24
        bw = cat_w + pad * 2
        bh = cat_h + 24
        by = 1230
        bx = (WIDTH - bw) // 2
        draw.rounded_rectangle(
            [(bx, by), (bx + bw, by + bh)],
            radius=bh // 2, fill=BRAND_GOLD + (255,)
        )
        draw.text((bx + pad, by + 6), cat_text, font=cat_font, fill=DARK_BG + (255,))

        # Titolo
        title_font = self._load_font(68)
        lines = self._wrap(title, title_font, max_width=WIDTH - 120)
        if len(lines) > 3:
            lines = lines[:3]
            lines[2] = lines[2].rstrip(".,;:") + "..."
        y = 1340
        line_height = 86
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            lw_t = bbox[2] - bbox[0]
            x = (WIDTH - lw_t) // 2
            for ox, oy in [(2, 2), (-2, 2), (2, -2), (-2, -2)]:
                draw.text((x + ox, y + oy), line, font=title_font, fill=(0, 0, 0, 220))
            draw.text((x, y), line, font=title_font, fill=WHITE + (255,))
            y += line_height

        # CTA in basso, leggibile su qualunque foto.
        cta_font = self._load_cta_font(44)
        cta_lines = [line.strip() for line in self.config.cta_text.splitlines() if line.strip()]
        line_h = 58
        emoji_font = self._load_emoji_font(46)
        widths = [self._mixed_text_size(draw, line, cta_font, emoji_font)[0] for line in cta_lines]
        box_y = HEIGHT - 265
        for idx, line in enumerate(cta_lines):
            line_w, _ = self._mixed_text_size(draw, line, cta_font, emoji_font)
            x = (WIDTH - line_w) // 2
            y = box_y + 23 + idx * line_h
            for ox, oy in [(2, 2), (-2, 2), (2, -2), (-2, -2)]:
                self._draw_mixed_text(draw, (x + ox, y + oy), line, cta_font, emoji_font, (0, 0, 0, 230))
            self._draw_mixed_text(draw, (x, y), line, cta_font, emoji_font, WHITE + (255,))

        # Hint sotto la pillola (es. "Tocca il link in bio per leggere")
        if self.config.cta_hint:
            hint_font = self._load_font(30)
            hint = self.config.cta_hint
            hbb = draw.textbbox((0, 0), hint, font=hint_font)
            hw = hbb[2] - hbb[0]
            hx = (WIDTH - hw) // 2
            hy = cy + 58 + pad_y + 26
            # Ombra per leggibilita'
            for ox, oy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
                draw.text((hx + ox, hy + oy), hint, font=hint_font, fill=(0, 0, 0, 200))
            draw.text((hx, hy), hint, font=hint_font, fill=CREAM + (220,))

        return layer

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(str(_font_path()), size)
        except Exception:
            logger.warning("Reel: Playfair non disponibile, fallback DejaVu Serif Bold")
            try:
                return ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", size
                )
            except Exception:
                return ImageFont.load_default()

    def _load_cta_font(self, size: int) -> ImageFont.ImageFont:
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
        return self._load_font(size)

    def _load_emoji_font(self, size: int) -> ImageFont.ImageFont:
        path = _emoji_font_path()
        if path:
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                logger.warning("Reel: font emoji non caricabile, fallback al font principale")
        return self._load_font(size)

    @staticmethod
    def _is_emoji_char(char: str) -> bool:
        code = ord(char)
        return (
            code in (0x2764, 0xFE0F)
            or 0x1F300 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
        )

    @staticmethod
    def _heart_size(text_font) -> int:
        return max(24, int(getattr(text_font, "size", 46) * 0.72))

    @staticmethod
    def _heart_gap(text_font) -> int:
        return max(8, int(getattr(text_font, "size", 46) * 0.22))

    @staticmethod
    def _draw_heart(draw: ImageDraw.ImageDraw, xy: tuple[int, int], size: int, fill) -> None:
        x, y = xy
        radius = size * 0.28
        left = (x + size * 0.08, y + size * 0.02, x + size * 0.08 + radius * 2, y + size * 0.02 + radius * 2)
        right = (x + size * 0.42, y + size * 0.02, x + size * 0.42 + radius * 2, y + size * 0.02 + radius * 2)
        draw.ellipse(left, fill=fill)
        draw.ellipse(right, fill=fill)
        points = [
            (x + size * 0.03, y + size * 0.32),
            (x + size * 0.97, y + size * 0.32),
            (x + size * 0.50, y + size * 0.98),
        ]
        draw.polygon(points, fill=fill)

    def _mixed_text_size(self, draw: ImageDraw.ImageDraw, text: str, text_font, emoji_font) -> tuple[int, int]:
        width = 0
        height = 0
        i = 0
        heart_token = "{heart}"
        while i < len(text):
            if text.startswith(heart_token, i):
                size = self._heart_size(text_font)
                width += size + self._heart_gap(text_font)
                height = max(height, size)
                i += len(heart_token)
                continue
            char = text[i]
            if ord(char) == 0xFE0F:
                i += 1
                continue
            font = emoji_font if self._is_emoji_char(char) else text_font
            bbox = draw.textbbox((0, 0), char, font=font)
            width += bbox[2] - bbox[0]
            height = max(height, bbox[3] - bbox[1])
            i += 1
        return width, height

    def _draw_mixed_text(self, draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, text_font, emoji_font, fill) -> None:
        x, y = xy
        i = 0
        heart_token = "{heart}"
        while i < len(text):
            if text.startswith(heart_token, i):
                size = self._heart_size(text_font)
                heart_y = y + max(0, int(getattr(text_font, "size", size) * 0.18))
                heart_fill = (238, 64, 88, fill[3] if len(fill) > 3 else 255)
                if fill[0] == 0 and fill[1] == 0 and fill[2] == 0:
                    heart_fill = fill
                self._draw_heart(draw, (int(x), int(heart_y)), size, heart_fill)
                x += size + self._heart_gap(text_font)
                i += len(heart_token)
                continue
            char = text[i]
            if ord(char) == 0xFE0F:
                i += 1
                continue
            font = emoji_font if self._is_emoji_char(char) else text_font
            draw.text((x, y), char, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), char, font=font)
            x += bbox[2] - bbox[0]
            i += 1

    @staticmethod
    def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int):
        words = text.split()
        lines = []
        current = ""
        dummy = Image.new("RGB", (10, 10))
        d = ImageDraw.Draw(dummy)
        for w in words:
            test = (current + " " + w).strip()
            bbox = d.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        return lines

    # --- AUDIO ---------------------------------------------------------------
    def _prepare_audio(self, out_dir: Path) -> Path:
        """Sceglie a caso un file dalla music dir; se nessuno, genera pad ambient procedurale."""
        music_dir = _music_dir()
        candidates: list[Path] = []
        if music_dir.exists():
            # Match case-insensitive: scorri tutti i file e confronta l'estensione minuscola
            allowed_ext = {".mp3", ".wav", ".m4a", ".aac"}
            for p in music_dir.iterdir():
                if p.is_file() and p.suffix.lower() in allowed_ext:
                    candidates.append(p)
            logger.info(f"Reel: music dir={music_dir}, candidates={len(candidates)}")
        else:
            logger.warning(f"Reel: music dir non esiste -> {music_dir}")

        if candidates:
            chosen = random.choice(candidates)
            logger.info(f"Reel: traccia audio selezionata {chosen.name}")
            return chosen
        else:
            logger.info("Reel: nessun file audio nella music dir, uso pad ambient procedurale di fallback")
            wav_path = out_dir / "ambient.wav"
            self._write_procedural_ambient(wav_path, duration=self.config.duration_seconds)
            return wav_path

    @staticmethod
    def _write_procedural_ambient(path: Path, duration: int, fps: int = 44100) -> None:
        t = np.linspace(0, duration, int(duration * fps), endpoint=False)
        freqs = [130.81, 196.00, 261.63, 329.63, 392.00]  # accordo Do maggiore esteso
        wave_buf = np.zeros_like(t)
        for i, f in enumerate(freqs):
            amp = 0.12 / (1 + i * 0.3)
            lfo = 1 + 0.003 * np.sin(2 * math.pi * 0.2 * t + i)
            wave_buf += amp * np.sin(2 * math.pi * f * t * lfo)
        env = np.ones_like(t)
        fade_in_n = int(1 * fps)
        fade_out_n = int(2 * fps)
        env[:fade_in_n] = np.linspace(0, 1, fade_in_n)
        env[-fade_out_n:] = np.linspace(1, 0, fade_out_n)
        wave_buf = wave_buf * env * 0.6
        left = wave_buf
        right = np.roll(wave_buf, int(0.005 * fps))
        stereo = np.stack([left, right], axis=1)
        audio_int16 = (np.clip(stereo, -1, 1) * 32000).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(fps)
            wf.writeframes(audio_int16.tobytes())

    # --- ENCODE --------------------------------------------------------------
    def _encode_video(self, frame_path: Path, audio_path: Path, output_path: Path) -> None:
        """Concatena frame + audio in un MP4 H.264 + AAC con fade in/out."""
        cfg = self.config
        ffmpeg = _ffmpeg_binary()
        # Calcola i timestamp di fade out
        fade_in_dur = max(0, float(getattr(cfg, "video_fade_in_seconds", 0.6)))
        fade_dur = 0.6
        video_fade_out_start = max(0, cfg.duration_seconds - fade_dur)
        audio_fade_out_start = max(0, cfg.duration_seconds - 2)
        video_filters = [
            f"scale={WIDTH}:{HEIGHT}",
        ]
        if fade_in_dur > 0:
            video_filters.append(f"fade=t=in:st=0:d={fade_in_dur}")
        video_filters.extend([
            f"fade=t=out:st={video_fade_out_start}:d={fade_dur}",
            "format=yuv420p",
        ])

        # Per audio sorgente esterno serve farlo finire entro la durata richiesta.
        # Usiamo -t per troncare e -af per il fade.
        cmd = [
            ffmpeg,
            "-y",
            "-loop", "1",
            "-framerate", str(cfg.fps),
            "-i", str(frame_path),
            "-i", str(audio_path),
            "-t", str(cfg.duration_seconds),
            "-vf", ",".join(video_filters),
            "-af", (
                "afade=t=in:st=0:d=0.5,"
                f"afade=t=out:st={audio_fade_out_start}:d=2"
            ),
            "-c:v", "libx264",
            "-preset", cfg.preset,
            "-crf", str(cfg.crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", cfg.audio_bitrate,
            "-movflags", "+faststart",
            "-shortest",
            str(output_path),
        ]

        logger.info(f"Reel: encoding -> {output_path.name}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            logger.error(f"Reel: ffmpeg failed:\n{proc.stderr[-2000:]}")
            raise RuntimeError(f"ffmpeg encoding fallito (exit {proc.returncode})")


# =============================================================================
# PUBLISHER STORIES API (Graph v24.0)
# =============================================================================
class FacebookStoryPublisher:
    """Pubblica un MP4 sulla Storia della Pagina Facebook tramite Stories API."""

    GRAPH_VERSION = "v24.0"

    def __init__(self, page_id: str, page_access_token: str):
        self.page_id = page_id
        self.page_token = page_access_token

    def publish(self, video_path: str, description: str = "") -> Tuple[bool, str]:
        """Esegue il flusso start -> upload -> finish per una video story."""
        try:
            video_file = Path(video_path)
            if not video_file.exists():
                return False, f"Video non trovato: {video_path}"
            file_size = video_file.stat().st_size

            # FASE 1: START
            start = self._start_upload(file_size)
            if not start:
                return False, "Fase START fallita"
            video_id = start.get("video_id")
            upload_url = start.get("upload_url")
            if not (video_id and upload_url):
                return False, f"Risposta START incompleta: {start}"
            logger.info(f"Facebook Story: START ok video_id={video_id}")

            # FASE 2: UPLOAD binario
            if not self._upload_binary(upload_url, video_file, file_size):
                return False, "Fase UPLOAD fallita"
            logger.info(f"Facebook Story: UPLOAD ok ({file_size} bytes)")

            # FASE 3: FINISH + PUBLISH
            ok, info = self._finish_publish(video_id, description=description)
            if not ok:
                return False, f"Fase FINISH fallita: {info}"
            logger.info(f"Facebook Story: FINISH ok, post_id={info}")
            return True, info or video_id

        except requests.RequestException as e:
            return False, f"Errore HTTP: {e}"
        except Exception as e:
            logger.error("Facebook Story: eccezione publish", exc_info=True)
            return False, str(e)

    def _start_upload(self, file_size: int) -> Optional[dict]:
        url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{self.page_id}/video_stories"
        params = {
            "upload_phase": "start",
            "access_token": self.page_token,
        }
        resp = requests.post(url, params=params, timeout=30)
        if resp.status_code != 200:
            logger.error(f"Facebook Story START {resp.status_code}: {resp.text[:500]}")
            return None
        return resp.json()

    def _upload_binary(self, upload_url: str, video_file: Path, file_size: int) -> bool:
        # Stories upload: stesso meccanismo rupload usato dai video verticali Meta.
        headers = {
            "Authorization": f"OAuth {self.page_token}",
            "offset": "0",
            "file_size": str(file_size),
        }
        with open(video_file, "rb") as f:
            resp = requests.post(upload_url, headers=headers, data=f, timeout=300)
        if resp.status_code not in (200, 201):
            logger.error(f"Facebook Story UPLOAD {resp.status_code}: {resp.text[:500]}")
            return False
        # La risposta puo' contenere "success": true
        try:
            data = resp.json()
            return bool(data.get("success", True))
        except Exception:
            return True

    def _finish_publish(self, video_id: str, description: str = "") -> Tuple[bool, str]:
        url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{self.page_id}/video_stories"
        params = {
            "access_token": self.page_token,
            "video_id": video_id,
            "upload_phase": "finish",
        }
        if description:
            params["description"] = description[:2200]
            params["text"] = description[:2200]
        resp = requests.post(url, params=params, timeout=60)
        if resp.status_code != 200 and description:
            logger.warning(
                "Facebook Story FINISH con description/text rifiutato, retry senza testo: %s",
                resp.text[:500],
            )
            fallback = {
                "access_token": self.page_token,
                "video_id": video_id,
                "upload_phase": "finish",
            }
            resp = requests.post(url, params=fallback, timeout=60)
        if resp.status_code != 200:
            return False, f"{resp.status_code}: {resp.text[:500]}"
        try:
            return True, resp.json().get("post_id", resp.text)
        except Exception:
            return True, resp.text


# Compatibilita' con eventuali import esistenti.
FacebookReelPublisher = FacebookStoryPublisher


# =============================================================================
# FACADE: orchestrazione generazione + pubblicazione
# =============================================================================
class FacebookReelManager:
    """Facade che combina generazione locale e pubblicazione su Facebook Stories."""

    def __init__(self):
        self.generator = FacebookReelGenerator()

    def generate(self, articolo) -> Optional[str]:
        """Solo generazione locale (utile per anteprime/dev)."""
        return self.generator.generate(articolo)

    def publish(self, articolo, page_token: str) -> Tuple[bool, str]:
        """
        Genera + pubblica come Storia Facebook. Restituisce (success, error_or_post_id).

        Cleanup: in caso di successo il file MP4 locale viene rimosso
        (Facebook ospita gia' il video). In caso di fallimento il file resta
        in media/reels/<slug>.mp4 per ispezione e retry manuale.
        """
        page_id = getattr(settings, "FACEBOOK_PAGE_ID", "")
        if not page_id:
            return False, "FACEBOOK_PAGE_ID non configurato"
        if not page_token:
            return False, "Page access token mancante"

        video_path = self.generate(articolo)
        if not video_path:
            return False, "Generazione video fallita"

        try:
            from .share_links import build_short_share_url

            short_url = build_short_share_url(articolo, "facebook", "reel")
        except Exception:
            short_url = getattr(settings, "SITE_URL", "https://ombradelportico.it").rstrip("/") + f"/articolo/{articolo.slug}/"
        description = f"{articolo.titolo}\n\nLeggi tutto: {short_url}"

        publisher = FacebookStoryPublisher(page_id, page_token)
        success, info = publisher.publish(video_path, description=description)

        if success:
            self._cleanup_local_file(video_path)
        else:
            logger.info(
                f"Facebook Story: mantengo file locale per debug -> {video_path} "
                f"(motivo fallimento: {info[:200]})"
            )

        return success, info

    @staticmethod
    def _cleanup_local_file(video_path: str) -> None:
        """Rimuove il file MP4 locale dopo pubblicazione riuscita."""
        try:
            p = Path(video_path)
            if p.exists():
                size_kb = p.stat().st_size // 1024
                p.unlink()
                logger.info(f"Facebook Story: file locale rimosso {p.name} ({size_kb} KB liberati)")
        except OSError as e:
            logger.warning(f"Facebook Story: cleanup fallito per {video_path}: {e}")


# Istanza condivisa pronta all\'uso
reel_manager = FacebookReelManager()
