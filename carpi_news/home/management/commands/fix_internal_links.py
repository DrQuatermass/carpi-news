"""
Management command per correggere i link interni negli articoli esistenti
Applica le nuove logiche:
1. Link puntano agli articoli più recenti (non più vecchi)
2. Rimuove link su parole generiche (quando, dove, info, etc.)
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
from home.content_polisher import content_polisher
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Corregge i link interni negli articoli applicando le nuove logiche'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra cosa verrebbe fatto senza applicare modifiche',
        )
        parser.add_argument(
            '--article-id',
            type=int,
            help='Correggi solo un articolo specifico per ID',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        article_id = options.get('article_id')

        if dry_run:
            self.stdout.write(self.style.WARNING('=== MODALITÀ DRY-RUN - Nessuna modifica verrà salvata ===\n'))

        # Seleziona articoli da processare
        if article_id:
            articoli = Articolo.objects.filter(id=article_id, approvato=True)
            if not articoli.exists():
                self.stdout.write(self.style.ERROR(f'Articolo con ID {article_id} non trovato o non approvato'))
                return
        else:
            articoli = Articolo.objects.filter(approvato=True).order_by('-data_pubblicazione')

        total = articoli.count()
        self.stdout.write(f'Trovati {total} articoli da processare\n')

        updated = 0
        errors = 0

        for i, articolo in enumerate(articoli, 1):
            try:
                self.stdout.write(f'[{i}/{total}] Processando: {articolo.titolo[:60]}...')

                # Salva contenuto originale
                original_content = articolo.contenuto

                # Step 1: Rimuovi tutti i link interni esistenti
                import re
                # Pattern per rimuovere <a> ma mantenere il contenuto interno
                content_no_links = re.sub(
                    r'<a[^>]*class="internal-link"[^>]*>(.*?)</a>',
                    r'\1',
                    original_content,
                    flags=re.DOTALL | re.IGNORECASE
                )

                # Step 2: Rigenera i link con le nuove logiche
                new_content = content_polisher.add_internal_links(
                    content_no_links,
                    article_title=articolo.titolo,
                    current_article_slug=articolo.slug
                )

                # Verifica se ci sono state modifiche
                if new_content != original_content:
                    if not dry_run:
                        articolo.contenuto = new_content
                        articolo.save(update_fields=['contenuto'])

                    updated += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Aggiornato'))
                else:
                    self.stdout.write(self.style.WARNING(f'  - Nessuna modifica necessaria'))

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f'  ✗ Errore: {str(e)}'))
                logger.error(f'Errore processando articolo {articolo.id}: {e}', exc_info=True)

        # Riepilogo
        self.stdout.write('\n' + '='*60)
        if dry_run:
            self.stdout.write(self.style.WARNING('MODALITÀ DRY-RUN - Nessuna modifica salvata'))
        self.stdout.write(self.style.SUCCESS(f'✓ Articoli aggiornati: {updated}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'✗ Errori: {errors}'))
        self.stdout.write(f'Total processati: {total}')
        self.stdout.write('='*60)
