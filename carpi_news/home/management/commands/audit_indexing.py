"""
Audit pagine con noindex e 404 sul sito.

Uso:
  python manage.py audit_indexing
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Audit noindex nei template e 404 negli articoli'

    def handle(self, *args, **opts):
        self.stdout.write(self.style.NOTICE('\n=== noindex trovati nei template ==='))
        templates_dir = Path(settings.BASE_DIR) / 'home' / 'templates'
        noindex_pattern = re.compile(r'noindex', re.IGNORECASE)
        found_any = False
        for tpl in templates_dir.rglob('*.html'):
            text = tpl.read_text(encoding='utf-8', errors='ignore')
            if noindex_pattern.search(text):
                found_any = True
                lines = [
                    (i + 1, line)
                    for i, line in enumerate(text.split('\n'))
                    if noindex_pattern.search(line)
                ]
                self.stdout.write(f'\n{tpl.relative_to(settings.BASE_DIR)}:')
                for line_number, line in lines:
                    self.stdout.write(f'  L{line_number}: {line.strip()[:120]}')
        if not found_any:
            self.stdout.write('  Nessun noindex trovato nei template.')

        self.stdout.write(self.style.NOTICE('\n=== noindex via header HTTP ==='))
        found_header = False
        for src_dir in [Path(settings.BASE_DIR) / 'home', Path(settings.BASE_DIR) / 'carpi_news']:
            for py in src_dir.rglob('*.py'):
                if py.resolve() == Path(__file__).resolve():
                    continue
                try:
                    text = py.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue
                if 'X-Robots-Tag' in text or "'noindex'" in text or '"noindex"' in text:
                    found_header = True
                    self.stdout.write(f'  {py.relative_to(settings.BASE_DIR)}')
        if not found_header:
            self.stdout.write('  Nessun header noindex trovato nel codice Python.')

        from django.db.models import Count
        from home.models import Articolo

        self.stdout.write(self.style.NOTICE('\n=== Articoli problematici ==='))
        non_approvati = Articolo.objects.filter(approvato=False).count()
        self.stdout.write(f'  Articoli non approvati: {non_approvati}')

        non_pagati = Articolo.objects.filter(
            is_pubbliredazionale=True
        ).exclude(payment_status='completed').count()
        self.stdout.write(f'  Pubbliredazionali non pagati: {non_pagati}')

        dups = (
            Articolo.objects.values('slug')
            .annotate(c=Count('slug'))
            .filter(c__gt=1)
        )
        if dups.exists():
            self.stdout.write(self.style.WARNING(
                f'  ATTENZIONE: {dups.count()} slug duplicati'
            ))
            for dup in dups[:10]:
                self.stdout.write(f'    {dup["slug"]} x{dup["c"]}')
        else:
            self.stdout.write('  Slug duplicati: 0')
