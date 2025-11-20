#!/usr/bin/env python3
"""
Scheduler per l'editoriale quotidiano
Esegue l'editoriale ogni giorno alle 8:00 (ora italiana)
"""
import threading
import time
import logging
from datetime import datetime, timedelta
import schedule
import sys
import os
import django

# Setup Django (solo se non già inizializzato)
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")

# Controlla se Django è già inizializzato (apps.py già chiamato)
if not django.apps.apps.ready:
    django.setup()

from home.logger_config import setup_centralized_logger

logger = setup_centralized_logger('editoriale_scheduler', 'INFO')

def run_editoriale():
    """Esegue l'editoriale quotidiano"""
    try:
        logger.info("🕐 Avvio editoriale quotidiano schedulato")
        
        # Import dinamico per evitare problemi di inizializzazione
        import subprocess
        import os
        
        # Esegui editoriale.py
        script_path = os.path.join(os.path.dirname(__file__), 'editoriale.py')
        result = subprocess.run([sys.executable, script_path], 
                              capture_output=True, text=True, cwd=os.path.dirname(__file__))
        
        if result.returncode == 0:
            logger.info("✅ Editoriale quotidiano completato con successo")
        else:
            logger.error(f"❌ Errore nell'editoriale: {result.stderr}")
            
    except Exception as e:
        logger.error(f"Errore nell'esecuzione schedulata dell'editoriale: {e}")

def start_scheduler():
    """Avvia lo scheduler per l'editoriale"""
    from pathlib import Path

    try:
        # Programma l'editoriale alle 8:00 ogni giorno (ora italiana)
        schedule.every().day.at("08:00").do(run_editoriale)

        logger.info("📅 Scheduler editoriale avviato - esecuzione alle 8:00 ogni giorno")

        # Lock file per aggiornamento periodico
        lock_file = Path('locks') / 'editorial_scheduler.lock'

        # Loop principale dello scheduler
        while True:
            schedule.run_pending()

            # Aggiorna il lock file ogni minuto per dimostrare che siamo vivi
            try:
                lock_file.write_text(str(os.getpid()))
            except Exception:
                pass

            time.sleep(60)  # Controlla ogni minuto

    except Exception as e:
        logger.error(f"Errore nello scheduler editoriale: {e}")

def start_scheduler_daemon():
    """Avvia lo scheduler in un thread daemon con controllo per prevenire duplicati"""
    from pathlib import Path
    import time

    try:
        # Lock file per prevenire avvii multipli tra worker Gunicorn
        locks_dir = Path('locks')
        locks_dir.mkdir(exist_ok=True)
        lock_file = locks_dir / 'editorial_scheduler.lock'

        # Se il lock esiste ed è recente (meno di 2 minuti), verifica se il processo è vivo
        if lock_file.exists():
            lock_age = time.time() - lock_file.stat().st_mtime
            if lock_age < 120:  # Lock valido per 2 minuti (aggiornato ogni minuto)
                # Leggi il PID e controlla se il processo è ancora vivo
                try:
                    pid_str = lock_file.read_text().strip()
                    if pid_str and pid_str.isdigit():
                        pid = int(pid_str)
                        # Controlla se il processo esiste (cross-platform)
                        process_exists = False
                        try:
                            if os.name == 'nt':  # Windows
                                import psutil
                                process_exists = psutil.pid_exists(pid)
                            else:  # Unix/Linux
                                os.kill(pid, 0)  # Signal 0 non uccide, solo verifica esistenza
                                process_exists = True
                        except (OSError, ProcessLookupError, ImportError):
                            process_exists = False

                        if process_exists:
                            logger.info(f"Scheduler editoriale già avviato dal processo {pid} (lock età: {lock_age:.1f}s), skip")
                            return False
                        else:
                            # Processo morto, lock stantio
                            logger.info(f"Lock da processo morto {pid}, rimuovo")
                            lock_file.unlink()
                    else:
                        # Lock corrotto, rimuovilo
                        logger.warning(f"Lock corrotto (PID non valido: '{pid_str}'), rimuovo")
                        lock_file.unlink()
                except Exception as e:
                    logger.warning(f"Errore lettura lock: {e}, rimuovo")
                    lock_file.unlink()
            else:
                # Lock vecchio (processo morto), rimuovilo
                logger.info(f"Rimozione lock editoriale vecchio ({lock_age:.1f}s)")
                lock_file.unlink()

        # Crea il lock
        lock_file.write_text(str(os.getpid()))

        thread = threading.Thread(target=start_scheduler, daemon=True)
        thread.start()
        logger.info("🔄 Scheduler editoriale avviato in background")
        return True
    except Exception as e:
        logger.error(f"Errore nell'avvio daemon scheduler: {e}")
        return False

if __name__ == "__main__":
    start_scheduler()