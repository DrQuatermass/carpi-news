#!/usr/bin/env python
import os
import sys
import django

# Aggiungi il percorso del progetto
sys.path.append('C:/news/carpi_news')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
django.setup()

from home.models import Articolo

# Controlla articoli
total = Articolo.objects.count()
approved = Articolo.objects.filter(approvato=True).count()

print(f"Articoli totali: {total}")
print(f"Articoli approvati: {approved}")
print("\nPrimi 5 articoli:")
for i, a in enumerate(Articolo.objects.all()[:5], 1):
    print(f"{i}. {a.titolo[:50]}... (Approvato: {a.approvato})")