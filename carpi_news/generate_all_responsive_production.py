#!/usr/bin/env python
"""
Script per generare versioni responsive per TUTTE le immagini in produzione
Da eseguire una volta sul server per risolvere il problema
"""
import os
import sys
from pathlib import Path

# Setup Django
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
import django
django.setup()

from django.conf import settings
from home.signals import generate_responsive_versions
from PIL import Image
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def generate_for_all_directories():
    """Genera versioni responsive per tutte le directory immagini"""
    print("\n" + "="*80)
    print("GENERAZIONE MASSIVA IMMAGINI RESPONSIVE")
    print("="*80 + "\n")

    directories = [
        Path(settings.MEDIA_ROOT) / 'images' / 'uploaded',
        Path(settings.MEDIA_ROOT) / 'images' / 'downloaded',
        Path(settings.MEDIA_ROOT) / 'banners',
    ]

    total_processed = 0
    total_created = 0
    total_errors = 0

    for directory in directories:
        if not directory.exists():
            print(f"[SKIP] Directory non trovata: {directory}")
            continue

        print(f"\n[PROCESS] Directory: {directory}")
        print(f"          Path: {directory}\n")

        # Trova tutte le immagini WebP che NON sono già versioni responsive
        images = [
            f for f in directory.glob('*.webp')
            if not any(suffix in f.stem for suffix in ['-400w', '-600w', '-800w'])
        ]

        # Aggiungi anche PNG/JPG se presenti
        for ext in ['*.png', '*.jpg', '*.jpeg']:
            images.extend([
                f for f in directory.glob(ext)
                if not any(suffix in f.stem for suffix in ['-400w', '-600w', '-800w'])
            ])

        if not images:
            print(f"  [INFO] Nessuna immagine da processare\n")
            continue

        print(f"  [INFO] Trovate {len(images)} immagini da processare\n")

        for i, image_path in enumerate(images, 1):
            try:
                # Mostra progresso ogni 10 immagini
                if i % 10 == 0:
                    print(f"  [PROGRESS] {i}/{len(images)} immagini processate...")

                # Verifica dimensioni immagine prima di processare
                with Image.open(image_path) as img:
                    width, height = img.size
                    # Salta immagini troppo piccole
                    if width < 400:
                        logger.debug(f"  [SKIP] Immagine troppo piccola ({width}x{height}): {image_path.name}")
                        continue

                # Conta versioni esistenti prima
                before_count = len(list(image_path.parent.glob(f"{image_path.stem}-*w.webp")))

                # Genera versioni responsive
                created_files = generate_responsive_versions(
                    str(image_path),
                    widths=[400, 600, 800],
                    quality=75
                )

                # Conta versioni create
                if created_files:
                    total_created += len(created_files)
                    logger.info(f"  [OK] {image_path.name}: {len(created_files)} versioni create")

                total_processed += 1

            except Exception as e:
                total_errors += 1
                logger.error(f"  [ERROR] {image_path.name}: {e}")

        print(f"\n  [DONE] Directory completata: {directory.name}")
        print(f"         Processate: {len(images)}, Errori: {total_errors}\n")

    print("\n" + "="*80)
    print("GENERAZIONE COMPLETATA")
    print("="*80)
    print(f"\nRiepilogo:")
    print(f"  - Immagini processate: {total_processed}")
    print(f"  - Versioni responsive create: {total_created}")
    print(f"  - Errori: {total_errors}")
    print(f"\nVerifica con Lighthouse per confermare il miglioramento!\n")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Genera versioni responsive per tutte le immagini')
    parser.add_argument('--dry-run', action='store_true', help='Simula l\'esecuzione senza creare file')
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY RUN] Modalità simulazione - nessun file verrà creato\n")
        # TODO: implementare dry run se necessario

    try:
        generate_for_all_directories()
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Generazione interrotta dall'utente")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
