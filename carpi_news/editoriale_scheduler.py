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

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")
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

        # Esegui un test immediato (se è dopo le 8:00 e non c'è già l'editoriale di oggi)
        now = datetime.now()
        if now.hour >= 8:
            # Controlla se esiste già l'editoriale di oggi
            from home.models import Articolo
            from django.utils import timezone

            today = timezone.now().date()
            today_editorial = Articolo.objects.filter(
                categoria='Editoriale',
                data_pubblicazione__date=today
            ).exists()

            if not today_editorial:
                logger.info("🚀 Esecuzione test immediata dell'editoriale")
                run_editoriale()

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

        # Se il lock esiste ed è recente (meno di 2 minuti), skip
        if lock_file.exists():
            lock_age = time.time() - lock_file.stat().st_mtime
            if lock_age < 120:  # Lock valido per 2 minuti (aggiornato ogni minuto)
                logger.info(f"Scheduler editoriale già avviato (lock età: {lock_age:.1f}s), skip")
                return False
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