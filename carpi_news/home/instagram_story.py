"""
Storia e Reel automatici Instagram per Ombra del Portico.

Riusa la pipeline di generazione video di home.facebook_reels (stesso template
grafico 1080x1920 con logo, card, badge, titolo, musica royalty-free) ma:
- Salva in media/stories/ o media/ig_reels/ a seconda del target
- CTA "Leggi nel link in bio" (gli URL non sono cliccabili ne' nelle Storie
  ne' nelle caption dei Reel Instagram, solo via Link Sticker che pero' non
  e' esposto via Graph API)
- Pubblica via Instagram Graph API con media_type=STORIES o REELS

Limitazioni Meta (importanti da sapere):
- Link Sticker (lo "swipe-up") nelle Storie NON e' esposto via Graph API.
  Si puo' aggiungere solo dall'app nativa.
- La musica via Music Sticker (catalogo Meta) NON e' esposta via API.
  Quella che usiamo e' musica royalty-free embedded direttamente nel video.

Punti d'ingresso pubblici:
    from home.instagram_story import ig_story_manager, ig_reel_manager
    story_manager.publish(articolo, page_token) -> (ok, info)
    reel_manager.publish(articolo, page_token)  -> (ok, info)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

import requests
from django.conf import settings

from home.facebook_reels import FacebookReelGenerator, ReelConfig

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# GENERATORS (sottoclassi che cambiano solo cta + output dir)
# -----------------------------------------------------------------------------
class InstagramStoryGenerator(FacebookReelGenerator):
    """Genera il video 1080x1920 destinato a Storia Instagram (15s)."""

    def __init__(self, config: Optional[ReelConfig] = None):
        if config is None:
            config = ReelConfig.from_settings()
        # Cartella condivisa con InstagramReelGenerator (stesso CTA, stesso video):
        # cosi' Story e Reel IG riusano lo stesso MP4 invece di rigenerarlo.
        config.output_dir_name = "ig_video"
        config.cta_text = "Link in bio\n{heart} per riceverlo nei DM"
        super().__init__(config)


class InstagramReelGenerator(FacebookReelGenerator):
    """Genera il video 1080x1920 destinato a Reel Instagram (15s).
    Condivide la cartella e il file di output con InstagramStoryGenerator
    perche' i due video sono identici (stesso CTA, stesso template)."""

    def __init__(self, config: Optional[ReelConfig] = None):
        if config is None:
            config = ReelConfig.from_settings()
        config.output_dir_name = "ig_video"
        config.cta_text = "Link in bio\n{heart} per riceverlo nei DM"
        config.video_fade_in_seconds = 0
        super().__init__(config)


