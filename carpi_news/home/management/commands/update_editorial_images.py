from django.core.management.base import BaseCommand
from django.templatetags.static import static
from django.db import models
from home.models import Articolo


class Command(BaseCommand):
    help = 'Aggiorna le immagini di tutti gli editoriali e articoli "Eco del Consiglio" con il logo del sito'

    def handle(self, *args, **options):
        # Trova gli editoriali senza immagine + TUTTI gli Eco del Consiglio (anche con immagine)
        editoriali_senza_foto = Articolo.objects.filter(
            categoria='Editoriale'
        ).filter(
            # Solo editoriali senza foto
            models.Q(foto__isnull=True) | models.Q(foto='') | models.Q(foto__exact='')
        )
        
        # Tutti gli Eco del Consiglio (sostituisci sempre l'immagine)
        eco_consiglio_tutti = Articolo.objects.filter(categoria="L'Eco del Consiglio")
        
        # Combina i due queryset
        articoli_da_aggiornare = editoriali_senza_foto.union(eco_consiglio_tutti)
        
        if not articoli_da_aggiornare.exists():
            self.stdout.write(
                self.style.SUCCESS('Nessun articolo da aggiornare trovato.')
            )
            return

        # URL del logo
        logo_url = static('home/images/portico_logo_nopayoff.png')
        
        # Contatore per statistiche
        updated_count = 0
        
        self.stdout.write(f'Trovati {articoli_da_aggiornare.count()} articoli da aggiornare:')
        self.stdout.write(f'  • Editoriali senza foto: {editoriali_senza_foto.count()}')
        self.stdout.write(f'  • Eco del Consiglio (tutti): {eco_consiglio_tutti.count()}')
        self.stdout.write('')
        
        for articolo in articoli_da_aggiornare:
            old_foto = articolo.foto or 'Nessuna'
            articolo.foto = logo_url
            articolo.save()
            updated_count += 1
            
            self.stdout.write(
                f'[OK] Aggiornato [{articolo.categoria}]: "{articolo.titolo[:50]}..." '
                f'(Foto: {old_foto} -> {logo_url})'
            )

        # Riassunto finale
        self.stdout.write(
            self.style.SUCCESS(
                f'\nCompletato! Aggiornati {updated_count} articoli con il logo del sito.'
            )
        )
        
        # Mostra statistiche per entrambe le categorie
        all_editoriali = Articolo.objects.filter(categoria='Editoriale')
        all_eco_consiglio = Articolo.objects.filter(categoria="L'Eco del Consiglio")
        
        self.stdout.write(f'\nStatistiche finali:')
        self.stdout.write(f'   Totale Editoriali: {all_editoriali.count()}')
        self.stdout.write(f'   Totale Eco del Consiglio: {all_eco_consiglio.count()}')
        
        # Conta quelli con logo
        editoriali_with_logo = all_editoriali.exclude(
            models.Q(foto__isnull=True) | models.Q(foto='') | models.Q(foto__exact='')
        ).count()
        eco_with_logo = all_eco_consiglio.exclude(
            models.Q(foto__isnull=True) | models.Q(foto='') | models.Q(foto__exact='')
        ).count()
        
        self.stdout.write(f'   Editoriali con immagine: {editoriali_with_logo}')
        self.stdout.write(f'   Eco del Consiglio con immagine: {eco_with_logo}')