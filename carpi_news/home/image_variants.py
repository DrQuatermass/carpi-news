import logging
import io
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
import requests
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


ARTICLE_IMAGE_VARIANTS = {
    "16x9": (1200, 675),
    "4x3": (1200, 900),
    "1x1": (1200, 1200),
}
ARTICLE_IMAGE_VARIANT_FIELDS = {
    "16x9": "image_16x9",
    "4x3": "image_4x3",
    "1x1": "image_1x1",
}
MAX_IMAGE_SLUG_LENGTH = 80


class ArticleImageVariantError(Exception):
    pass


def _to_rgb(image):
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        if image.mode in ("RGBA", "LA"):
            background.paste(image, mask=image.split()[-1])
        else:
            background.paste(image)
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _smart_crop_box(image, target_width, target_height):
    try:
        import smartcrop

        result = smartcrop.SmartCrop().crop(image, target_width, target_height)
        top_crop = result.get("top_crop") or {}
        x = int(top_crop["x"])
        y = int(top_crop["y"])
        width = int(top_crop["width"])
        height = int(top_crop["height"])
        return (x, y, x + width, y + height)
    except Exception:
        return None


def _center_crop_box(image_width, image_height, target_ratio):
    source_ratio = image_width / image_height
    if source_ratio > target_ratio:
        crop_width = int(image_height * target_ratio)
        left = (image_width - crop_width) // 2
        return (left, 0, left + crop_width, image_height)

    crop_height = int(image_width / target_ratio)
    top = (image_height - crop_height) // 2
    return (0, top, image_width, top + crop_height)


def crop_resize_webp(source_path, output_path, size, quality=82):
    target_width, target_height = size
    target_ratio = target_width / target_height

    with Image.open(source_path) as img:
        img = _to_rgb(img)
        crop_box = _smart_crop_box(img, target_width, target_height)
        if crop_box is None:
            crop_box = _center_crop_box(img.width, img.height, target_ratio)

        cropped = img.crop(crop_box)
        resized = cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        resized.save(output_path, "WebP", quality=quality, method=6)


def get_article_source_image_path(article):
    if article.foto_upload:
        try:
            path = Path(article.foto_upload.path)
            if path.exists():
                return path
        except (ValueError, OSError):
            pass

    if article.foto and str(article.foto).startswith("/media/"):
        path = Path(settings.MEDIA_ROOT) / str(article.foto).replace("/media/", "", 1)
        if path.exists():
            return path

    return None


def get_article_variant_path(article, aspect):
    image_slug = (article.slug or "")[:MAX_IMAGE_SLUG_LENGTH].rstrip("-")
    if not image_slug:
        return None
    return Path(settings.MEDIA_ROOT) / "images" / "articles" / f"{image_slug}-{aspect}.webp"


def missing_article_image_variants(article):
    missing = []
    for aspect, field_name in ARTICLE_IMAGE_VARIANT_FIELDS.items():
        field = getattr(article, field_name, None)
        expected_path = get_article_variant_path(article, aspect)
        if not expected_path:
            missing.append(field_name)
            continue
        if not field or not getattr(field, "name", "") or not expected_path.exists():
            missing.append(field_name)
    return missing


def has_all_article_image_variants(article):
    return not missing_article_image_variants(article)


def generate_article_image_variants(article, source_path=None, force=False, quality=82):
    source_path = Path(source_path) if source_path else get_article_source_image_path(article)
    if not source_path or not source_path.exists():
        logger.info("Nessuna immagine locale per varianti articolo %s", article.pk)
        return {}

    if not article.slug:
        logger.warning("Impossibile generare varianti immagine senza slug per articolo %s", article.pk)
        return {}

    created = {}
    output_dir = Path(settings.MEDIA_ROOT) / "images" / "articles"
    image_slug = article.slug[:MAX_IMAGE_SLUG_LENGTH].rstrip("-")

    for aspect, size in ARTICLE_IMAGE_VARIANTS.items():
        relative_name = f"images/articles/{image_slug}-{aspect}.webp"
        output_path = output_dir / f"{image_slug}-{aspect}.webp"
        field_name = ARTICLE_IMAGE_VARIANT_FIELDS[aspect]

        current = getattr(article, field_name, None)
        if current and current.name and output_path.exists() and not force:
            continue

        try:
            crop_resize_webp(source_path, output_path, size, quality=quality)
        except (OSError, UnidentifiedImageError) as exc:
            raise ArticleImageVariantError(
                f"Impossibile generare variante {aspect} per articolo {article.pk} da {source_path}: {exc}"
            ) from exc
        created[field_name] = relative_name
        logger.info("Variante immagine creata: %s", relative_name)

    if created and article.pk:
        type(article).objects.filter(pk=article.pk).update(**created)
        for field_name, relative_name in created.items():
            getattr(article, field_name).name = relative_name

    return created


def localize_remote_article_image(article, timeout=15, quality=75):
    image_url = (article.foto or "").strip()
    if not image_url.startswith(("http://", "https://")):
        return None

    if not article.slug:
        logger.warning("Impossibile salvare immagine remota senza slug per articolo %s", article.pk)
        return None

    filename = f"{article.slug[:MAX_IMAGE_SLUG_LENGTH].rstrip('-')}-original.webp"
    output_dir = Path(settings.MEDIA_ROOT) / "images" / "downloaded"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    media_url = f"/media/images/downloaded/{filename}"

    if output_path.exists():
        article.foto = media_url
        if article.pk:
            type(article).objects.filter(pk=article.pk).update(foto=media_url)
        return output_path

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(image_url, timeout=timeout, headers=headers)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Download immagine remota fallito per articolo %s: %s", article.pk, exc)
        return None

    content_type = response.headers.get("content-type", "")
    parsed_path = urlparse(image_url).path.lower()
    if "image" not in content_type and not parsed_path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        logger.warning("URL immagine remota non riconosciuto per articolo %s: %s", article.pk, image_url)
        return None

    try:
        with Image.open(io.BytesIO(response.content)) as img:
            img = _to_rgb(img)
            img.save(output_path, "WebP", quality=quality, method=6)
    except (OSError, UnidentifiedImageError) as exc:
        logger.warning("Immagine remota non processabile per articolo %s: %s", article.pk, exc)
        return None

    article.foto = media_url
    if article.pk:
        type(article).objects.filter(pk=article.pk).update(foto=media_url)
    logger.info("Immagine remota salvata localmente per articolo %s: %s", article.pk, media_url)
    return output_path


def ensure_article_image_variants(article, force=False):
    """Garantisce immagine locale e varianti multi-aspect prima della pubblicazione/social."""
    if has_all_article_image_variants(article) and not force:
        return {}

    source_path = get_article_source_image_path(article)
    if source_path is None:
        source_path = localize_remote_article_image(article)

    if source_path is None:
        logger.info("Nessuna immagine locale disponibile per articolo %s", article.pk)
        return {}

    return generate_article_image_variants(article, source_path=source_path, force=force)