# -----------------------------------------------------------------------------
# PUBLISHER (endpoint Instagram /media + /media_publish con media_type)
# -----------------------------------------------------------------------------
class InstagramVideoPublisher:
    """
    Pubblica un video MP4 su Instagram come Storia o Reel.

    Differenza Story vs Reel:
    - media_type=STORIES -> sparisce dopo 24h, va nelle Storie
    - media_type=REELS   -> rimane permanente, va in Feed/Reels (con caption)
    """

    GRAPH_VERSION = "v24.0"

    def __init__(self, ig_user_id: str, page_access_token: str, media_type: str = "STORIES"):
        if media_type not in ("STORIES", "REELS"):
            raise ValueError(f"media_type non valido: {media_type}")
        self.ig_user_id = ig_user_id
        self.page_token = page_access_token
        self.media_type = media_type

    def publish(self, video_url: str, caption: str = "",
                link_comment: str = "",
                location_id: str = "",
                cover_url: str = "",
                audio_name: str = "",
                thumb_offset_ms: int = 1000) -> Tuple[bool, str]:
        """
        Esegue create_container -> wait -> media_publish.

        Args:
            video_url: URL pubblico del video MP4 (Meta deve poterlo scaricare)
            caption: testo della caption (usata solo per REELS, ignorata per STORIES)

        Returns:
            (success, error_or_media_id)
        """
        try:
            # FASE 1: crea container
            create_url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{self.ig_user_id}/media"
            data = {
                "access_token": self.page_token,
                "media_type": self.media_type,
                "video_url": video_url,
            }
            if self.media_type == "REELS" and caption:
                # Caption supportata solo per Reels (max 2200 char)
                data["caption"] = caption[:2200]
                data["share_to_feed"] = "true"

            # Metadati avanzati per discovery (entrambi i media_type)
            if location_id:
                data["location_id"] = location_id
            # Cover e audio_name supportati solo per REELS
            if self.media_type == "REELS":
                if cover_url:
                    data["cover_url"] = cover_url
                elif thumb_offset_ms is not None:
                    # Evita thumbnail nere quando Meta usa il frame 0 del video.
                    data["thumb_offset"] = str(max(0, int(thumb_offset_ms)))
                if audio_name:
                    data["audio_name"] = audio_name[:50]  # limite IG ~50 char

            logger.info(f"IG {self.media_type}: creazione container per {video_url}")
            create_resp = requests.post(create_url, data=data, timeout=30)
            logger.info(f"IG {self.media_type} container: {create_resp.status_code} - {create_resp.text[:500]}")

            if create_resp.status_code != 200 and self.media_type == "REELS":
                optional_keys = {"cover_url", "location_id", "audio_name"}
                if optional_keys.intersection(data):
                    fallback_data = {
                        key: value
                        for key, value in data.items()
                        if key not in optional_keys
                    }
                    if thumb_offset_ms is not None:
                        # Mantiene una thumbnail non nera senza dipendere da cover_url.
                        fallback_data["thumb_offset"] = str(max(0, int(thumb_offset_ms)))
                    logger.warning(
                        "IG Reel: container con metadata extra fallito, retry minimale: %s",
                        create_resp.text[:500],
                    )
                    create_resp = requests.post(create_url, data=fallback_data, timeout=30)
                    logger.info(
                        f"IG REELS fallback container: {create_resp.status_code} - "
                        f"{create_resp.text[:500]}"
                    )

            if create_resp.status_code != 200:
                return False, f"Container fallito: {create_resp.text[:500]}"

            container_id = create_resp.json().get("id")
            if not container_id:
                return False, "Container ID non ricevuto"

            # FASE 2: attendi processing (Instagram impiega tempo per i video)
            # Per i video serve un po' di tempo: 5-15s di solito basta
            ok = self._wait_container_ready(container_id, max_wait_s=60)
            if not ok:
                return False, f"Container {container_id} non e' diventato READY in tempo"

            # FASE 3: pubblica
            publish_url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{self.ig_user_id}/media_publish"
            publish_data = {
                "access_token": self.page_token,
                "creation_id": container_id,
            }
            logger.info(f"IG {self.media_type}: pubblicazione container {container_id}")
            pub_resp = requests.post(publish_url, data=publish_data, timeout=30)
            logger.info(f"IG {self.media_type} publish: {pub_resp.status_code} - {pub_resp.text[:500]}")

            if pub_resp.status_code != 200:
                return False, f"Publish fallito: {pub_resp.text[:500]}"

            media_id = pub_resp.json().get("id", "")

            # Commento auto col link cliccabile (solo Reels; Storie non hanno commenti).
            # Best-effort: fallimento NON deve far fallire il publish.
            if link_comment and self.media_type == "REELS" and media_id:
                ok, info = self._post_link_comment(media_id, link_comment)
                if ok:
                    logger.info(f"IG Reel: commento link pubblicato (id={info})")
                else:
                    logger.warning(f"IG Reel: commento link fallito (non blocca): {info}")

            return True, media_id

        except requests.RequestException as e:
            return False, f"Errore HTTP: {e}"
        except Exception as e:
            logger.error(f"IG {self.media_type}: eccezione publish", exc_info=True)
            return False, str(e)

    def _post_link_comment(self, media_id: str, message: str) -> Tuple[bool, str]:
        """Pubblica un commento dalla Pagina sul Reel IG col link cliccabile.
        Delay 3s perche' subito dopo il publish il Reel potrebbe non essere
        ancora indicizzato per commenti."""
        time.sleep(3)
        url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{media_id}/comments"
        try:
            resp = requests.post(url, data={
                "access_token": self.page_token,
                "message": message[:2200],
            }, timeout=30)
            if resp.status_code == 200:
                return True, resp.json().get("id", "")
            return False, f"{resp.status_code}: {resp.text[:300]}"
        except requests.RequestException as e:
            return False, f"HTTP error: {e}"

    def _wait_container_ready(self, container_id: str, max_wait_s: int = 60,
                               poll_interval_s: int = 5) -> bool:
        """
        Polla lo status del container fino a 'FINISHED' o errore.
        I video Instagram passano da IN_PROGRESS -> FINISHED in ~5-15s.
        """
        url = f"https://graph.facebook.com/{self.GRAPH_VERSION}/{container_id}"
        params = {"access_token": self.page_token, "fields": "status_code,status"}
        elapsed = 0
        while elapsed < max_wait_s:
            time.sleep(poll_interval_s)
            elapsed += poll_interval_s
            try:
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"IG: poll status fallito {resp.status_code}: {resp.text[:200]}")
                    continue
                payload = resp.json()
                status_code = payload.get("status_code", "")
                logger.info(f"IG container {container_id}: status_code={status_code} (elapsed={elapsed}s)")
                if status_code == "FINISHED":
                    return True
                if status_code in ("ERROR", "EXPIRED"):
                    logger.error(f"IG container in stato terminale {status_code}: {payload}")
                    return False
            except requests.RequestException as e:
                logger.warning(f"IG: errore poll status {e}")
        logger.error(f"IG container {container_id}: timeout dopo {max_wait_s}s")
        return False


