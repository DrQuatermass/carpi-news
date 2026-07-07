"""
Riapplica il sistema di internal linking agli articoli esistenti.

A differenza di apply_internal_links_bulk, questo comando prima RIMUOVE i link
interni gia' presenti (sfilando i tag <a class="internal-link">), poi riapplica
la logica aggiornata di add_internal_links. Serve per propagare agli articoli
vecchi le nuove regole (match a parola intera, esclusione orari, nomi propri).

NON ha costi API: e' solo Python + query al database.
"""
import re
import logging

from django.core.management.base import BaseCommand
from home.models import Articolo
from home.content_polisher import ContentPolisher

logger = logging.getLogger(__name__)

# Sfila un <a ... class="internal-link" ...>INNER</a> lasciando solo INNER
INTERNAL_LINK_RE = re.compile(
    r'<a\b[^>]*class="internal-link"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
COUNT_LINKS_RE = re.compile(r'class="internal-link"', re.IGNORECASE)


class Command(BaseCommand):
    help = 'Rimuove i link interni esistenti e riapplica la logica aggiornata agli articoli approvati'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Simula senza salvare')
        parser.add_argument('--limit', type=int,
                            help='Numero massimo di articoli da processare')
        parser.add_argument('--skip', type=int, default=0,
                            help='Salta i primi N articoli')
        parser.add_argument('--category', type=str,
                            help='Processa solo articoli di questa categoria')
        parser.add_argument('--show', type=int, default=8,
                            help='Quanti esempi di variazione mostrare (default: 8)')

    @staticmethod
    def _strip_internal_links(html: str) -> str:
        # Ripete finche' non ci sono piu' match (gestisce eventuali annidamenti)
        prev = None
        cur = html
        while prev != cur:
            prev = cur
            cur = INTERNAL_LINK_RE.sub(r'\1', cur)
        return cur

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options.get('limit')
        skip = options.get('skip', 0)
        category = options.get('category')
        show = options.get('show', 8)

        qs = Articolo.objects.filter(approvato=True).order_by('-data_pubblicazione')
        if category:
            qs = qs.filter(categoria=category)
        if skip:
            qs = qs[skip:]
        if limit:
            qs = qs[:limit]

        total = qs.count()
        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] Nessuna modifica verra\' salvata\n'))
        self.stdout.write(f'=== Riapplicazione internal links a {total} articoli ===\n')

        polisher = ContentPolisher()
        processed = changed = errors = 0
        links_before_tot = links_after_tot = 0
        shown = 0

        for idx, art in enumerate(qs, 1):
            try:
                original = art.contenuto or ''
                links_before = len(COUNT_LINKS_RE.findall(original))

                stripped = self._strip_internal_links(original)
                relinked = polisher.add_internal_links(
                    stripped,
                    article_title=art.titolo,
                    current_article_slug=art.slug,
                    current_article_date=art.data_pubblicazione,
                )
                links_after = len(COUNT_LINKS_RE.findall(relinked))

                links_before_tot += links_before
                links_after_tot += links_after
                processed += 1

                if relinked != original:
                    changed += 1
                    if shown < show:
                        shown += 1
                        self.stdout.write(self.style.SUCCESS(
                            f'[{idx}/{total}] {art.titolo[:55]}  '
                            f'({links_before} -> {links_after} link)'
                        ))
                    if not dry_run:
                        art.contenuto = relinked
                        art.save(update_fields=['contenuto'])
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(
                    f'[{idx}/{total}] ERRORE su "{art.titolo[:40]}": {e}'
                ))
                logger.error(f'reapply_internal_links su {art.slug}: {e}', exc_info=True)

        self.stdout.write('\n=== Riepilogo ===')
        self.stdout.write(f'Processati: {processed}/{total}')
        self.stdout.write(f'Articoli modificati: {changed}')
        self.stdout.write(f'Link interni totali: {links_before_tot} -> {links_after_tot}')
        self.stdout.write(f'Errori: {errors}')
        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] Nessuna modifica salvata'))
        else:
            self.stdout.write(self.style.SUCCESS('\n[COMPLETATO] Modifiche salvate'))
