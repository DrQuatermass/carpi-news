#!/usr/bin/env python3
"""
Scheduler per la newsletter giornaliera
Invia la newsletter ogni giorno alle 17:30 (ora italiana)
"""
import threading
import time
import logging
import sys
import os
from datetime import time as datetime_time
from zoneinfo import ZoneInfo

sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")

# NON chiamare django.setup() qui - causa "populate() isn't reentrant"
# quando importato da apps.py. Django è già inizializzato in quel contesto.

from home.logger_config import setup_centralized_logger

logger = setup_centralized_logger('newsletter_scheduler', 'INFO')

NEWSLETTER_TIME = datetime_time(17, 30)
NEWSLETTER_TIMEZONE = ZoneInfo("Europe/Rome")


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
    from datetime import datetime

    try:
        logger.info("📅 Scheduler newsletter avviato - esecuzione alle 17:30 ogni giorno")

        lock_file = Path('locks') / 'newsletter_scheduler.lock'
        last_run_date = None

        while True:
            now_rome = datetime.now(NEWSLETTER_TIMEZONE)
            if (
                now_rome.hour == NEWSLETTER_TIME.hour
                and now_rome.minute == NEWSLETTER_TIME.minute
                and last_run_date != now_rome.date()
            ):
                run_newsletter()
                last_run_date = now_rome.date()

            try:
                lock_file.write_text(str(os.getpid()))
            except Exception:
                pass
            time.sleep(60)

    except Exception as e:
        logger.error(f"Errore nello scheduler newsletter: {e}")


def start_scheduler_daemon():
    """Avvia lo scheduler in un thread daemon con lock atomico (fcntl) per prevenire duplicati tra worker Gunicorn"""
    from pathlib import Path

    try:
        locks_dir = Path('locks')
        locks_dir.mkdir(exist_ok=True)
        lock_file = locks_dir / 'newsletter_scheduler.lock'

        if os.name == 'nt':
            # Windows: fallback al controllo PID (sviluppo locale)
            if lock_file.exists():
                try:
                    pid_str = lock_file.read_text().strip()
                    if pid_str and pid_str.isdigit():
                        import psutil
                        if psutil.pid_exists(int(pid_str)):
                            logger.info(f"Scheduler newsletter già avviato (PID {pid_str}), skip")
                            return False
                except Exception:
                    pass
            lock_file.write_text(str(os.getpid()))
        else:
            # Linux/Unix: lock atomico con fcntl — impossibile race condition
            import fcntl
            lock_fd = open(lock_file, 'w')
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                logger.info("Scheduler newsletter già gestito da altro worker Gunicorn, skip")
                lock_fd.close()
                return False
            # Scrivi PID e mantieni il fd aperto per tenere il lock
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
            # Salva fd come attributo del modulo per evitare garbage collection
            start_scheduler_daemon._lock_fd = lock_fd

        thread = threading.Thread(target=start_scheduler, daemon=True)
        thread.start()
        logger.info("🔄 Scheduler newsletter avviato in background")
        return True

    except Exception as e:
        logger.error(f"Errore nell'avvio daemon scheduler newsletter: {e}")
        return False


if __name__ == "__main__":
    start_scheduler()
