#!/usr/bin/env python
"""
Script per creare versioni responsive delle immagini uploaded esistenti
Genera versioni 400w, 600w, 800w per tutte le immagini .webp in media/images/uploaded/
"""
import os
import sys
from pathlib import Path
from PIL import Image

# Aggiungi il path del progetto Django al sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
import django
django.setup()

from django.conf import settings


def create_responsive_versions(image_path, widths=[400, 600, 800]):
    """
    Crea versioni responsive di un'immagine

    Args:
        image_path: Path dell'immagine originale
        widths: Lista di larghezze da generare (default: [400, 600, 800])
    """
    try:
        # Apri l'immagine
        with Image.open(image_path) as img:
            # Converti in RGB se necessario (per immagini con alpha channel)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            original_width, original_height = img.size

            # Genera versioni responsive
            for target_width in widths:
                # Salta se l'immagine è più piccola della larghezza target
                if original_width <= target_width:
                    continue

                # Calcola altezza proporzionale
                aspect_ratio = original_height / original_width
                target_height = int(target_width * aspect_ratio)

                # Crea nome file responsive
                image_name = image_path.stem
                responsive_name = f"{image_name}-{target_width}w.webp"
                responsive_path = image_path.parent / responsive_name

                # Salta se esiste già
                if responsive_path.exists():
                    print(f"   [SKIP] Esiste già: {responsive_name}")
                    continue

                # Ridimensiona e salva
                resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                resized.save(responsive_path, 'WEBP', quality=85, method=6)

                # Calcola risparmio
                original_size = image_path.stat().st_size
                new_size = responsive_path.stat().st_size
                saving_kb = (original_size - new_size) / 1024

                print(f"   [OK] Creato: {responsive_name} ({target_width}x{target_height}) - Risparmio: {saving_kb:.1f} KB")

    except Exception as e:
        print(f"   [ERROR] Errore: {e}")


def main():
    """Processa tutte le immagini uploaded"""
    uploaded_dir = Path(settings.MEDIA_ROOT) / 'images' / 'uploaded'

    if not uploaded_dir.exists():
        print(f"[ERROR] Directory non trovata: {uploaded_dir}")
        return

    # Trova tutte le immagini .webp che NON sono già versioni responsive
    images = [
        f for f in uploaded_dir.glob('*.webp')
        if not any(suffix in f.stem for suffix in ['-400w', '-600w', '-800w'])
    ]

    if not images:
        print("[INFO] Nessuna immagine da processare")
        return

    print(f"[INFO] Trovate {len(images)} immagini da processare\n")

    total_processed = 0
    total_created = 0

    for image_path in images:
        print(f"[PROCESS] Elaborazione: {image_path.name}")

        # Conta file esistenti prima
        before_count = len(list(image_path.parent.glob(f"{image_path.stem}-*w.webp")))

        create_responsive_versions(image_path)

        # Conta file esistenti dopo
        after_count = len(list(image_path.parent.glob(f"{image_path.stem}-*w.webp")))
        created = after_count - before_count
        total_created += created
        total_processed += 1

        print()

    print(f"\n[DONE] Completato!")
    print(f"   Immagini processate: {total_processed}")
    print(f"   Versioni responsive create: {total_created}")
    print(f"   Media directory: {uploaded_dir}")


if __name__ == '__main__':
    main()
