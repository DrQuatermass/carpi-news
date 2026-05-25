import logging
from pathlib import Path

from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)


ARTICLE_IMAGE_VARIANTS = {
    "16x9": (1200, 675),
    "4x3": (1200, 900),
    "1x1": (1200, 1200),
}
MAX_IMAGE_SLUG_LENGTH = 80


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
        field_name = f"image_{aspect.replace('x', 'x')}"

        current = getattr(article, field_name, None)
        if current and current.name and output_path.exists() and not force:
            continue

        crop_resize_webp(source_path, output_path, size, quality=quality)
        created[field_name] = relative_name
        logger.info("Variante immagine creata: %s", relative_name)

    if created and article.pk:
        type(article).objects.filter(pk=article.pk).update(**created)
        for field_name, relative_name in created.items():
            getattr(article, field_name).name = relative_name

    return created
