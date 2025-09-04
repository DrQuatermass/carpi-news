#!/usr/bin/env python3
"""
Script per pulire i vecchi file log quando non sono più in uso
"""
import os
import sys
import shutil
from pathlib import Path

def cleanup_old_logs():
    """Pulisce i vecchi file log"""
    base_path = Path(__file__).parent
    
    # File da rimuovere
    old_log_files = [
        base_path / 'logs' / 'playlist_monitor.log',
        base_path / 'logs' / 'carpi_news.log',
        base_path / 'monitor.log',
        base_path / 'migration_log.txt'
    ]
    
    print("=== PULIZIA VECCHI LOG ===")
    
    removed_count = 0
    for log_file in old_log_files:
        if log_file.exists():
            try:
                # Prova a rimuovere
                log_file.unlink()
                print(f"[OK] Rimosso: {log_file}")
                removed_count += 1
            except OSError as e:
                print(f"[ERRORE] Impossibile rimuovere {log_file}: {e}")
                
                # Se il file è in uso, proviamo a svuotarlo
                try:
                    with open(log_file, 'w') as f:
                        f.write('')
                    print(f"[SVUOTATO] Svuotato: {log_file}")
                except OSError:
                    print(f"[AVVISO] File in uso da altro processo: {log_file}")
        else:
            print(f"[INFO] Non esiste: {log_file}")
    
    print(f"\n[COMPLETATO] Pulizia completata. File rimossi: {removed_count}")
    
    # Mostra il nuovo file log centralizzato
    new_log = base_path / 'logs' / 'monitors.log'
    if new_log.exists():
        size_kb = new_log.stat().st_size / 1024
        print(f"[LOG] Log centralizzato: {new_log} ({size_kb:.1f} KB)")
    
    return removed_count

if __name__ == "__main__":
    cleanup_old_logs()