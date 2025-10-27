#!/usr/bin/env python
"""
Script per convertire tutte le immagini esistenti in media/images/downloaded/ in formato WebP
Mantiene i file originali con suffisso .backup
"""

import os
import sys
import io
from pathlib import Path
from PIL import Image

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'carpi_news'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')

import django
django.setup()

from django.conf import settings
from home.models import Articolo


def convert_image_to_webp(image_path: Path, quality: int = 85) -> Path:
    """
    Converte un'immagine in WebP

    Args:
        image_path: Path dell'immagine da convertire
        quality: Qualità WebP (default 85)

    Returns:
        Path del nuovo file WebP
    """
    try:
        # Leggi l'immagine
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        img = Image.open(io.BytesIO(image_bytes))

        # Converti in RGB se necessario (WebP supporta RGBA per trasparenze)
        if img.mode in ('RGBA', 'LA'):
            # Mantieni RGBA per WebP con trasparenza
            pass
        elif img.mode == 'P':
            img = img.convert('RGBA')
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Salva come WebP
        output_buffer = io.BytesIO()
        img.save(output_buffer, format='WEBP', quality=quality, method=6)
        webp_bytes = output_buffer.getvalue()

        # Genera nome file WebP
        webp_path = image_path.with_suffix('.webp')

        # Se il file è già WebP, sovrascrivi
        if image_path.suffix.lower() == '.webp':
            # Backup del file originale
            backup_path = image_path.with_suffix('.webp.backup')
            if not backup_path.exists():
                image_path.rename(backup_path)
                print(f"  Backup: {backup_path.name}")

            # Salva WebP ottimizzato
            with open(image_path, 'wb') as f:
                f.write(webp_bytes)

            return image_path
        else:
            # Backup del file originale (jpg/png)
            backup_path = Path(str(image_path) + '.backup')
            if not backup_path.exists():
                image_path.rename(backup_path)
                print(f"  Backup: {backup_path.name}")
            else:
                # Se esiste già il backup, rimuovi l'originale
                image_path.unlink()

            # Salva come WebP
            with open(webp_path, 'wb') as f:
                f.write(webp_bytes)

            return webp_path

    except Exception as e:
        print(f"  [ERRORE] Errore nella conversione: {e}")
        return None


def update_database_urls(old_path: str, new_path: str):
    """Aggiorna gli URL nel database"""
    old_url = f"/media/images/downloaded/{old_path}"
    new_url = f"/media/images/downloaded/{new_path}"

    # Aggiorna articoli con foto che puntano al vecchio URL
    articles = Articolo.objects.filter(foto=old_url)
    count = articles.count()

    if count > 0:
        articles.update(foto=new_url)
        print(f"  [DB] Aggiornati {count} articoli nel database")

    return count


def main():
    """Converte tutte le immagini in media/images/downloaded/"""

    # Directory delle immagini
    media_dir = Path(settings.MEDIA_ROOT) / 'images' / 'downloaded'

    if not media_dir.exists():
        print(f"[ERRORE] Directory non trovata: {media_dir}")
        return

    print(f"Cerco immagini in: {media_dir}\n")

    # Estensioni supportate
    extensions = ['.jpg', '.jpeg', '.png', '.webp']

    # Trova tutte le immagini
    image_files = []
    for ext in extensions:
        image_files.extend(media_dir.glob(f'*{ext}'))
        image_files.extend(media_dir.glob(f'*{ext.upper()}'))

    # Escludi i backup
    image_files = [f for f in image_files if '.backup' not in f.name]

    if not image_files:
        print("Nessuna immagine da convertire")
        return

    print(f"Trovate {len(image_files)} immagini da processare\n")

    # Statistiche
    converted = 0
    skipped = 0
    errors = 0
    total_saved_kb = 0
    db_updates = 0

    for i, image_path in enumerate(image_files, 1):
        original_name = image_path.name

        # Salta se il file non esiste (potrebbe essere già stato processato come duplicato)
        if not image_path.exists():
            print(f"[{i}/{len(image_files)}] {original_name} - File già processato, salto")
            skipped += 1
            continue

        original_size_kb = image_path.stat().st_size / 1024

        print(f"[{i}/{len(image_files)}] {original_name} ({original_size_kb:.1f}KB)")

        # Converti in WebP
        webp_path = convert_image_to_webp(image_path, quality=85)

        if webp_path:
            new_size_kb = webp_path.stat().st_size / 1024
            saved_kb = original_size_kb - new_size_kb
            saving_percent = (saved_kb / original_size_kb) * 100 if original_size_kb > 0 else 0

            print(f"  [OK] Convertito: {webp_path.name} ({new_size_kb:.1f}KB, risparmio {saving_percent:.1f}%)")

            # Aggiorna database se necessario
            if original_name != webp_path.name:
                updated = update_database_urls(original_name, webp_path.name)
                db_updates += updated

            converted += 1
            total_saved_kb += saved_kb
        else:
            errors += 1

        print()

    # Riepilogo
    print("=" * 60)
    print("RIEPILOGO")
    print("=" * 60)
    print(f"Immagini convertite: {converted}")
    print(f"Errori: {errors}")
    print(f"Spazio risparmiato: {total_saved_kb / 1024:.2f} MB")
    print(f"Record database aggiornati: {db_updates}")
    print()
    print("Conversione completata!")
    print()
    print("Note:")
    print("  - I file originali sono stati rinominati con suffisso .backup")
    print("  - Gli URL nel database sono stati aggiornati automaticamente")
    print("  - Riavvia i monitor per usare i nuovi file WebP")


if __name__ == '__main__':
    main()
