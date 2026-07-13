"""
Corregge l'anno di data_evento per gli articoli in cui l'anno è "slittato"
avanti a causa della vecchia logica di estrazione (che ancorava l'anno a
datetime.now() invece che alla data di pubblicazione).

Un evento viene annunciato poco prima di accadere: se la sua data_evento cade
troppo oltre la data di pubblicazione (oltre ~11 mesi), l'anno è quasi
sicuramente sbagliato. In quel caso arretriamo l'anno di un anno alla volta
finché l'evento rientra in una finestra plausibile rispetto alla pubblicazione.
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
import logging

logger = logging.getLogger(__name__)

# Un evento può stare al massimo ~11 mesi dopo la pubblicazione dell'articolo.
# Oltre questa soglia consideriamo l'anno slittato.
MAX_GIORNI_DOPO_PUBBLICAZIONE = 335


def _sottrai_un_anno(d):
    """Sottrae un anno gestendo il 29 febbraio (che negli anni non bisestili
    non esiste: in quel caso ripiega sul 28)."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


class Command(BaseCommand):
    help = "Corregge l'anno di data_evento slittato in avanti rispetto alla pubblicazione"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra cosa verrebbe corretto senza applicare le modifiche',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('=== MODALITÀ DRY-RUN ===\n'))

        articoli = Articolo.objects.filter(
            data_evento__isnull=False,
            data_pubblicazione__isnull=False,
        ).order_by('data_evento')

        total = articoli.count()
        self.stdout.write(f'Controllo {total} articoli con data_evento...\n')
        self.stdout.write('=' * 70)

        corretti = 0

        for articolo in articoli:
            pub = articolo.data_pubblicazione.date()
            data_evento = articolo.data_evento

            nuova_data = data_evento
            # Arretra un anno alla volta finché l'evento rientra nella finestra.
            while (nuova_data - pub).days > MAX_GIORNI_DOPO_PUBBLICAZIONE:
                nuova_data = _sottrai_un_anno(nuova_data)

            if nuova_data != data_evento:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{"[DRY-RUN] " if dry_run else ""}[FIX] {(articolo.titolo or "")[:50]}...'
                    )
                )
                self.stdout.write(
                    f'     {data_evento} -> {nuova_data} (pubblicato {pub})'
                )

                if not dry_run:
                    articolo.data_evento = nuova_data
                    articolo.save(update_fields=['data_evento'])

                corretti += 1

        self.stdout.write('\n' + '=' * 70)
        if dry_run:
            self.stdout.write(self.style.WARNING('RIEPILOGO DRY-RUN:'))
        else:
            self.stdout.write(self.style.SUCCESS('RIEPILOGO:'))
        self.stdout.write(f'Articoli controllati: {total}')
        self.stdout.write(f'Date corrette: {corretti}')
        self.stdout.write('=' * 70)
