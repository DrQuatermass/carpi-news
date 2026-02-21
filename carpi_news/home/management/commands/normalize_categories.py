"""
Management command per normalizzare tutte le categorie esistenti nel database.
Applica il metodo normalize_category() a tutti gli articoli.
"""

from django.core.management.base import BaseCommand
from home.models import Articolo


class Command(BaseCommand):
    help = 'Normalizza tutte le categorie degli articoli esistenti'

    def handle(self, *args, **options):
        self.stdout.write("Inizio normalizzazione categorie...")

        # Conta articoli prima della normalizzazione
        total_articoli = Articolo.objects.count()
        self.stdout.write(f"Trovati {total_articoli} articoli")

        # Raggruppa per categoria prima della normalizzazione
        categorie_before = {}
        for articolo in Articolo.objects.all():
            cat = articolo.categoria or 'None'
            categorie_before[cat] = categorie_before.get(cat, 0) + 1

        self.stdout.write("\n--- Categorie PRIMA della normalizzazione ---")
        for cat, count in sorted(categorie_before.items()):
            self.stdout.write(f"  {cat}: {count}")

        # Normalizza tutte le categorie
        updated_count = 0
        for articolo in Articolo.objects.all():
            old_cat = articolo.categoria
            new_cat = Articolo.normalize_category(articolo.categoria)

            if old_cat != new_cat:
                articolo.categoria = new_cat
                articolo.save(update_fields=['categoria'])
                updated_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  Aggiornato: '{old_cat}' -> '{new_cat}' (Articolo ID: {articolo.id})")
                )

        # Raggruppa per categoria dopo la normalizzazione
        categorie_after = {}
        for articolo in Articolo.objects.all():
            cat = articolo.categoria or 'None'
            categorie_after[cat] = categorie_after.get(cat, 0) + 1

        self.stdout.write("\n--- Categorie DOPO la normalizzazione ---")
        for cat, count in sorted(categorie_after.items()):
            self.stdout.write(f"  {cat}: {count}")

        self.stdout.write(
            self.style.SUCCESS(f"\n✓ Normalizzazione completata: {updated_count} articoli aggiornati su {total_articoli}")
        )
