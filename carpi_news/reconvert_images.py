#!/usr/bin/env python
"""
Script per riconvertire immagini WebP esistenti con nuovi parametri
(qualità 65%, max 800px invece di 75%, 1200px)
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
django.setup()

from home.models import Articolo
from pathlib import Path
from PIL import Image
from django.conf import settings

def reconvert_webp_images(quality=65, max_width=800, dry_run=True):
    """
    Riconverte le immagini WebP esistenti con nuovi parametri

    Args:
        quality: Qualità WebP (default 65)
        max_width: Larghezza massima (default 800)
        dry_run: Se True, mostra solo cosa farebbe senza modificare
    """
    print(f"=== Riconversione Immagini WebP ===")
    print(f"Qualità: {quality}%")
    print(f"Larghezza max: {max_width}px")
    print(f"Modalità: {'DRY RUN (nessuna modifica)' if dry_run else 'LIVE (modifica file)'}")
    print()

    # Trova articoli con foto_upload WebP
    articoli = Articolo.objects.filter(foto_upload__endswith='.webp')
    total = articoli.count()

    print(f"Trovati {total} articoli con immagini WebP")
    print()

    converted = 0
    total_savings = 0

    for idx, articolo in enumerate(articoli, 1):
        try:
            file_path = Path(settings.MEDIA_ROOT) / articolo.foto_upload.name

            if not file_path.exists():
                print(f"[{idx}/{total}] SKIP: {file_path.name} - File non trovato")
                continue

            # Apri immagine
            img = Image.open(file_path)
            original_size = file_path.stat().st_size
            width, height = img.size

            # Controlla se serve riconvertire
            if width <= max_width:
                print(f"[{idx}/{total}] SKIP: {file_path.name} - Già {width}px (≤ {max_width}px)")
                continue

            print(f"[{idx}/{total}] {file_path.name}")
            print(f"   Dimensioni: {width}x{height}px → ", end='')

            # Ridimensiona
            ratio = max_width / width
            new_height = int(height * ratio)
            img_resized = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            print(f"{max_width}x{new_height}px")

            if not dry_run:
                # Salva con nuova qualità
                img_resized.save(file_path, 'WebP', quality=quality, method=6)
                new_size = file_path.stat().st_size
                savings = original_size - new_size
                total_savings += savings

                print(f"   Dimensione: {original_size/1024:.1f}KB → {new_size/1024:.1f}KB (risparmio: {savings/1024:.1f}KB)")
                converted += 1
            else:
                print(f"   Dimensione: {original_size/1024:.1f}KB (sarebbe ridotto)")

        except Exception as e:
            print(f"[{idx}/{total}] ERRORE: {articolo.foto_upload.name} - {e}")

    print()
    print("=== Riepilogo ===")
    if dry_run:
        print(f"Modalità DRY RUN - Nessuna modifica effettuata")
        print(f"Immagini da riconvertire: {converted}/{total}")
    else:
        print(f"Immagini riconvertite: {converted}/{total}")
        print(f"Risparmio totale: {total_savings/1024/1024:.2f} MB")

if __name__ == '__main__':
    import sys

    # Controlla argomenti
    dry_run = '--live' not in sys.argv

    if dry_run:
        print("⚠️  MODALITÀ DRY RUN - Nessuna modifica verrà effettuata")
        print("    Per applicare le modifiche, esegui: python reconvert_images.py --live")
        print()
    else:
        print("⚠️  MODALITÀ LIVE - Le immagini verranno MODIFICATE")
        response = input("Sei sicuro? (scrivi 'SI' per confermare): ")
        if response != 'SI':
            print("Operazione annullata")
            sys.exit(0)
        print()

    reconvert_webp_images(quality=65, max_width=800, dry_run=dry_run)
