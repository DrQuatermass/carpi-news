"""Cancella gli articoli non approvati vecchi, con registro e immagini (home/eliminazione.py).

    python manage.py elimina_non_approvati              # prova: conta e basta
    python manage.py elimina_non_approvati --esegui     # cancella davvero
    python manage.py elimina_non_approvati --giorni 30 --esegui

Esclusi pubbliredazionali e articoli con post o link brevi sui social.
"""
from django.core.management.base import BaseCommand

from home.eliminazione import candidati_pulizia, elimina_in_blocco


class Command(BaseCommand):
    help = "Cancella gli articoli non approvati piu' vecchi di N giorni (default 7), lasciando il registro"

    def add_arguments(self, parser):
        parser.add_argument('--giorni', type=int, default=7)
        parser.add_argument('--esegui', action='store_true', help='Cancella davvero (senza: solo conteggio)')
        parser.add_argument('--limite', type=int, help='Massimo numero di articoli')

    def handle(self, *args, **opt):
        qs = candidati_pulizia(opt['giorni'])
        if opt['limite']:
            qs = qs.filter(pk__in=list(qs.values_list('pk', flat=True)[:opt['limite']]))
        self.stdout.write(f"Non approvati piu' vecchi di {opt['giorni']} giorni: {qs.count()}")
        articoli, file, byte = elimina_in_blocco(qs, motivo='pulizia', esegui=opt['esegui'],
                                                 log=lambda m: self.stdout.write(m))
        if opt['esegui']:
            self.stdout.write(self.style.SUCCESS(
                f"Cancellati {articoli} articoli e {file} immagini ({byte / 1e6:.1f} MB)"))
        else:
            self.stdout.write(self.style.WARNING(
                f"Prova: si cancellerebbero {articoli} articoli e {file} immagini ({byte / 1e6:.1f} MB). "
                "Aggiungi --esegui per farlo."))
