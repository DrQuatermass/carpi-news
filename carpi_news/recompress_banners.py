"""
Script una-tantum per ricomprimere i banner esistenti con quality=70
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
django.setup()

from admin_panel.models import Banner
from PIL import Image
import io

def recompress_banner(banner):
    """Ricomprimi un banner con quality=70"""
    if not banner.image:
        return False

    try:
        # Apri immagine
        img = Image.open(banner.image.path)
        original_size = os.path.getsize(banner.image.path)

        # Converti in RGB se necessario
        if img.mode in ('RGBA', 'LA', 'P'):
            if img.mode == 'P':
                img = img.convert('RGBA')
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Salva come WebP con quality=70
        output_path = banner.image.path
        img.save(output_path, format='WEBP', quality=70, method=6)

        new_size = os.path.getsize(output_path)
        saved = original_size - new_size
        saved_percent = (saved / original_size) * 100 if original_size > 0 else 0

        print(f"OK {banner.title}: {original_size/1024:.1f}KB -> {new_size/1024:.1f}KB (risparmiato {saved_percent:.1f}%)")
        return True

    except Exception as e:
        print(f"ERRORE {banner.title}: {e}")
        return False

if __name__ == '__main__':
    print("Ricompressione banner WebP con quality=70\n")

    banners = Banner.objects.filter(image__isnull=False)
    total = banners.count()
    success = 0

    for i, banner in enumerate(banners, 1):
        print(f"[{i}/{total}] ", end="")
        if recompress_banner(banner):
            success += 1

    print(f"\nOK Completato: {success}/{total} banner ricompressi")
