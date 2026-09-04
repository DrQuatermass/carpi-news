"""
Ricalibra il contatore `views` degli articoli, gonfiato dai crawler fino al
settembre 2026 (facebookexternalhit non veniva riconosciuto come bot: ~14 richieste
per ogni lettura umana).

Uso:
  manage.py ricalibra_views --csv views_umane.csv [--divisore 13.7] [--dry-run]

Il CSV (slug,views_umane) viene dai log Apache (tool "visite"), disponibili dal
18/07/2026: per quegli articoli il contatore viene SOSTITUITO con le letture umane.
Per tutti gli altri il valore viene DIVISO per --divisore (rapporto misurato tra
contatore e letture umane sugli articoli del 19/7-3/9/2026: 86.657 / 6.344).
Il valore precedente viene salvato in views_precedente.csv accanto al CSV.
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError

from home.models import Articolo


class Command(BaseCommand):
    help = "Ricalibra il contatore views (crawler esclusi) dai log o per divisione"

    def add_arguments(self, parser):
        parser.add_argument('--csv', help='CSV slug,views_umane dai log (articoli dal 18/07/2026)')
        parser.add_argument('--divisore', type=float, default=13.7, help='divisore per gli articoli senza dato nei log')
        parser.add_argument('--dry-run', action='store_true', help='mostra solo cosa cambierebbe')

    def handle(self, *args, **opts):
        from_log = {}
        if opts['csv']:
            if not os.path.exists(opts['csv']):
                raise CommandError(f"CSV non trovato: {opts['csv']}")
            with open(opts['csv'], encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    try:
                        from_log[row['slug']] = int(float(row['views_umane']))
                    except (KeyError, ValueError):
                        continue
        divisore = opts['divisore']
        if divisore <= 0:
            raise CommandError('--divisore deve essere > 0')

        backup_path = os.path.join(os.path.dirname(os.path.abspath(opts['csv'])) if opts['csv'] else '.', 'views_precedente.csv')
        n_log = n_div = 0
        tot_prima = tot_dopo = 0
        rows = []
        for a in Articolo.objects.filter(approvato=True).only('id', 'slug', 'views').iterator(chunk_size=500):
            prima = a.views or 0
            if a.slug in from_log:
                dopo = from_log[a.slug]
                n_log += 1
            else:
                dopo = int(round(prima / divisore))
                n_div += 1
            tot_prima += prima
            tot_dopo += dopo
            rows.append((a.id, a.slug, prima, dopo))

        self.stdout.write(f"articoli: {len(rows)} | dai log: {n_log} | per divisione (/{divisore}): {n_div}")
        self.stdout.write(f"views totali: prima {tot_prima} -> dopo {tot_dopo}")
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('dry-run: nessuna modifica'))
            return

        with open(backup_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['id', 'slug', 'views_prima', 'views_dopo'])
            w.writerows(rows)
        for art_id, _slug, prima, dopo in rows:
            if prima != dopo:
                Articolo.objects.filter(pk=art_id).update(views=dopo)
        self.stdout.write(self.style.SUCCESS(f"fatto: valori precedenti salvati in {backup_path}"))
