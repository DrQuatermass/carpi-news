"""
Image Proxy per ottimizzare immagini esterne
Scarica, ridimensiona, converte in WebP e cachea le immagini da fonti esterne
"""
import logging
import requests
import time
from io import BytesIO
from PIL import Image
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseServerError
from django.core.cache import cache
from django.conf import settings
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET
from urllib.parse import unquote
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

# Timeout per richieste HTTP (secondi) - ridotto per migliorare LCP
REQUEST_TIMEOUT = 5

# Qualità WebP (0-100) - ottimizzata per compressione/qualità
WEBP_QUALITY = 65

# Dimensioni massime cache (10 MB per immagine)
MAX_CACHE_SIZE = 10 * 1024 * 1024

# Cache su disco per immagini proxy già processate
PROXY_CACHE_TTL = 86400
PROXY_CACHE_DIR = Path(settings.MEDIA_ROOT) / 'proxy_cache'
PROXY_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cache_key(url, width=None, quality=None):
    """
    Genera chiave cache univoca basata su URL e parametri
    """
    key_parts = [url]
    if width:
        key_parts.append(f"w{width}")
    if quality:
        key_parts.append(f"q{quality}")

    key_string = "_".join(key_parts)
    hash_key = hashlib.md5(key_string.encode()).hexdigest()
    return f"image_proxy_{hash_key}"


def get_cached_proxy_path(url: str, width: int = None, quality: int = WEBP_QUALITY) -> Path:
    key = hashlib.md5(f"{url}:{width}:{quality}".encode()).hexdigest()
    return PROXY_CACHE_DIR / f"{key}.webp"


def is_fresh_cache_file(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < PROXY_CACHE_TTL


def download_and_optimize_image(url, width=None, quality=WEBP_QUALITY):
    """
    Scarica e ottimizza un'immagine esterna

    Args:
        url: URL dell'immagine sorgente
        width: Larghezza target (opzionale, mantiene aspect ratio)
        quality: Qualità WebP (0-100)

    Returns:
        tuple: (image_data: bytes, content_type: str)
    """
    try:
        # Download dell'immagine con connection pooling e compressione
        logger.info(f"Downloading image: {url[:100]}...")

        # Session con connection pooling per riutilizzare connessioni TCP
        session = requests.Session()

        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; OmbraDelPortico/1.0; +https://ombradelportico.it)',
                'Accept': 'image/webp,image/avif,image/*,*/*;q=0.8',  # Preferisce immagini già ottimizzate
                'Accept-Encoding': 'gzip, deflate, br'  # Compressione HTTP
            },
            stream=True  # Streaming per grandi immagini
        )
        response.raise_for_status()

        # Verifica dimensione
        content_length = len(response.content)
        if content_length > MAX_CACHE_SIZE:
            logger.warning(f"Image too large: {content_length / 1024 / 1024:.1f}MB")
            return None, None

        # Apri immagine
        img = Image.open(BytesIO(response.content))
        original_size = img.size
        original_format = img.format

        logger.info(f"Original image: {original_size[0]}x{original_size[1]} {original_format}")

        # Ridimensiona se necessario
        if width and img.width > width:
            ratio = width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((width, new_height), Image.Resampling.LANCZOS)
            logger.info(f"Resized to: {width}x{new_height}")

        # Converti in RGB se necessario (per PNG con trasparenza)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background

        # Converti in WebP con compressione ottimizzata
        webp_io = BytesIO()
        # method=4: bilancia velocità/compressione (invece di 6 che è più lento)
        img.save(webp_io, 'WebP', quality=quality, method=4)
        webp_data = webp_io.getvalue()

        # Log risparmio
        savings = content_length - len(webp_data)
        savings_percent = (savings / content_length) * 100 if content_length > 0 else 0
        logger.info(
            f"Optimized: {content_length/1024:.1f}KB -> {len(webp_data)/1024:.1f}KB "
            f"(saved {savings_percent:.1f}%)"
        )

        return webp_data, 'image/webp'

    except requests.RequestException as e:
        logger.error(f"Request error: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Image processing error: {e}")
        return None, None


@require_GET
@cache_control(public=True, max_age=86400)
def image_proxy_view(request):
    """
    View per proxy immagini esterne con ottimizzazione e cache

    Query params:
        - url: URL dell'immagine (required)
        - w: larghezza target (optional)
        - q: qualità WebP 0-100 (optional, default 75)

    Example:
        /image-proxy/?url=https://example.com/image.jpg&w=600&q=80
    """
    # Ottieni parametri
    url = request.GET.get('url')
    if not url:
        return HttpResponseBadRequest("Missing 'url' parameter")

    # Decodifica URL
    url = unquote(url)

    # Validazione URL (sicurezza)
    if not url.startswith(('http://', 'https://')):
        return HttpResponseBadRequest("Invalid URL")

    # Blocca URL locali (sicurezza - previene SSRF)
    if any(blocked in url.lower() for blocked in ['localhost', '127.0.0.1', '0.0.0.0', '192.168.', '10.0.']):
        return HttpResponseBadRequest("Invalid URL")

    # Parametri opzionali
    try:
        width = int(request.GET.get('w', 0)) or None
        quality = int(request.GET.get('q', WEBP_QUALITY))
        quality = max(1, min(100, quality))  # Clamp 1-100
    except ValueError:
        return HttpResponseBadRequest("Invalid parameters")

    cached_path = get_cached_proxy_path(url, width, quality)
    if is_fresh_cache_file(cached_path):
        response = HttpResponse(cached_path.read_bytes(), content_type='image/webp')
        response['X-Cache'] = 'DISK-HIT'
        response['Cache-Control'] = 'public, max-age=86400'
        response['Vary'] = 'Accept'
        return response

    # Genera chiave cache
    cache_key = get_cache_key(url, width, quality)

    # Controlla cache
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.debug(f"Cache hit: {cache_key}")
        image_data, content_type = cached_data
        response = HttpResponse(image_data, content_type=content_type)
        response['X-Cache'] = 'HIT'
        response['Cache-Control'] = 'public, max-age=86400'
        response['Vary'] = 'Accept'
        return response

    # Cache miss: scarica e ottimizza
    logger.info(f"Cache miss: {cache_key}")
    image_data, content_type = download_and_optimize_image(url, width, quality)

    if image_data is None:
        return HttpResponseServerError("Failed to process image")

    # Salva in cache (30 giorni)
    cache.set(cache_key, (image_data, content_type), timeout=2592000)
    if content_type == 'image/webp':
        try:
            cached_path.write_bytes(image_data)
        except Exception as e:
            logger.warning(f"Disk cache write failed for proxy image: {e}")

    # Ritorna immagine ottimizzata
    response = HttpResponse(image_data, content_type=content_type)
    response['X-Cache'] = 'MISS'
    response['Cache-Control'] = 'public, max-age=86400'
    response['Vary'] = 'Accept'  # Cache varia per tipo Accept
    return response
