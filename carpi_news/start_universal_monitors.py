#!/usr/bin/env python3
"""
Script di avvio per il sistema di monitoraggio universale Ombra del Portico
Sostituisce i vecchi monitor individuali
"""
import sys
import os
import logging
import time
from django.conf import settings
# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')

import django
django.setup()

from home.monitor_manager import MonitorManager
from home.logger_config import setup_centralized_logger, cleanup_old_logs

def main():
    """Avvia tutti i monitor configurati"""
    # Setup logging centralizzato
    logger = setup_centralized_logger('carpi_news_main', 'INFO')
    
    # Controllo se il sistema è abilitato
    if not settings.UNIVERSAL_MONITORS.get('ENABLED', True):
        print("=== Ombra del Portico - UNIVERSAL MONITOR SYSTEM ===")
        print("SISTEMA DISABILITATO - I monitor sono stati disattivati nella configurazione")
        print("Per riattivare, imposta UNIVERSAL_MONITORS_ENABLED=True nel file .env")
        logger.info("Sistema di monitoraggio disabilitato tramite configurazione")
        return 0
    
    # Pulizia vecchi log
    try:
        cleaned_files = cleanup_old_logs()
        if cleaned_files:
            logger.info(f"File log vecchi puliti: {len(cleaned_files)}")
    except Exception as e:
        logger.warning(f"Errore nella pulizia log: {e}")
    
    print("=== Ombra del Portico - UNIVERSAL MONITOR SYSTEM ===")
    
    # Crea manager
    manager = MonitorManager()
    
    # Aggiungi monitor principali
    configs = [
        ('carpi_calcio', 300),           # 5 minuti
        ('comune_carpi_graphql', 600),   # 10 minuti (GraphQL con dati ricchi)
        ('eventi_carpi_graphql', 1800),  # 30 minuti (eventi con descrizione_estesa)
        ('ansa_carpi', 300),             # 5 minuti (notizie nazionali su Carpi)
        ('voce_carpi', 600),             # 10 minuti (La Voce di Carpi)
        ('voce_carpi_sport', 600),       # 10 minuti (La Voce di Carpi Sport)
        ('temponews', 600),              # 10 minuti (TempoNews Carpi)
        ('terre_argine', 900),           # 15 minuti (Unione Terre d'Argine)
        ('youtube_playlist', 1800),      # 30 minuti (YouTube Playlist 1)
        ('youtube_playlist_2', 1800),    # 30 minuti (YouTube Playlist 2)
        ('email_comunicati', 300),       # 5 minuti (Email comunicati stampa + IFTTT)
    ]
    
    for config_name, interval in configs:
        success = manager.add_monitor(config_name, interval)
        if success:
            logger.info(f"Monitor {config_name} configurato (intervallo: {interval}s)")
        else:
            logger.error(f"Errore nella configurazione monitor {config_name}")
    
    # Mostra stato
    manager.print_status()
    
    # Avvia tutti i monitor
    print("\nAvvio monitor...")
    results = manager.start_all_monitors()
    
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    if success_count == 0:
        print("ERRORE: Nessun monitor avviato con successo!")
        return 1
    
    print(f"\n{success_count}/{total_count} monitor avviati con successo")
    manager.print_status()
    
    try:
        print("\nMonitor attivi. Premi Ctrl+C per fermare.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nFermando tutti i monitor...")
        manager.stop_all_monitors()
        print("Sistema fermato. Arrivederci!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
