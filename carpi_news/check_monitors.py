#!/usr/bin/env python3
"""
Script per verificare lo stato dei monitor sul server
"""
import sys
import os
import subprocess
import logging
from datetime import datetime

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')

import django
django.setup()

from home.monitor_configs import MONITOR_CONFIGS
from django.conf import settings

def check_processes():
    """Controlla i processi monitor attivi"""
    print("=== PROCESSI MONITOR ATTIVI ===")
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        monitor_processes = []
        
        for line in result.stdout.split('\n'):
            if ('universal_news_monitor' in line or 
                'start_universal_monitors' in line or
                'monitor' in line.lower()) and 'grep' not in line:
                monitor_processes.append(line)
        
        if monitor_processes:
            for process in monitor_processes:
                print(f"  {process}")
        else:
            print("  Nessun processo monitor trovato")
            
    except Exception as e:
        print(f"  Errore nel controllo processi: {e}")
    print()

def check_lock_files():
    """Controlla i file di lock"""
    print("=== FILE DI LOCK ===")
    lock_dir = 'locks'
    if os.path.exists(lock_dir):
        lock_files = [f for f in os.listdir(lock_dir) if f.endswith('.lock')]
        if lock_files:
            for lock_file in lock_files:
                lock_path = os.path.join(lock_dir, lock_file)
                mtime = os.path.getmtime(lock_path)
                mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                print(f"  {lock_file} (creato: {mtime_str})")
        else:
            print("  Nessun file di lock trovato")
    else:
        print("  Directory locks non trovata")
    print()

def check_log_files():
    """Controlla gli ultimi log"""
    print("=== ULTIMI LOG MONITOR ===")
    log_file = 'logs/monitors.log'
    if os.path.exists(log_file):
        try:
            result = subprocess.run(['tail', '-20', log_file], capture_output=True, text=True)
            print(result.stdout)
        except Exception as e:
            print(f"  Errore nella lettura log: {e}")
    else:
        print("  File log non trovato")
    print()

def check_configurations():
    """Mostra le configurazioni attive"""
    print("=== CONFIGURAZIONI MONITOR ===")
    
    # Da apps.py
    print("Monitor in apps.py:")
    apps_monitors = [
        ('carpi_calcio', 300),
        ('comune_carpi_graphql', 600),
        ('eventi_carpi_graphql', 1800),
        ('ansa_carpi', 300),
        ('youtube_playlist', 1800),
        ('youtube_playlist_2', 1800),
        ('temponews', 600),
        ('voce_carpi', 600),
        ('terre_argine', 900),
    ]
    
    for name, interval in apps_monitors:
        config = MONITOR_CONFIGS.get(name)
        if config:
            print(f"  ✓ {name}: {config.name} ({interval}s)")
        else:
            print(f"  ✗ {name}: CONFIGURAZIONE MANCANTE")
    
    print(f"\nMonitor universali abilitati: {getattr(settings, 'UNIVERSAL_MONITORS', {}).get('ENABLED', 'N/A')}")
    print()

def check_system_status():
    """Controlla stato generale del sistema"""
    print("=== STATO SISTEMA ===")
    
    # Django settings
    print(f"Debug: {settings.DEBUG}")
    print(f"Anthropic API configurata: {'Si' if settings.ANTHROPIC_API_KEY else 'No'}")
    
    # Spazio disco
    try:
        result = subprocess.run(['df', '-h', '.'], capture_output=True, text=True)
        print("Spazio disco:")
        print(result.stdout)
    except:
        print("Impossibile controllare spazio disco")
    
    print()

def main():
    print("=" * 50)
    print("CARPI NEWS - MONITOR STATUS CHECK")
    print(f"Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()
    
    check_system_status()
    check_configurations()
    check_processes()
    check_lock_files()
    check_log_files()
    
    print("=" * 50)
    print("COMANDI UTILI:")
    print("  Riavvia monitor: sudo systemctl restart carpi-news")
    print("  Stop monitor: pkill -f universal_news_monitor")
    print("  Avvia manuale: python start_universal_monitors.py")
    print("  Log in tempo reale: tail -f logs/monitors.log")
    print("=" * 50)

if __name__ == "__main__":
    main()