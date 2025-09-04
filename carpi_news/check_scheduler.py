#!/usr/bin/env python3
import sys
import os
import django
from datetime import datetime

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")
django.setup()

from home.models import Articolo
from django.utils import timezone

def check_scheduler_status():
    """Controlla lo stato dello scheduler dell'editoriale"""
    
    # Controlla se esiste già un editoriale per oggi
    today = timezone.now().date()
    editorial_today = Articolo.objects.filter(
        categoria='Editoriale', 
        data_pubblicazione__date=today
    )
    
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    print(f"Data odierna: {today}")
    print(f"Ora attuale: {current_time}")
    print(f"Editoriale di oggi presente: {'Si' if editorial_today.exists() else 'No'}")
    
    if editorial_today.exists():
        editorial = editorial_today.first()
        print(f"Titolo editoriale: {editorial.titolo}")
        print(f"Pubblicato alle: {editorial.data_pubblicazione.strftime('%H:%M')}")
    
    # Calcola quando sarà il prossimo editoriale
    if now.hour < 8:
        print(f"Prossimo editoriale: oggi alle 8:00 (tra {8 - now.hour} ore e {60 - now.minute} minuti)")
    elif not editorial_today.exists():
        print("ATTENZIONE: L'editoriale doveva essere gia generato alle 8:00 ma non e presente!")
        print("Probabilmente lo scheduler non e attivo")
    else:
        print("Prossimo editoriale: domani alle 8:00")
    
    return editorial_today.exists()

if __name__ == "__main__":
    check_scheduler_status()