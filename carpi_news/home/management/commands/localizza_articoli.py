"""Localizza gli articoli approvati: comune, luogo e coordinate (home/localizzazione.py).

Gli articoli nuovi si localizzano da soli all'approvazione (home/signals.py). Il comando serve per
l'arretrato e per recuperare quelli rimasti indietro (es. API non raggiungibile):
    python manage.py localizza_articoli                        # approvati degli ultimi 7 giorni senza luogo
    python manage.py localizza_articoli --tutti --solo-testo   # gratis, solo comune
    python manage.py localizza_articoli --tutti --limit 1000   # con AI, ~0,2 centesimi ad articolo
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from home.localizzazione import localizza
from home.models import Articolo


class Command(BaseCommand):
    help = "Localizza gli articoli approvati (comune, luogo, coordinate)"

    def add_arguments(self, parser):
        parser.add_argument('--tutti', action='store_true', help="Tutto l'arretrato, non solo gli ultimi 7 giorni")
        parser.add_argument('--solo-testo', action='store_true', help="Solo comune con le parole chiave, senza AI (gratis)")
        parser.add_argument('--rifai', action='store_true',
                            help="Rifai anche gli articoli gia' localizzati solo col testo (per passarli all'AI)")
        parser.add_argument('--limit', type=int, default=30, help="Articoli massimi per giro (default 30, 0 = nessun limite)")
        parser.add_argument('--dry-run', action='store_true', help="Mostra il risultato senza salvare")

    def handle(self, *args, **options):
        qs = Articolo.objects.filter(approvato=True).exclude(luogo_origine='manuale')
        if options['rifai']:
            qs = qs.filter(Q(luogo_aggiornato__isnull=True) | Q(luogo_origine='testo'))
        else:
            qs = qs.filter(luogo_aggiornato__isnull=True)
        if not options['tutti']:
            qs = qs.filter(data_pubblicazione__gte=timezone.now() - timedelta(days=7))
        qs = qs.order_by('-data_pubblicazione')
        if options['limit']:
            qs = qs[:options['limit']]

        usa_ai = not options['solo_testo']
        conteggio = {}
        for articolo in qs:
            origine = localizza(articolo, usa_ai=usa_ai, salva=not options['dry_run'])
            conteggio[origine] = conteggio.get(origine, 0) + 1
            if options['verbosity'] > 1 or options['dry_run']:
                punto = f"{articolo.lat:.4f},{articolo.lng:.4f}" if articolo.lat is not None else '-'
                self.stdout.write(f"[{origine}] {articolo.comune} | {articolo.luogo_nome or '-'} | "
                                  f"{articolo.luogo_indirizzo or '-'} | {punto}{' preciso' if articolo.luogo_preciso else ''}"
                                  f" | {articolo.titolo[:60]}")
        self.stdout.write(f"Localizzati: {sum(conteggio.values())} {conteggio}")
