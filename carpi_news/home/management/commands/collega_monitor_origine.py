"""Collega al monitor d'origine gli articoli nati prima del campo monitor_origine (28/9/2026).

Il monitor si ricava dal dominio della fonte, con la stessa regola della rielaborazione
(home.rielaborazione_ai.trova_monitor): a parita' di dominio vince il monitor attivo con
un prompt. Serve al selettore "Fuori dall'indice Google" del monitor, che vale per gli
articoli collegati.

    python manage.py collega_monitor_origine            # mostra cosa farebbe
    python manage.py collega_monitor_origine --esegui
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from home.models import Articolo, MonitorConfig
from home.rielaborazione_ai import _dominio


class Command(BaseCommand):
    help = "Collega gli articoli senza monitor_origine al monitor con lo stesso dominio della fonte"

    def add_arguments(self, parser):
        parser.add_argument('--esegui', action='store_true', help='Scrive nel database (senza: solo resoconto)')

    def handle(self, *args, **opt):
        monitor_per_dominio = {}
        monitors = sorted(MonitorConfig.objects.all(), key=lambda m: (not m.is_active, not m.ai_system_prompt, m.pk))
        for m in monitors:
            monitor_per_dominio.setdefault(_dominio(m.base_url), m)
        monitor_per_dominio.pop('', None)

        da_collegare = defaultdict(list)
        senza_monitor = Counter()
        for pk, fonte in Articolo.objects.filter(monitor_origine__isnull=True).exclude(fonte='').exclude(
                fonte__isnull=True).values_list('pk', 'fonte').iterator():
            dom = _dominio(fonte)
            m = monitor_per_dominio.get(dom)
            if m:
                da_collegare[m].append(pk)
            elif dom:
                senza_monitor[dom] += 1

        for m, ids in sorted(da_collegare.items(), key=lambda x: -len(x[1])):
            self.stdout.write(f"{len(ids):6d}  {m.name}{'  [noindex]' if m.noindex else ''}")
        self.stdout.write(f"Totale da collegare: {sum(len(v) for v in da_collegare.values())}")
        self.stdout.write(f"Domini senza monitor (restano scollegati): {senza_monitor.most_common(15)}")

        if not opt['esegui']:
            self.stdout.write("Prova a vuoto: aggiungi --esegui per scrivere.")
            return
        # update() diretto: niente post_save (immagini, social, localizzazione) sugli articoli vecchi
        for m, ids in da_collegare.items():
            for i in range(0, len(ids), 500):
                Articolo.objects.filter(pk__in=ids[i:i + 500], monitor_origine__isnull=True).update(monitor_origine=m)
        self.stdout.write(self.style.SUCCESS("Fatto."))
