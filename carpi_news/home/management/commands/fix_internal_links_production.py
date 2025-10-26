"""
Management command per correggere i link interni negli articoli in produzione
Versione ottimizzata per server con progressi visibili e gestione errori robusta
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
from home.content_polisher import content_polisher
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Corregge i link interni negli articoli applicando le nuove logiche (ottimizzato per produzione)'

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
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Numero di articoli da processare per batch (default: 50)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limita il numero totale di articoli da processare',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        article_id = options.get('article_id')
        batch_size = options['batch_size']
        limit = options.get('limit')

        start_time = datetime.now()

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
            if limit:
                articoli = articoli[:limit]

        total = articoli.count()
        self.stdout.write(f'\n🔍 Trovati {total} articoli da processare')
        self.stdout.write(f'📦 Batch size: {batch_size}')
        if limit:
            self.stdout.write(f'⚠️  Limite articoli: {limit}')
        self.stdout.write('')

        updated = 0
        errors = 0
        skipped = 0
        total_links = 0
        processed = 0

        # Processa in batch per evitare sovraccarico memoria
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = articoli[batch_start:batch_end]

            self.stdout.write(f'\n📋 Batch {batch_start//batch_size + 1}: articoli {batch_start + 1}-{batch_end}/{total}')
            self.stdout.write('─' * 80)

            for i, articolo in enumerate(batch, 1):
                processed += 1
                global_index = batch_start + i

                try:
                    # Progress indicator più compatto
                    progress = f'[{global_index}/{total}]'
                    title_preview = articolo.titolo[:50] + ('...' if len(articolo.titolo) > 50 else '')

                    self.stdout.write(f'{progress} {title_preview}', ending='')
                    self.stdout.flush()

                    # Salva contenuto originale
                    original_content = articolo.contenuto

                    # Step 1: Rimuovi tutti i link interni esistenti
                    content_no_links = re.sub(
                        r'<a[^>]*class="internal-link"[^>]*>(.*?)</a>',
                        r'\1',
                        original_content,
                        flags=re.DOTALL | re.IGNORECASE
                    )

                    # Step 2: Rigenera i link con le nuove logiche (catena a ritroso)
                    new_content = content_polisher.add_internal_links(
                        content_no_links,
                        article_title=articolo.titolo,
                        current_article_slug=articolo.slug,
                        current_article_date=articolo.data_pubblicazione
                    )

                    # Conta i link aggiunti
                    links_in_article = len(re.findall(r'class="internal-link"', new_content))
                    total_links += links_in_article

                    # Verifica se ci sono state modifiche
                    if new_content != original_content:
                        if not dry_run:
                            articolo.contenuto = new_content
                            articolo.save(update_fields=['contenuto'])

                        updated += 1
                        self.stdout.write(self.style.SUCCESS(f' ✓ ({links_in_article} link)'))
                    else:
                        skipped += 1
                        self.stdout.write(self.style.WARNING(' ○ (skip)'))

                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f' ✗ ERRORE: {str(e)[:50]}'))
                    logger.error(f'Errore processando articolo {articolo.id}: {e}', exc_info=True)

            # Riepilogo batch
            self.stdout.write(f'  Batch completato: {updated} aggiornati, {skipped} saltati, {errors} errori')

        # Calcola tempo impiegato
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        avg_time = duration / processed if processed > 0 else 0

        # Riepilogo finale
        self.stdout.write('\n' + '=' * 80)
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  MODALITÀ DRY-RUN - Nessuna modifica salvata'))
        self.stdout.write('\n📊 RIEPILOGO FINALE:')
        self.stdout.write('─' * 80)
        self.stdout.write(self.style.SUCCESS(f'✓ Articoli aggiornati:  {updated}'))
        self.stdout.write(self.style.WARNING(f'○ Articoli saltati:     {skipped}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'✗ Errori:               {errors}'))
        self.stdout.write(f'📝 Totale processati:   {processed}')
        self.stdout.write(self.style.SUCCESS(f'🔗 Totale link creati:  {total_links}'))
        self.stdout.write(f'⏱️  Tempo impiegato:     {duration:.2f}s')
        self.stdout.write(f'⚡ Tempo medio/articolo: {avg_time:.3f}s')
        self.stdout.write('=' * 80 + '\n')