# -----------------------------------------------------------------------------
# FACADES: orchestrazione generazione + pubblicazione + cleanup
# -----------------------------------------------------------------------------
class _BaseIgVideoManager:
    """Base condivisa tra Story e Reel Instagram."""

    GENERATOR_CLASS = None       # da settare in subclass
    MEDIA_TYPE = None            # 'STORIES' o 'REELS'
    OUTPUT_SUBDIR = None         # 'stories' o 'ig_reels'

    def __init__(self):
        self.generator = self.GENERATOR_CLASS()

    def generate(self, articolo) -> Optional[str]:
        return self.generator.generate(articolo)

    def publish(self, articolo, page_token: str) -> Tuple[bool, str]:
        """Genera video, lo pubblica su Instagram, fa cleanup su successo."""
        ig_user_id = getattr(settings, "INSTAGRAM_ACCOUNT_ID", "")
        if not ig_user_id:
            return False, "INSTAGRAM_ACCOUNT_ID non configurato"
        if not page_token:
            return False, "Page access token mancante"

        video_path = self.generate(articolo)
        if not video_path:
            return False, "Generazione video fallita"

        # URL pubblico per Meta (deve essere accessibile da internet)
        video_filename = Path(video_path).name
        video_url = f"https://ombradelportico.it/media/{self.OUTPUT_SUBDIR}/{video_filename}"

        caption = self._build_caption(articolo)
        # Commento col link cliccabile: solo per Reels (le Storie IG non hanno commenti)
        link_comment = self._build_link_comment(articolo) if self.MEDIA_TYPE == "REELS" else ""

        # Metadati avanzati per discovery.
        # Le Stories IG accettano un set di parametri piu' stretto dei Reel:
        # il location tag viene inviato solo ai Reel per evitare reject del container.
        location_id = getattr(settings, "CARPI_PLACE_ID", "") if self.MEDIA_TYPE == "REELS" else ""
        audio_name = getattr(settings, "INSTAGRAM_REEL_AUDIO_NAME", "") if self.MEDIA_TYPE == "REELS" else ""
        cover_url = self._build_cover_url(articolo) if self.MEDIA_TYPE == "REELS" else ""

        publisher = InstagramVideoPublisher(ig_user_id, page_token, media_type=self.MEDIA_TYPE)
        success, info = publisher.publish(
            video_url,
            caption=caption,
            link_comment=link_comment,
            location_id=location_id,
            cover_url=cover_url,
            audio_name=audio_name,
            thumb_offset_ms=1000,
        )

        if success:
            # Non eliminiamo subito: l'altra piattaforma IG (Story/Reel) potrebbe
            # ancora dover usare lo stesso file (output_dir_name='ig_video' condiviso).
            # Il cleanup periodico (management command 'cleanup_social_media') rimuove
            # i file piu' vecchi del TTL.
            logger.info(f"IG {self.MEDIA_TYPE}: file locale mantenuto per reuse cross-platform: {video_path}")
        else:
            logger.info(
                f"IG {self.MEDIA_TYPE}: mantengo file locale per debug -> {video_path} "
                f"(motivo: {info[:200]})"
            )
        return success, info

    @staticmethod
    def _cleanup_local_file(video_path: str) -> None:
        try:
            p = Path(video_path)
            if p.exists():
                size_kb = p.stat().st_size // 1024
                p.unlink()
                logger.info(f"IG: file locale rimosso {p.name} ({size_kb} KB liberati)")
        except OSError as e:
            logger.warning(f"IG: cleanup fallito per {video_path}: {e}")

    @staticmethod
    def _build_cover_url(articolo) -> str:
        """
        Genera cover thumbnail 1080x1920 per il Reel IG riusando il template
        verticale del video. Meta raccomanda 9:16 per evitare crop/spazi vuoti;
        se il Reel viene condiviso nel feed, Instagram ne ritaglia il centro 1:1.
        """
        try:
            from home.facebook_reels import FacebookReelGenerator
            import tempfile

            config = ReelConfig.from_settings()
            config.cta_text = "Link in bio\n{heart} per riceverlo nei DM"
            tmp_gen = FacebookReelGenerator(config)
            image_path = tmp_gen._resolve_image_path(articolo)
            if not image_path:
                logger.warning(f"IG Reel cover: nessuna immagine valida per {articolo.slug}")
                return ""

            covers_dir = Path(settings.BASE_DIR) / "media" / "ig_reel_covers"
            covers_dir.mkdir(parents=True, exist_ok=True)

            with tempfile.TemporaryDirectory(prefix="ig_reel_cover_") as tmpdir:
                frame_path = tmp_gen._compose_frame(
                    image_path=image_path,
                    title=articolo.titolo,
                    category=articolo.categoria or "Notizie",
                    out_dir=Path(tmpdir),
                )
                final = covers_dir / f"{articolo.slug}_cover.jpg"
                Path(frame_path).replace(final)

            url = f"https://ombradelportico.it/media/ig_reel_covers/{final.name}"
            logger.info(f"IG Reel cover: generata {url}")
            return url
        except Exception as e:
            logger.warning(f"IG Reel cover: generazione fallita ({e})")
            return ""

    @staticmethod
    def _build_link_comment(articolo) -> str:
        """Commento autopubblicato sul Reel IG col link cliccabile."""
        try:
            from home.share_links import build_short_share_url

            url = build_short_share_url(articolo, "instagram", "reel")
        except Exception:
            url = (f"https://ombradelportico.it/articolo/{articolo.slug}/"
                   f"?utm_source=instagram&utm_medium=reel&utm_campaign=share")
        return f"Leggi l'articolo completo qui: {url}"

    @staticmethod
    def _build_caption(articolo) -> str:
        """Caption del Reel IG (ignorata per Storia). Hashtag iperlocali da social_sharing."""
        sommario = (articolo.sommario or "")[:500]
        if articolo.sommario and len(articolo.sommario) > 500:
            sommario += "..."
        try:
            from home.social_sharing import social_manager
            hashtags = social_manager._get_instagram_hashtags(articolo)
        except Exception:
            hashtags = "#OmbraDelPortico #Carpi #NotizieCarpi"
        parts = [
            articolo.titolo,
            "",
            sommario,
            "",
            "Link nel primo commento e in bio",
            "",
            hashtags,
        ]
        return "\n".join(p for p in parts if p is not None)[:2200]


class InstagramStoryManager(_BaseIgVideoManager):
    GENERATOR_CLASS = InstagramStoryGenerator
    MEDIA_TYPE = "STORIES"
    OUTPUT_SUBDIR = "ig_video"


class InstagramReelManager(_BaseIgVideoManager):
    GENERATOR_CLASS = InstagramReelGenerator
    MEDIA_TYPE = "REELS"
    OUTPUT_SUBDIR = "ig_video"


# Istanze condivise pronte all\'uso
ig_story_manager = InstagramStoryManager()
ig_reel_manager = InstagramReelManager()
