"""
Configurazione logging centralizzata per tutti i monitor
"""
import logging
import logging.handlers
import os
from pathlib import Path


def setup_centralized_logger(name: str = None, log_level: str = "WARNING") -> logging.Logger:
    """
    Configura logger centralizzato per tutti i monitor
    
    Args:
        name: Nome del logger (default: 'carpi_news_monitors')
        log_level: Livello di logging (DEBUG, INFO, WARNING, ERROR)
    
    Returns:
        Logger configurato
    """
    if name is None:
        name = 'carpi_news_monitors'
    
    logger = logging.getLogger(name)
    
    # Evita duplicazione se già configurato
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Directory log centralizzata
    log_dir = Path(__file__).parent.parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    # File log unico per tutti i monitor
    log_file = log_dir / 'monitors.log'
    
    # Formatter ottimizzato e leggibile
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Handler per file con rotazione (ridotta)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=2*1024*1024,  # 2 MB (ridotto da 10 MB)
        backupCount=2,         # solo 2 backup (ridotto da 5)
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.WARNING)  # Solo WARNING e ERROR (ridotto da DEBUG)
    
    # Handler per console (solo INFO e superiori)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    ))
    console_handler.setLevel(logging.WARNING)  # Solo WARNING e superiori (ridotto da INFO)
    
    # Aggiungi handler
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Non propagare ai logger parent
    logger.propagate = False
    
    logger.info(f"🚀 Sistema logging avviato - File: {log_file}")
    
    return logger


def get_monitor_logger(monitor_name: str) -> logging.Logger:
    """
    Ottiene logger specifico per un monitor
    
    Args:
        monitor_name: Nome del monitor (es. 'carpi_calcio', 'comune_carpi')
    
    Returns:
        Logger configurato per il monitor specifico
    """
    logger_name = f'carpi_news_monitors.{monitor_name}'
    
    # Se il logger principale non è configurato, configuralo
    main_logger = logging.getLogger('carpi_news_monitors')
    if not main_logger.handlers:
        setup_centralized_logger()
    
    # Crea logger specifico per il monitor
    monitor_logger = logging.getLogger(logger_name)
    
    return monitor_logger


def cleanup_old_logs():
    """Pulisce i vecchi file log sparsi"""
    try:
        log_patterns = [
            'logs/playlist_monitor.log',
            'logs/carpi_news.log', 
            'monitor.log',
            'migration_log.txt'
        ]
        
        base_path = Path(__file__).parent.parent
        cleaned_files = []
        
        for pattern in log_patterns:
            log_file = base_path / pattern
            if log_file.exists():
                # Backup del contenuto nel nuovo log se non vuoto
                if log_file.stat().st_size > 0:
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            old_content = f.read()
                        
                        # Scrivi nel nuovo log centralizzato
                        logger = get_monitor_logger('migration')
                        logger.info(f"=== CONTENUTO MIGRATO DA {log_file} ===")
                        logger.info(old_content)
                        logger.info(f"=== FINE CONTENUTO DA {log_file} ===")
                        
                    except Exception as e:
                        print(f"Errore nel backup di {log_file}: {e}")
                
                # Rimuovi il vecchio file
                log_file.unlink()
                cleaned_files.append(str(log_file))
        
        if cleaned_files:
            logger = get_monitor_logger('cleanup')
            logger.info(f"File log puliti: {cleaned_files}")
        
        return cleaned_files
        
    except Exception as e:
        print(f"Errore nella pulizia log: {e}")
        return []


# Configurazione di default per retrocompatibilità
def configure_django_logging():
    """Configura logging per Django se non già fatto"""
    import django.conf
    
    if hasattr(django.conf.settings, 'LOGGING'):
        return
    
    # Setup logging configuration per Django
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'detailed': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            'simple': {
                'format': '%(asctime)s - %(levelname)s - %(message)s',
                'datefmt': '%H:%M:%S',
            },
        },
        'handlers': {
            'file': {
                'level': 'WARNING',  # Solo WARNING e ERROR (ridotto da DEBUG)
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': os.path.join(os.path.dirname(__file__), '..', 'logs', 'monitors.log'),
                'maxBytes': 2*1024*1024,  # 2 MB (ridotto da 10 MB)
                'backupCount': 2,         # solo 2 backup (ridotto da 5)
                'formatter': 'detailed',
                'encoding': 'utf-8',
            },
            'console': {
                'level': 'WARNING',  # Solo WARNING e superiori (ridotto da INFO)
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
            },
        },
        'loggers': {
            'carpi_news_monitors': {
                'handlers': ['file', 'console'],
                'level': 'WARNING',  # Solo WARNING e superiori (ridotto da DEBUG)
                'propagate': False,
            },
            'home': {
                'handlers': ['file', 'console'], 
                'level': 'WARNING',  # Solo WARNING e superiori (ridotto da INFO)
                'propagate': False,
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'WARNING',
        }
    }
    
    # Se Django è configurato, applica il logging
    try:
        if django.conf.settings.configured:
            django.conf.settings.LOGGING = LOGGING
            import logging.config
            logging.config.dictConfig(LOGGING)
    except:
        # Fallback se Django non è ancora configurato
        pass


# Auto-setup al momento dell'import
if __name__ != "__main__":
    try:
        setup_centralized_logger()
    except Exception:
        pass  # Ignora errori durante l'import


# Production ready - no test code