#!/usr/bin/env python
"""
Script diagnostico per verificare perché le immagini responsive non vengono generate
Esegui in produzione per identificare il problema
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
from home.models import Articolo
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def diagnose():
    """Diagnostica il problema delle immagini responsive"""
    print("\n" + "="*80)
    print("DIAGNOSI SISTEMA IMMAGINI RESPONSIVE")
    print("="*80 + "\n")

    # 1. Verifica PIL/Pillow
    print("[1] Verifica installazione PIL/Pillow...")
    try:
        from PIL import Image
        print(f"    [OK] PIL/Pillow installato: {Image.__version__ if hasattr(Image, '__version__') else 'versione sconosciuta'}")
    except ImportError as e:
        print(f"    [ERROR] PIL/Pillow NON installato: {e}")
        return

    # 2. Verifica MEDIA_ROOT
    print(f"\n[2] Verifica MEDIA_ROOT...")
    print(f"    MEDIA_ROOT: {settings.MEDIA_ROOT}")
    print(f"    Esiste? {Path(settings.MEDIA_ROOT).exists()}")
    print(f"    Scrivibile? {os.access(settings.MEDIA_ROOT, os.W_OK)}")

    # 3. Verifica directory uploaded
    uploaded_dir = Path(settings.MEDIA_ROOT) / 'images' / 'uploaded'
    print(f"\n[3] Verifica directory uploaded...")
    print(f"    Path: {uploaded_dir}")
    print(f"    Esiste? {uploaded_dir.exists()}")
    if uploaded_dir.exists():
        print(f"    Scrivibile? {os.access(uploaded_dir, os.W_OK)}")

    # 4. Conta articoli con foto_upload
    print(f"\n[4] Analisi articoli con immagini...")
    total_with_upload = Articolo.objects.filter(foto_upload__isnull=False, foto_upload__gt='').count()
    print(f"    Articoli con foto_upload: {total_with_upload}")

    # 5. Verifica esistenza file per campione di articoli
    print(f"\n[5] Verifica esistenza file (campione ultimi 20 articoli)...")
    recent_articles_query = Articolo.objects.filter(
        foto_upload__isnull=False,
        foto_upload__gt=''
    ).order_by('-data_creazione')
    recent_articles = list(recent_articles_query[:20])

    existing_files = 0
    missing_files = 0
    files_with_responsive = 0
    files_without_responsive = 0

    for article in recent_articles:
        if not article.foto_upload:
            continue

        image_path = Path(article.foto_upload.path)
        exists = image_path.exists()

        if exists:
            existing_files += 1
            # Verifica se ha versioni responsive
            has_400w = (image_path.parent / f"{image_path.stem}-400w.webp").exists()
            has_600w = (image_path.parent / f"{image_path.stem}-600w.webp").exists()
            has_800w = (image_path.parent / f"{image_path.stem}-800w.webp").exists()

            if has_400w or has_600w or has_800w:
                files_with_responsive += 1
                print(f"    [OK] {image_path.name} - Responsive: {has_400w}/{has_600w}/{has_800w}")
            else:
                files_without_responsive += 1
                print(f"    [MISS] {image_path.name} - Nessuna versione responsive")
        else:
            missing_files += 1
            print(f"    [ERROR] File non trovato: {image_path}")

    print(f"\n    Riepilogo campione:")
    print(f"      - File esistenti: {existing_files}")
    print(f"      - File mancanti: {missing_files}")
    print(f"      - Con versioni responsive: {files_with_responsive}")
    print(f"      - Senza versioni responsive: {files_without_responsive}")

    # 6. Verifica segnali Django
    print(f"\n[6] Verifica segnali Django...")
    from django.db.models.signals import post_save

    receivers = post_save._live_receivers(Articolo)
    print(f"    Segnali post_save registrati per Articolo: {len(receivers)}")

    # Cerca il signal generate_responsive_images_on_save
    found_signal = False
    for receiver in receivers:
        receiver_name = receiver.__name__ if hasattr(receiver, '__name__') else str(receiver)
        if 'responsive' in receiver_name.lower():
            found_signal = True
            print(f"    [OK] Trovato signal: {receiver_name}")
            break

    if found_signal:
        # Mostra tutti i signal registrati
        all_receivers = [r.__name__ if hasattr(r, '__name__') else str(r) for r in receivers]
        print(f"    [INFO] Altri signal registrati: {', '.join(all_receivers)}")
    else:
        print(f"    [WARNING] Signal 'generate_responsive_images_on_save' non trovato!")

    # 7. Test manuale generazione versioni responsive
    print(f"\n[7] Test generazione manuale su un file...")
    test_article = recent_articles[0] if recent_articles else None
    if test_article and test_article.foto_upload:
        test_path = Path(test_article.foto_upload.path)
        if test_path.exists():
            print(f"    File di test: {test_path.name}")
            print(f"    Dimensioni: {test_path.stat().st_size / 1024:.1f} KB")

            # Prova a generare versioni responsive
            from home.signals import generate_responsive_versions
            try:
                created = generate_responsive_versions(str(test_path), widths=[400], quality=75)
                if created:
                    print(f"    [OK] Test generazione riuscito! Creati: {len(created)} file")
                else:
                    print(f"    [INFO] Nessun file creato (probabilmente già esistenti o immagine troppo piccola)")
            except Exception as e:
                print(f"    [ERROR] Test generazione fallito: {e}")
        else:
            print(f"    [ERROR] File di test non trovato")
    else:
        print(f"    [INFO] Nessun articolo disponibile per il test")

    # 8. Verifica permessi
    print(f"\n[8] Verifica permessi scrittura...")
    if uploaded_dir.exists():
        test_file = uploaded_dir / ".test_write_permission"
        try:
            test_file.touch()
            test_file.unlink()
            print(f"    [OK] Directory scrivibile")
        except Exception as e:
            print(f"    [ERROR] Impossibile scrivere: {e}")

    print("\n" + "="*80)
    print("DIAGNOSI COMPLETATA")
    print("="*80 + "\n")


if __name__ == '__main__':
    diagnose()
