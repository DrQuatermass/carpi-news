import logging
import time
from typing import Dict, List, Optional
from home.universal_news_monitor import UniversalNewsMonitor, SiteConfig
from home.monitor_configs import MONITOR_CONFIGS, get_config
from home.logger_config import get_monitor_logger

# Logger per il manager
logger = get_monitor_logger('monitor_manager')


class MonitorManager:
    """Gestisce multiple istanze di monitor news"""
    
    def __init__(self):
        self.monitors: Dict[str, UniversalNewsMonitor] = {}
        self.running_monitors: List[str] = []
    
    def add_monitor(self, config_name: str, check_interval: int = 900) -> bool:
        """Aggiunge un monitor dalla configurazione"""
        try:
            config = get_config(config_name)
            monitor = UniversalNewsMonitor(config, check_interval)
            self.monitors[config_name] = monitor
            logger.info(f"Monitor {config_name} aggiunto con successo")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiungere monitor {config_name}: {e}")
            return False
    
    def add_custom_monitor(self, config: SiteConfig, check_interval: int = 900) -> bool:
        """Aggiunge un monitor con configurazione personalizzata"""
        try:
            monitor = UniversalNewsMonitor(config, check_interval)
            self.monitors[config.name.lower().replace(' ', '_')] = monitor
            logger.info(f"Monitor personalizzato {config.name} aggiunto")
            return True
        except Exception as e:
            logger.error(f"Errore nell'aggiungere monitor personalizzato {config.name}: {e}")
            return False
    
    def start_monitor(self, config_name: str) -> bool:
        """Avvia un monitor specifico"""
        if config_name not in self.monitors:
            logger.error(f"Monitor {config_name} non trovato")
            return False
        
        if config_name in self.running_monitors:
            logger.warning(f"Monitor {config_name} già in esecuzione")
            return False
        
        monitor = self.monitors[config_name]
        success = monitor.start_monitoring()
        
        if success:
            self.running_monitors.append(config_name)
            logger.info(f"Monitor {config_name} avviato con successo")
        else:
            logger.error(f"Impossibile avviare monitor {config_name}")
        
        return success
    
    def stop_monitor(self, config_name: str) -> bool:
        """Ferma un monitor specifico"""
        if config_name not in self.monitors:
            logger.error(f"Monitor {config_name} non trovato")
            return False
        
        if config_name not in self.running_monitors:
            logger.warning(f"Monitor {config_name} non in esecuzione")
            return False
        
        monitor = self.monitors[config_name]
        monitor.stop_monitoring()
        self.running_monitors.remove(config_name)
        logger.info(f"Monitor {config_name} fermato")
        return True
    
    def start_all_monitors(self) -> Dict[str, bool]:
        """Avvia tutti i monitor configurati"""
        results = {}
        for config_name in self.monitors:
            results[config_name] = self.start_monitor(config_name)
        return results
    
    def stop_all_monitors(self):
        """Ferma tutti i monitor in esecuzione"""
        for config_name in self.running_monitors.copy():
            self.stop_monitor(config_name)
    
    def get_status(self) -> Dict[str, Dict[str, any]]:
        """Ottiene lo stato di tutti i monitor"""
        status = {}
        for config_name, monitor in self.monitors.items():
            status[config_name] = {
                'config_name': config_name,
                'site_name': monitor.config.name,
                'scraper_type': monitor.config.scraper_type,
                'category': monitor.config.category,
                'check_interval': monitor.check_interval,
                'is_running': config_name in self.running_monitors,
                'seen_articles_count': len(monitor.seen_articles),
                'lock_file': monitor.lock_file_path
            }
        return status
    
    def print_status(self):
        """Stampa lo stato dei monitor"""
        status = self.get_status()
        
        print("\n=== STATO MONITOR ===")
        if not status:
            print("Nessun monitor configurato")
            return
        
        for config_name, info in status.items():
            running_status = "[ATTIVO]" if info['is_running'] else "[FERMO]"
            print(f"\n{config_name.upper()}:")
            print(f"  Nome: {info['site_name']}")
            print(f"  Tipo: {info['scraper_type']}")
            print(f"  Categoria: {info['category']}")
            print(f"  Stato: {running_status}")
            print(f"  Intervallo: {info['check_interval']}s")
            print(f"  Articoli visti: {info['seen_articles_count']}")


# Funzioni di utilità per uso rapido
def start_default_monitors(check_interval: int = 900) -> MonitorManager:
    """Avvia i monitor di default (Carpi Calcio e Comune)"""
    manager = MonitorManager()
    
    # Aggiungi monitor principali
    manager.add_monitor('carpi_calcio', check_interval)
    manager.add_monitor('comune_carpi', check_interval)
    
    return manager

def start_all_available_monitors(check_interval: int = 900) -> MonitorManager:
    """Avvia tutti i monitor disponibili nelle configurazioni"""
    manager = MonitorManager()
    
    for config_name in MONITOR_CONFIGS.keys():
        if config_name != 'youtube_playlist':  # Salta YouTube senza API key
            manager.add_monitor(config_name, check_interval)
    
    return manager


# Esempio di utilizzo come script standalone
if __name__ == "__main__":
    import sys
    import os
    import django
    
    # Configura Django
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
    django.setup()
    
    # Configura logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=== MONITOR MANAGER Ombra del Portico ===")
    
    # Crea manager e aggiungi monitor
    manager = start_default_monitors(600)  # 10 minuti
    
    # Mostra stato
    manager.print_status()
    
    # Avvia tutti i monitor
    print("\nAvvio monitor...")
    results = manager.start_all_monitors()
    
    for config_name, success in results.items():
        status = "[AVVIATO]" if success else "[ERRORE]"
        print(f"{config_name}: {status}")
    
    manager.print_status()
    
    try:
        print("\nMonitor in esecuzione. Premi Ctrl+C per fermare.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nFermando tutti i monitor...")
        manager.stop_all_monitors()
        print("Tutti i monitor fermati. Arrivederci!")