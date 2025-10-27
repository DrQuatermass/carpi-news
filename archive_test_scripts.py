#!/usr/bin/env python
"""
Script per archiviare script di test e file temporanei dalla root
Sposta i file in una cartella archive/ per mantenere la root pulita
"""

import os
import shutil
from pathlib import Path
from datetime import datetime

def archive_test_scripts():
    """Archivia script di test e temporanei"""

    # Crea directory archive con timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_dir = Path(f'archive/cleanup_{timestamp}')
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Pattern di file da archiviare
    patterns = [
        'test_*.py',
        'check_*.py',
        'download_*.py',
        'optimize_*.py',
        '*.html',  # modenatoday_eventi.html
        'nul',
        'conversion_log.txt'
    ]

    # File specifici da archiviare
    specific_files = [
        'carpi_news/db.sqlite3.corrupted_backup_20251024_222055',
        'carpi_news/home/internal_linking.py',
        'carpi_news/nul'
    ]

    moved = []
    errors = []
    skipped = []

    print("Archiviazione script di test e file temporanei...\n")

    # Cerca nella root
    root = Path('.')
    for pattern in patterns:
        for file_path in root.glob(pattern):
            # Salta venv e altri directory
            if file_path.is_file() and not any(part.startswith('.') or part == 'venv' for part in file_path.parts):
                try:
                    dest = archive_dir / file_path.name
                    shutil.move(str(file_path), str(dest))
                    moved.append(str(file_path))
                    print(f"[OK] Archiviato: {file_path} -> {dest}")
                except Exception as e:
                    errors.append(f"{file_path}: {e}")
                    print(f"[ERRORE] {file_path}: {e}")

    # File specifici
    for file_path_str in specific_files:
        file_path = Path(file_path_str)
        if file_path.exists():
            try:
                # Mantieni struttura directory per file in subdirectory
                if len(file_path.parts) > 1:
                    dest_dir = archive_dir / file_path.parent.name
                    dest_dir.mkdir(exist_ok=True)
                    dest = dest_dir / file_path.name
                else:
                    dest = archive_dir / file_path.name

                shutil.move(str(file_path), str(dest))
                moved.append(str(file_path))
                print(f"[OK] Archiviato: {file_path} -> {dest}")
            except Exception as e:
                errors.append(f"{file_path}: {e}")
                print(f"[ERRORE] {file_path}: {e}")

    # Crea README nell'archive
    readme_path = archive_dir / 'README.txt'
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(f"Archive creato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("Questi file sono stati archiviati per mantenere pulita la directory principale.\n")
        f.write("Si tratta principalmente di script di test e file temporanei.\n\n")
        f.write("File archiviati:\n")
        for file in moved:
            f.write(f"  - {file}\n")

    # Riepilogo
    print("\n" + "="*60)
    print("RIEPILOGO")
    print("="*60)
    print(f"File archiviati: {len(moved)}")
    print(f"Errori: {len(errors)}")
    print(f"Directory archive: {archive_dir}")

    if errors:
        print("\nErrori:")
        for error in errors:
            print(f"  - {error}")

    print("\nNOTA: I file sono stati spostati in archive/ e possono essere eliminati")
    print("      se non più necessari. La directory archive/ è già in .gitignore")

    return len(moved), len(errors)


if __name__ == '__main__':
    archive_test_scripts()
