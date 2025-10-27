#!/usr/bin/env python
"""
Script per rimuovere file backup (.bak, .backup) dai template e CSS
Mantiene i backup delle immagini WebP per sicurezza
"""

import os
from pathlib import Path

def cleanup_backup_files():
    """Rimuove file backup da template e CSS"""

    # Directory da pulire
    template_dir = Path('carpi_news/home/templates')
    css_dir = Path('carpi_news/home/static/home/css')

    removed = []
    errors = []

    print("Pulizia file backup (.bak, .backup)...\n")

    # Template backup
    if template_dir.exists():
        for pattern in ['*.bak', '*.backup']:
            for file_path in template_dir.glob(pattern):
                try:
                    file_path.unlink()
                    removed.append(str(file_path))
                    print(f"[OK] Rimosso: {file_path}")
                except Exception as e:
                    errors.append(f"{file_path}: {e}")
                    print(f"[ERRORE] {file_path}: {e}")

    # CSS backup
    if css_dir.exists():
        for pattern in ['*.bak', '*.backup']:
            for file_path in css_dir.glob(pattern):
                try:
                    file_path.unlink()
                    removed.append(str(file_path))
                    print(f"[OK] Rimosso: {file_path}")
                except Exception as e:
                    errors.append(f"{file_path}: {e}")
                    print(f"[ERRORE] {file_path}: {e}")

    # Riepilogo
    print("\n" + "="*60)
    print("RIEPILOGO")
    print("="*60)
    print(f"File backup rimossi: {len(removed)}")
    print(f"Errori: {len(errors)}")

    if errors:
        print("\nErrori:")
        for error in errors:
            print(f"  - {error}")

    print("\nNOTA: I backup delle immagini WebP sono stati mantenuti per sicurezza")
    print("      Si trovano in carpi_news/media/images/downloaded/")


if __name__ == '__main__':
    cleanup_backup_files()
