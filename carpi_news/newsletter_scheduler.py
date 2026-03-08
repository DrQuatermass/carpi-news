#!/usr/bin/env python3
"""
Scheduler per la newsletter giornaliera
Invia la newsletter ogni giorno alle 17:30 (ora italiana)
"""
import threading
import time
import logging
import schedule
import sys
import os

sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")

# NON chiamare django.setup() qui - causa "populate() isn't reentrant"
# quando importato da apps.py. Django è già inizializzato in quel contesto.

from home.logger_config import setup_centralized_logger

logger = setup_centralized_logger('newsletter_scheduler', 'INFO')


def run_newsletter():
    """Esegue l'invio della newsletter giornaliera"""
    try:
        logger.info("📧 Avvio invio newsletter giornaliera schedulata")

        import subprocess
        result = subprocess.run(
            [sys.executable, 'manage.py', 'send_newsletter'],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )

        if result.returncode == 0:
            logger.info(f"✅ Newsletter inviata con successo: {result.stdout.strip()}")
        else:
            logger.error(f"❌ Errore nell'invio newsletter: {result.stderr}")

    except Exception as e:
        logger.error(f"Errore nell'esecuzione schedulata della newsletter: {e}")


def start_scheduler():
    """Avvia lo scheduler per la newsletter"""
    from pathlib import Path

    try:
        schedule.every().day.at("17:30").do(run_newsletter)
        logger.info("📅 Scheduler newsletter avviato - esecuzione alle 17:30 ogni giorno")

        lock_file = Path('locks') / 'newsletter_scheduler.lock'

        while True:
            schedule.run_pending()
            try:
                lock_file.write_text(str(os.getpid()))
            except Exception:
                pass
            time.sleep(60)

    except Exception as e:
        logger.error(f"Errore nello scheduler newsletter: {e}")


def start_scheduler_daemon():
    """Avvia lo scheduler in un thread daemon con controllo per prevenire duplicati"""
    from pathlib import Path

    try:
        locks_dir = Path('locks')
        locks_dir.mkdir(exist_ok=True)
        lock_file = locks_dir / 'newsletter_scheduler.lock'

        if lock_file.exists():
            lock_age = time.time() - lock_file.stat().st_mtime
            if lock_age < 120:
                try:
                    pid_str = lock_file.read_text().strip()
                    if pid_str and pid_str.isdigit():
                        pid = int(pid_str)
                        process_exists = False
                        try:
                            if os.name == 'nt':  # Windows
                                import psutil
                                process_exists = psutil.pid_exists(pid)
                            else:  # Unix/Linux
                                os.kill(pid, 0)
                                process_exists = True
                        except (OSError, ProcessLookupError, ImportError):
                            process_exists = False

                        if process_exists:
                            logger.info(f"Scheduler newsletter già avviato dal processo {pid} (lock età: {lock_age:.1f}s), skip")
                            return False
                        else:
                            logger.info(f"Lock da processo morto {pid}, rimuovo")
                            lock_file.unlink()
                    else:
                        logger.warning(f"Lock corrotto (PID non valido: '{pid_str}'), rimuovo")
                        lock_file.unlink()
                except Exception as e:
                    logger.warning(f"Errore lettura lock: {e}, rimuovo")
                    lock_file.unlink()
            else:
                logger.info(f"Rimozione lock newsletter vecchio ({lock_age:.1f}s)")
                lock_file.unlink()

        lock_file.write_text(str(os.getpid()))

        thread = threading.Thread(target=start_scheduler, daemon=True)
        thread.start()
        logger.info("🔄 Scheduler newsletter avviato in background")
        return True

    except Exception as e:
        logger.error(f"Errore nell'avvio daemon scheduler newsletter: {e}")
        return False


if __name__ == "__main__":
    start_scheduler()
