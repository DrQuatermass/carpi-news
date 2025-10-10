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
    _monitor_manager = None  # Riferimento al manager per il watchdog
    _watchdog_thread = None
    _editorial_scheduler_started = False
    
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
                    self.start_editorial_scheduler()
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
            # Previeni avvii multipli nello stesso processo
            if HomeConfig._universal_monitors_started:
                logger.info("Monitor universali già avviati in questo worker, skip")
                return

            # Previeni avvii multipli tra worker diversi usando un lock file globale
            from pathlib import Path
            import time

            master_lock_file = Path('locks/.master_startup.lock')
            master_lock_file.parent.mkdir(exist_ok=True)

            # Se il lock esiste ed è più recente di 60 secondi, skip
            if master_lock_file.exists():
                lock_age = time.time() - master_lock_file.stat().st_mtime
                if lock_age < 60:  # Lock valido per 60 secondi
                    logger.info(f"Monitor universali già avviati da altro worker (lock età: {lock_age:.1f}s), skip")
                    return
                else:
                    # Lock vecchio, rimuovilo
                    logger.info(f"Rimozione lock master vecchio ({lock_age:.1f}s)")
                    master_lock_file.unlink()

            # Crea il master lock
            master_lock_file.write_text(str(os.getpid()))
            logger.info(f"Master lock acquisito (PID {os.getpid()})")

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

                    # Salva riferimento al manager per il watchdog
                    HomeConfig._monitor_manager = manager

                    # Avvia il watchdog thread per monitorare i cambi da admin
                    self._start_monitor_watchdog()

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

    def _start_monitor_watchdog(self):
        """Avvia un thread watchdog che monitora i cambi is_active dal pannello admin"""
        if HomeConfig._watchdog_thread is not None:
            logger.info("Watchdog già avviato, skip")
            return

        def watchdog_loop():
            """Loop del watchdog che controlla il DB ogni 30 secondi"""
            import time
            from home.models import MonitorConfig
            from django.utils import timezone

            logger.info("Watchdog monitor avviato - controlla DB ogni 30 secondi")

            while True:
                try:
                    time.sleep(30)  # Controlla ogni 30 secondi

                    manager = HomeConfig._monitor_manager
                    if manager is None:
                        continue

                    # Ottieni monitor attivi dal DB
                    active_monitors_db = MonitorConfig.objects.filter(is_active=True)

                    for monitor_config in active_monitors_db:
                        # Crea nome monitor normalizzato
                        monitor_name = monitor_config.name.lower().replace(' ', '_')

                        # Controlla se è in esecuzione nel manager
                        if monitor_name not in manager.running_monitors:
                            logger.info(f"Watchdog: Monitor '{monitor_config.name}' è active nel DB ma non in esecuzione - riavvio...")

                            try:
                                # Aggiungi al manager se non esiste
                                if monitor_name not in manager.monitors:
                                    site_config = monitor_config.to_site_config()
                                    interval = monitor_config.config_data.get('interval', 600)
                                    manager.add_monitor_from_config(site_config, interval)

                                # Avvia il monitor
                                success = manager.start_monitor(monitor_name)
                                if success:
                                    logger.info(f"Watchdog: Monitor '{monitor_config.name}' riavviato con successo")
                                    monitor_config.last_run = timezone.now()
                                    monitor_config.save(update_fields=['last_run'])
                                else:
                                    logger.error(f"Watchdog: Impossibile riavviare '{monitor_config.name}'")

                            except Exception as e:
                                logger.error(f"Watchdog: Errore riavvio '{monitor_config.name}': {e}")

                    # Controlla monitor da fermare (is_active=False nel DB ma running nel manager)
                    inactive_monitors_db = MonitorConfig.objects.filter(is_active=False)
                    for monitor_config in inactive_monitors_db:
                        monitor_name = monitor_config.name.lower().replace(' ', '_')

                        if monitor_name in manager.running_monitors:
                            logger.info(f"Watchdog: Monitor '{monitor_config.name}' è inactive nel DB ma in esecuzione - fermo...")
                            try:
                                manager.stop_monitor(monitor_name)
                                logger.info(f"Watchdog: Monitor '{monitor_config.name}' fermato con successo")
                            except Exception as e:
                                logger.error(f"Watchdog: Errore fermata '{monitor_config.name}': {e}")

                except Exception as e:
                    logger.error(f"Watchdog: Errore nel ciclo di controllo: {e}")

        # Avvia thread watchdog
        watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True, name="MonitorWatchdog")
        watchdog_thread.start()
        HomeConfig._watchdog_thread = watchdog_thread
        logger.info("Thread watchdog monitor avviato")

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

    def start_editorial_scheduler(self):
        """Avvia lo scheduler per l'editoriale quotidiano"""
        try:
            # Previeni avvii multipli
            if HomeConfig._editorial_scheduler_started:
                logger.info("Scheduler editoriale già avviato, skip")
                return

            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            from editoriale_scheduler import start_scheduler_daemon

            success = start_scheduler_daemon()
            if success:
                HomeConfig._editorial_scheduler_started = True
                logger.info("✅ Scheduler editoriale avviato - articolo alle 8:00 ogni giorno")
            else:
                logger.error("❌ Impossibile avviare scheduler editoriale")

        except ImportError as e:
            logger.error(f"Modulo 'schedule' non trovato - installa con: pip install schedule")
        except Exception as e:
            logger.error(f"Errore nell'avvio scheduler editoriale: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

