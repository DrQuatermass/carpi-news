#!/usr/bin/env python3
"""
Scheduler per "Cosa fare oggi?" - Rubrica eventi quotidiana
Esegue ogni giorno alle 8:05 (ora italiana)
"""
import threading
import time
import logging
from datetime import datetime
import schedule
import sys
import os
import django

# Setup Django (solo se eseguito come script standalone)
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")

# NON chiamare django.setup() qui - causa "populate() isn't reentrant"
# quando importato da apps.py. Django è già inizializzato in quel contesto.

from home.logger_config import setup_centralized_logger

logger = setup_centralized_logger('cosa_fare_oggi_scheduler', 'INFO')

def run_cosa_fare_oggi():
    """Esegue la generazione di "Cosa fare oggi?" """
    try:
        logger.info("[OK] Avvio generazione 'Cosa fare oggi?' schedulata")

        # Import dinamico per evitare problemi di inizializzazione
        from django.core.management import call_command

        # Esegui il comando genera_cosa_fare_oggi
        call_command('genera_cosa_fare_oggi')

        logger.info("[OK] 'Cosa fare oggi?' completato con successo")

    except Exception as e:
        logger.error(f"Errore nell'esecuzione schedulata di 'Cosa fare oggi?': {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

def start_scheduler():
    """Avvia lo scheduler per 'Cosa fare oggi?' """
    from pathlib import Path

    try:
        # Programma alle 8:05 ogni giorno (ora italiana)
        schedule.every().day.at("08:05").do(run_cosa_fare_oggi)

        logger.info("[OK] Scheduler 'Cosa fare oggi?' avviato - esecuzione alle 8:05 ogni giorno")

        # Lock file per aggiornamento periodico
        lock_file = Path('locks') / 'cosa_fare_oggi_scheduler.lock'

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
        logger.error(f"Errore nello scheduler 'Cosa fare oggi?': {e}")

def start_scheduler_daemon():
    """Avvia lo scheduler in un thread daemon con controllo per prevenire duplicati"""
    from pathlib import Path
    import time

    try:
        # Lock file per prevenire avvii multipli tra worker Gunicorn
        locks_dir = Path('locks')
        locks_dir.mkdir(exist_ok=True)
        lock_file = locks_dir / 'cosa_fare_oggi_scheduler.lock'

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
                            logger.info(f"Scheduler 'Cosa fare oggi?' già avviato dal processo {pid} (lock età: {lock_age:.1f}s), skip")
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
                logger.info(f"Rimozione lock 'Cosa fare oggi?' vecchio ({lock_age:.1f}s)")
                lock_file.unlink()

        # Crea il lock
        lock_file.write_text(str(os.getpid()))

        thread = threading.Thread(target=start_scheduler, daemon=True, name="CosaFareOggiScheduler")
        thread.start()
        logger.info("[OK] Scheduler 'Cosa fare oggi?' avviato in background")
        return True
    except Exception as e:
        logger.error(f"Errore nell'avvio daemon scheduler 'Cosa fare oggi?': {e}")
        return False

if __name__ == "__main__":
    start_scheduler()
