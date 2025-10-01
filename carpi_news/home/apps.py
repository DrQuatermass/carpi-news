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
        if 'runserver' in sys.argv and not any('migrate' in arg for arg in sys.argv):
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
    
    
    def start_universal_monitors(self):
        """Avvia i monitor universali in background"""
        try:
            # Previeni avvii multipli
            if HomeConfig._universal_monitors_started:
                logger.info("Monitor universali già avviati, skip")
                return
            
            # Controlla se i monitor universali sono abilitati
            universal_config = getattr(settings, 'UNIVERSAL_MONITORS', {})
            if not universal_config.get('ENABLED', True):  # Default abilitato
                logger.info("Monitor universali disabilitati nelle impostazioni")
                return
            
            from home.monitor_manager import MonitorManager
            
            # Crea manager
            manager = MonitorManager()
            
            # Configurazioni dei monitor da avviare
            monitor_configs = universal_config.get('MONITORS', [
                ('carpi_calcio', 900),    # 15 minuti
                ('comune_carpi', 1200),   # 20 minuti
            ])
            
            # Avvia i monitor in un thread separato
            def start_monitors():
                try:
                    for config_name, interval in monitor_configs:
                        success = manager.add_monitor(config_name, interval)
                        if success:
                            logger.info(f"Monitor universale {config_name} configurato (intervallo: {interval}s)")
                        else:
                            logger.error(f"Errore nella configurazione monitor {config_name}")
                    
                    # Avvia tutti i monitor
                    results = manager.start_all_monitors()
                    success_count = sum(1 for success in results.values() if success)
                    logger.info(f"Monitor universali avviati: {success_count}/{len(results)}")
                    
                except Exception as e:
                    logger.error(f"Errore nell'avvio dei monitor universali: {e}")
            
            thread = threading.Thread(target=start_monitors, daemon=True)
            thread.start()
            
            # Marca come avviato
            HomeConfig._universal_monitors_started = True
            logger.info("Sistema monitor universali avviato automaticamente")
            
        except Exception as e:
            logger.error(f"Errore nell'avvio automatico dei monitor universali: {e}")
    
    def start_universal_monitors_improved(self):
        """Versione migliorata per avviare i monitor universali con gestione errori avanzata"""
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
            
            logger.info("Avvio monitor universali migliorato...")
            
            # Import dinamico per evitare problemi di inizializzazione
            from home.monitor_manager import MonitorManager
            from home.monitor_configs import get_config
            
            # Configurazioni dei monitor da avviare
            monitor_configs = [
                ('carpi_calcio', 300),           # 5 minuti - Carpi Calcio
                ('comune_carpi_graphql', 600),   # 10 minuti - Comune Carpi (GraphQL + fallback)
                ('eventi_carpi_graphql', 1800),  # 30 minuti - Eventi con descrizione_estesa
                ('ansa_carpi', 300),             # 5 minuti - ANSA Emilia-Romagna (filtro Carpi)
                ('youtube_playlist', 1800),      # 30 minuti - YouTube Playlist 1
                ('youtube_playlist_2', 1800),    # 30 minuti - YouTube Playlist 2
                ('temponews', 600),
                ('voce_carpi', 600),             # 10 minuti - La Voce di Carpi
                ('voce_carpi_sport', 600),       # 10 minuti - La Voce di Carpi Sport
                ('terre_argine', 900),           # 15 minuti - Terre d'Argine
                ('novi_modena', 900),            # 15 minuti - Comune Novi di Modena
                ('soliera', 900),                # 15 minuti - Comune Soliera
                ('campogalliano', 900),          # 15 minuti - Comune Campogalliano
                ('questura_modena', 600),        # 10 minuti - Questura Modena (Cronaca)
                ('email_comunicati', 300),       # 5 minuti - Email comunicati stampa + IFTTT
            ]
            
            # Verifica che le configurazioni esistano
            valid_configs = []
            for config_name, interval in monitor_configs:
                try:
                    config = get_config(config_name)
                    valid_configs.append((config_name, interval))
                    logger.info(f"Configurazione {config_name} validata")
                except Exception as e:
                    logger.warning(f"Configurazione {config_name} non valida: {e}")
            
            if not valid_configs:
                logger.error("Nessuna configurazione monitor valida trovata")
                return
            
            # Crea manager e avvia monitor
            manager = MonitorManager()
            
            started_monitors = []
            for config_name, interval in valid_configs:
                try:
                    success = manager.add_monitor(config_name, interval)
                    if success:
                        logger.info(f"Monitor {config_name} aggiunto con successo")
                    else:
                        logger.error(f"Impossibile aggiungere monitor {config_name}")
                        continue
                except Exception as e:
                    logger.error(f"Errore nell'aggiungere monitor {config_name}: {e}")
                    continue
            
            # Avvia tutti i monitor
            try:
                results = manager.start_all_monitors()
                success_count = sum(1 for success in results.values() if success)
                total_count = len(results)
                
                if success_count > 0:
                    logger.info(f"Monitor universali avviati con successo: {success_count}/{total_count}")
                    for monitor_name, started in results.items():
                        status = "✓ Avviato" if started else "✗ Fallito"
                        logger.info(f"  {monitor_name}: {status}")
                    
                    # Marca come avviato solo se almeno un monitor è partito
                    HomeConfig._universal_monitors_started = True
                    
                else:
                    logger.error("Nessun monitor universale avviato con successo")
                    
            except Exception as e:
                logger.error(f"Errore nell'avvio dei monitor: {e}")
                
        except Exception as e:
            logger.error(f"Errore critico nell'avvio monitor universali: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
