import logging
import threading
import os
import signal
import atexit
if os.name != "nt":  # Non Windows
    import fcntl
else:
    import msvcrt
from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'home'
    
    # Variabili di classe per prevenire avvii multipli
    _universal_monitors_started = False
    
    def ready(self):
        """Chiamato quando l'app è pronta - avvia il monitor playlist e registra segnali"""
        # Registra i segnali
        import home.signals

        # Evita di avviare durante le migrazioni o in altri contesti non appropriati
        import sys
        import os

        # Avvia i monitor in produzione (Gunicorn) o sviluppo (runserver)
        # Evita solo durante migrazioni, makemigrations, test, e altri comandi Django
        skip_commands = ['migrate', 'makemigrations', 'test', 'shell', 'createsuperuser', 'collectstatic']
        should_skip = any(cmd in sys.argv for cmd in skip_commands)

        # Controlla se l'auto-start è abilitato tramite variabile d'ambiente
        auto_start_enabled = os.environ.get('AUTO_START_MONITORS', 'False').lower() == 'true'

        # Rileva se siamo in ambiente di produzione (Gunicorn) o sviluppo (runserver)
        # Gunicorn può essere rilevato in diversi modi:
        # 1. sys.argv[0] contiene 'gunicorn'
        # 2. Variabile ambiente SERVER_SOFTWARE
        # 3. Processo parent è gunicorn
        is_gunicorn = 'gunicorn' in sys.argv[0] if sys.argv else False
        is_production = is_gunicorn or 'gunicorn' in os.environ.get('SERVER_SOFTWARE', '')
        is_dev = 'runserver' in sys.argv

        if auto_start_enabled and (is_production or is_dev) and not should_skip:
            # Avvia i monitor automaticamente con un piccolo ritardo per evitare conflitti
            import threading
            import time

            def delayed_start():
                time.sleep(5)  # Aspetta 5 secondi per evitare conflitti
                try:
                    self.start_universal_monitors_improved()
                except Exception as e:
                    logger.error(f"Errore nell'avvio ritardato dei monitor: {e}")

            # Solo se non sono già stati programmati
            if not hasattr(HomeConfig, '_delayed_start_scheduled'):
                thread = threading.Thread(target=delayed_start, daemon=True)
                thread.start()
                HomeConfig._delayed_start_scheduled = True
                logger.info("Monitor automatici programmati per l'avvio con ritardo di 5 secondi")
            else:
                logger.info("Monitor automatici già programmati, skip")
        elif (is_production or is_dev) and not should_skip and not auto_start_enabled:
            logger.info("Auto-start monitor disabilitato (AUTO_START_MONITORS=False). Usa 'python manage.py start_monitors' per avviarli manualmente.")
    
    
    def start_universal_monitors(self):
        """Avvia i monitor universali in background (deprecato - usa start_universal_monitors_improved)"""
        # Reindirizza al metodo migliorato che usa il database
        self.start_universal_monitors_improved()
    
    def start_universal_monitors_improved(self):
        """Versione migliorata per avviare i monitor universali dal database"""
        try:
            # Previeni avvii multipli
            if HomeConfig._universal_monitors_started:
                logger.info("Monitor universali già avviati, skip")
                return

            # Controlla se i monitor universali sono abilitati
            universal_config = getattr(settings, 'UNIVERSAL_MONITORS', {})
            if not universal_config.get('ENABLED', True):  # Default abilitato
                logger.info("Monitor universali disabilitati nelle impostazioni - sistema di monitoraggio NON avviato")
                return

            # Pulisci lock files vecchi (più di 1 ora) per evitare blocchi
            self._clean_stale_locks()

            logger.info("Avvio monitor universali dal database...")

            # Import dinamico per evitare problemi di inizializzazione
            from home.monitor_manager import MonitorManager
            from home.models import MonitorConfig

            # Carica monitor attivi dal database
            active_monitors = MonitorConfig.objects.filter(is_active=True).order_by('name')

            if not active_monitors.exists():
                logger.warning("Nessun monitor attivo trovato nel database")
                return

            logger.info(f"Trovati {active_monitors.count()} monitor attivi nel database")

            # Crea manager e avvia monitor
            manager = MonitorManager()

            added_count = 0
            for monitor_config in active_monitors:
                try:
                    # Converti in SiteConfig
                    site_config = monitor_config.to_site_config()

                    # Ottieni intervallo dalla configurazione (default 600s)
                    interval = monitor_config.config_data.get('interval', 600)

                    # Aggiungi al manager
                    success = manager.add_monitor_from_config(site_config, interval)

                    if success:
                        added_count += 1
                        logger.info(f"Monitor '{monitor_config.name}' aggiunto (intervallo: {interval}s)")
                    else:
                        logger.error(f"Impossibile aggiungere monitor '{monitor_config.name}'")

                except Exception as e:
                    logger.error(f"Errore nell'aggiungere monitor '{monitor_config.name}': {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    continue

            if added_count == 0:
                logger.error("Nessun monitor aggiunto al manager")
                return

            # Avvia tutti i monitor
            try:
                results = manager.start_all_monitors()
                success_count = sum(1 for success in results.values() if success)
                total_count = len(results)

                if success_count > 0:
                    logger.info(f"Monitor universali avviati con successo: {success_count}/{total_count}")
                    for monitor_name, started in results.items():
                        status = "[OK] Avviato" if started else "[ERRORE] Fallito"
                        logger.info(f"  {monitor_name}: {status}")

                    # Aggiorna last_run per i monitor avviati
                    from django.utils import timezone
                    active_monitors.update(last_run=timezone.now())

                    # Marca come avviato solo se almeno un monitor è partito
                    HomeConfig._universal_monitors_started = True
                    logger.info("Sistema monitor universali basato su DB avviato con successo!")

                else:
                    logger.error("Nessun monitor universale avviato con successo")

            except Exception as e:
                logger.error(f"Errore nell'avvio dei monitor: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        except Exception as e:
            logger.error(f"Errore critico nell'avvio monitor universali: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _clean_stale_locks(self):
        """Pulisce i lock files più vecchi di 1 ora"""
        try:
            from pathlib import Path
            import time

            locks_dir = Path('locks')
            if not locks_dir.exists():
                return

            current_time = time.time()
            one_hour_ago = current_time - 3600  # 1 ora in secondi

            removed = 0
            for lock_file in locks_dir.glob('*.lock'):
                try:
                    # Controlla l'età del file
                    file_mtime = lock_file.stat().st_mtime
                    if file_mtime < one_hour_ago:
                        lock_file.unlink()
                        removed += 1
                        logger.info(f"Rimosso lock vecchio: {lock_file.name}")
                except Exception as e:
                    logger.warning(f"Errore rimozione lock {lock_file.name}: {e}")

            if removed > 0:
                logger.info(f"Rimossi {removed} lock files vecchi")

        except Exception as e:
            logger.warning(f"Errore pulizia lock files: {e}")

