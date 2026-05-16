"""
Generazione e pubblicazione automatica di Reel Facebook per Ombra del Portico.

Il modulo si occupa di:
1. Comporre un MP4 verticale 1080x1920 a partire da un Articolo (foto + titolo + CTA + logo).
2. Aggiungere una traccia audio royalty-free presa da `FACEBOOK_REEL_MUSIC_DIR`
   (fallback su pad ambient procedurale se nessun file e' disponibile).
3. Pubblicare il video sulla Pagina Facebook tramite Reels Publishing API (Graph v24.0).

Punto di ingresso pubblico:
    from home.facebook_reels import FacebookReelManager
    manager = FacebookReelManager()
    path = manager.generate(articolo)             # solo generazione locale
    result = manager.publish(articolo)            # generazione + upload + publish

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


def _logo_path() -> Path:
    """Path del logo principale (illustrazione portico + wordmark + payoff)."""
    return _project_base_dir() / "home" / "static" / "home" / "images" / "portico_logo.png"


def _music_dir() -> Path:
    """Cartella della libreria musicale royalty-free."""
    custom = getattr(settings, "FACEBOOK_REEL_MUSIC_DIR", "")
    if custom:
        return Path(custom)
    return _project_base_dir() / "media" / "reel_music"


def _reels_output_dir() -> Path:
    """Cartella dove salvare i Reel generati (puliti periodicamente)."""
    d = _project_base_dir() / "media" / "reels"
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
    def generate(self, articolo) -> Optional[str]:
        """Genera il Reel per un articolo. Restituisce il path al MP4 oppure None se fallisce."""
        try:
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
                output_mp4 = _reels_output_dir() / f"{articolo.slug}.mp4"
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
        if not articolo.foto:
            return None

        foto = str(articolo.foto)

        # URL remoto: scarica
        if foto.startswith("http://") or foto.startswith("https://"):
            return self._download_image(foto)

        # Path relativo a MEDIA_URL: convertilo in path filesystem
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

        # CTA in basso
        cta_font = self._load_font(46)
        cta = "Leggi su ombradelportico.it"
        bbox = draw.textbbox((0, 0), cta, font=cta_font)
        cw = bbox[2] - bbox[0]
        cx = (WIDTH - cw) // 2
        cy = HEIGHT - 200
        pad_x = 36
        pad_y = 18
        draw.rounded_rectangle(
            [(cx - pad_x, cy - pad_y), (cx + cw + pad_x, cy + 60 + pad_y)],
            radius=40, fill=WHITE + (235,)
        )
        draw.text((cx, cy), cta, font=cta_font, fill=DARK_BG + (255,))

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
        fade_dur = 0.6
        video_fade_out_start = max(0, cfg.duration_seconds - fade_dur)
        audio_fade_out_start = max(0, cfg.duration_seconds - 2)

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
            "-vf", (
                f"scale={WIDTH}:{HEIGHT},"
                f"fade=t=in:st=0:d=0.6,"
                f"fade=t=out:st={video_fade_out_start}:d={fade_dur},"
                f"format=yuv420p"
            ),
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
# PUBLISHER REELS API (Graph v24.0)
# =============================================================================
class FacebookReelPublisher:
    """Publica un MP4 sulla Pagina Facebook tramite Reels Publishing API (3 fasi)."""

    GRAPH_VERSION = "v24.0"

    def __init__(self, page_id: str, page_access_token: str):
        self.page_id = page_id
        self.page_token = page_access_token

    def publish(self, video_path: str, description: str) -> Tuple[bool, str]:
        """
        Esegue il flusso start -> upload -> finish.
        Restituisce (success, error_message_or_post_id).
        """
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
            logger.info(f"Reel: START ok video_id={video_id}")

            # FASE 2: UPLOAD binario
            if not self._upload_binary(upload_url, video_file, file_size):
                return False, "Fase UPLOAD fallita"
            logger.info(f"Reel: UPLOAD ok ({file_size} bytes)")

            # FASE 3: FINISH + PUBLISH
            ok, info = self._finish_publish(video_id, description)
            if not ok:
                return False, f"Fase FINISH fallita: {info}"
            logger.info(f"Reel: FINISH ok, video_id={video_id}")
            return True, video_id

        except requests.RequestException as e:
            return False, f"Errore HTTP: {e}"
        except Exception as e:
            logger.error("Reel: eccezione publish", exc_info=True)
            return False, str(e)

    def _start_upload(self, file_size: int) -> Optional[dict]:
        url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{self.page_id}/video_reels"
        params = {
            "upload_phase": "start",
            "access_token": self.page_token,
        }
        resp = requests.post(url, params=params, timeout=30)
        if resp.status_code != 200:
            logger.error(f"Reel START {resp.status_code}: {resp.text[:500]}")
            return None
        return resp.json()

    def _upload_binary(self, upload_url: str, video_file: Path, file_size: int) -> bool:
        # Reels Hosted Upload: POST con body binario e headers specifici
        headers = {
            "Authorization": f"OAuth {self.page_token}",
            "offset": "0",
            "file_size": str(file_size),
        }
        with open(video_file, "rb") as f:
            resp = requests.post(upload_url, headers=headers, data=f, timeout=300)
        if resp.status_code not in (200, 201):
            logger.error(f"Reel UPLOAD {resp.status_code}: {resp.text[:500]}")
            return False
        # La risposta puo' contenere "success": true
        try:
            data = resp.json()
            return bool(data.get("success", True))
        except Exception:
            return True

    def _finish_publish(self, video_id: str, description: str) -> Tuple[bool, str]:
        url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{self.page_id}/video_reels"
        params = {
            "access_token": self.page_token,
            "video_id": video_id,
            "upload_phase": "finish",
            "video_state": "PUBLISHED",
            "description": description[:2200],  # limite description Reels
        }
        resp = requests.post(url, params=params, timeout=60)
        if resp.status_code != 200:
            return False, f"{resp.status_code}: {resp.text[:500]}"
        return True, resp.text


# =============================================================================
# FACADE: orchestrazione generazione + pubblicazione
# =============================================================================
class FacebookReelManager:
    """Facade che combina generazione locale e pubblicazione su Facebook."""

    def __init__(self):
        self.generator = FacebookReelGenerator()

    def generate(self, articolo) -> Optional[str]:
        """Solo generazione locale (utile per anteprime/dev)."""
        return self.generator.generate(articolo)

    def publish(self, articolo, page_token: str) -> Tuple[bool, str]:
        """
        Genera + pubblica. Restituisce (success, error_or_video_id).

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

        description = self._build_description(articolo)
        publisher = FacebookReelPublisher(page_id, page_token)
        success, info = publisher.publish(video_path, description)

        if success:
            self._cleanup_local_file(video_path)
        else:
            logger.info(
                f"Reel: mantengo file locale per debug -> {video_path} "
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
                logger.info(f"Reel: file locale rimosso {p.name} ({size_kb} KB liberati)")
        except OSError as e:
            logger.warning(f"Reel: cleanup fallito per {video_path}: {e}")

    @staticmethod
    def _build_description(articolo) -> str:
        """Caption del Reel (max 2200 caratteri, mostrata accanto al video).

        L'URL include ?social_share=1 come il resto del sistema (vedi
        social_sharing.SocialMediaManager._get_social_article_url): serve a
        forzare il dispatch dei metadata Open Graph dall'articolo invece che
        da pagine evento o altre risorse derivate.
        """
        url = f"https://ombradelportico.it/articolo/{articolo.slug}/?social_share=1"
        sommario = (articolo.sommario or "")[:600]
        if articolo.sommario and len(articolo.sommario) > 600:
            sommario += "..."
        parts = [
            articolo.titolo,
            "",
            sommario,
            "",
            f"Leggi l'articolo completo: {url}",
            "",
            "#OmbraDelPortico #Carpi #NotizieCarpi",
        ]
        return "\n".join(p for p in parts if p is not None)


# Istanza condivisa pronta all'uso
reel_manager = FacebookReelManager()
