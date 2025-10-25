"""
Comando per estrarre automaticamente le date dagli articoli di Eventi/Cultura
e popolare il campo data_evento.

Estrae date dal contenuto usando pattern intelligenti e le assegna automaticamente.
"""
from django.core.management.base import BaseCommand
from django.db import models
from home.models import Articolo
from datetime import datetime, date
import re
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Estrae automaticamente le date dagli articoli di Eventi/Cultura'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra cosa verrebbe modificato senza applicare le modifiche',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Sovrascrivi anche se data_evento è già impostata',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']

        if dry_run:
            self.stdout.write(self.style.WARNING('=== MODALITÀ DRY-RUN ===\n'))

        # Trova articoli Eventi/Cultura
        query = Articolo.objects.filter(
            models.Q(categoria__icontains='Eventi') |
            models.Q(categoria__icontains='Cultura')
        )

        if not force:
            # Solo articoli senza data_evento
            query = query.filter(data_evento__isnull=True)

        articoli = query.order_by('-data_pubblicazione')
        total = articoli.count()

        self.stdout.write(f'Trovati {total} articoli da processare\n')
        self.stdout.write('='*70 + '\n')

        updated = 0
        skipped = 0
        errors = 0

        for articolo in articoli:
            try:
                data_estratta = self.estrai_data(articolo)

                if data_estratta:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'{"[DRY-RUN] " if dry_run else ""}[OK] {articolo.titolo[:50]}...'
                        )
                    )
                    self.stdout.write(f'     Data estratta: {data_estratta.strftime("%d/%m/%Y")}')

                    if not dry_run:
                        articolo.data_evento = data_estratta
                        articolo.save(update_fields=['data_evento'])

                    updated += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'[SKIP] {articolo.titolo[:50]}... - Nessuna data trovata'
                        )
                    )
                    skipped += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'[ERRORE] {articolo.titolo[:50]}... - {str(e)}'
                    )
                )
                errors += 1

        # Riepilogo
        self.stdout.write('\n' + '='*70)
        if dry_run:
            self.stdout.write(self.style.WARNING('RIEPILOGO DRY-RUN:'))
        else:
            self.stdout.write(self.style.SUCCESS('RIEPILOGO:'))
        self.stdout.write(f'Articoli processati: {total}')
        self.stdout.write(f'Date estratte: {updated}')
        self.stdout.write(f'Saltati (nessuna data): {skipped}')
        self.stdout.write(f'Errori: {errors}')
        self.stdout.write('='*70)

    def estrai_data(self, articolo):
        """
        Estrae la data dall'articolo usando pattern intelligenti.
        Restituisce un oggetto date o None se non trova date.
        """
        # Rimuovi HTML
        contenuto = re.sub(r'<[^>]+>', '', articolo.contenuto)

        # Mappa mesi
        mesi = {
            'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4,
            'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
            'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12
        }

        # Anno corrente o prossimo
        anno_corrente = datetime.now().year
        mese_corrente = datetime.now().month

        # Pattern 1: "28 al 31 ottobre" - prende la data di inizio
        pattern1 = r'(\d{1,2})\s+al\s+\d{1,2}\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)'
        match = re.search(pattern1, contenuto, re.IGNORECASE)
        if match:
            giorno = int(match.group(1))
            mese = mesi[match.group(2).lower()]
            # Se il mese è passato, usa anno prossimo
            anno = anno_corrente if mese >= mese_corrente else anno_corrente + 1
            try:
                return date(anno, mese, giorno)
            except ValueError:
                pass

        # Pattern 2: "28 ottobre" - singola data
        pattern2 = r'(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)'
        match = re.search(pattern2, contenuto, re.IGNORECASE)
        if match:
            giorno = int(match.group(1))
            mese = mesi[match.group(2).lower()]
            anno = anno_corrente if mese >= mese_corrente else anno_corrente + 1
            try:
                return date(anno, mese, giorno)
            except ValueError:
                pass

        # Pattern 3: "2025-10-28" formato ISO
        pattern3 = r'(\d{4})-(\d{2})-(\d{2})'
        match = re.search(pattern3, contenuto)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        # Pattern 4: "28/10/2025" o "28/10"
        pattern4 = r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?'
        match = re.search(pattern4, contenuto)
        if match:
            giorno = int(match.group(1))
            mese = int(match.group(2))
            anno = int(match.group(3)) if match.group(3) else (anno_corrente if mese >= mese_corrente else anno_corrente + 1)
            try:
                return date(anno, mese, giorno)
            except ValueError:
                pass

        return None
