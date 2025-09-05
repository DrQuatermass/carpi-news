#!/usr/bin/env python3
"""
Script di deploy per Ombra del Portico su Aruba
Esegue le operazioni necessarie per il deployment in produzione
"""

import os
import sys
import django
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
django.setup()

from django.core.management import execute_from_command_line
from django.conf import settings

def main():
    """Esegue le operazioni di deploy"""
    print("Iniziando deploy Ombra del Portico...")
    
    # 1. Controlla configurazione
    print("\n1. Controllo configurazione...")
    if settings.DEBUG:
        print("ERRORE: DEBUG=True in produzione!")
        return False
    print("OK DEBUG=False")
    print(f"OK ALLOWED_HOSTS: {settings.ALLOWED_HOSTS}")
    
    # 2. Migrazione database
    print("\n2. Migrazione database...")
    try:
        execute_from_command_line(['manage.py', 'migrate', '--noinput'])
        print("OK Migrazioni completate")
    except Exception as e:
        print(f"ERRORE nelle migrazioni: {e}")
        return False
    
    # 3. Raccolta file statici
    print("\n3. Raccolta file statici...")
    try:
        execute_from_command_line(['manage.py', 'collectstatic', '--noinput'])
        print("OK File statici raccolti")
    except Exception as e:
        print(f"ERRORE nella raccolta file statici: {e}")
        return False
    
    # 4. Test configurazione email
    print("\n4. Test configurazione email...")
    try:
        from home.email_notifications import send_test_email
        if send_test_email():
            print("OK Configurazione email OK")
        else:
            print("WARNING Configurazione email fallita (controllare logs)")
    except Exception as e:
        print(f"ERRORE test email: {e}")
    
    # 5. Verifica directory necessarie
    print("\n5. Verifica directory...")
    directories = ['logs', 'media', 'staticfiles', 'locks']
    for directory in directories:
        path = Path(directory)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            print(f"OK Creata directory: {directory}")
        else:
            print(f"OK Directory presente: {directory}")
    
    # 6. Pulizia file di cache
    print("\n6. Pulizia cache...")
    try:
        import shutil
        for root, dirs, files in os.walk('.'):
            if '__pycache__' in dirs:
                shutil.rmtree(os.path.join(root, '__pycache__'))
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.pyc'):
                    os.remove(os.path.join(root, file))
        print("OK Cache pulita")
    except Exception as e:
        print(f"WARNING Errore pulizia cache: {e}")
    
    print("\nDeploy completato con successo!")
    print("\nProssimi passi per Aruba:")
    print("1. Carica tutti i file sul server via FTP/SFTP")
    print("2. Configura il file .htaccess")
    print("3. Verifica che il dominio punti alla directory corretta")
    print("4. Avvia il sistema di monitoraggio: python start_universal_monitors.py")
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)