"""
Comando per applicare internal links a tutti gli articoli esistenti
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
from home.content_polisher import ContentPolisher
import logging
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Applica internal links a tutti gli articoli approvati (dal più recente al più vecchio)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            help='Numero massimo di articoli da processare (default: tutti)'
        )
        parser.add_argument(
            '--skip',
            type=int,
            default=0,
            help='Salta i primi N articoli (default: 0)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula l\'operazione senza salvare (default: salva)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=2.0,
            help='Delay in secondi tra un articolo e l\'altro (default: 2.0)'
        )

    def handle(self, *args, **options):
        limit = options.get('limit')
        skip = options.get('skip', 0)
        dry_run = options.get('dry_run', False)
        delay = options.get('delay', 2.0)

        # Query articoli approvati dal più recente al più vecchio
        # In questo modo gli articoli recenti linkano a quelli precedenti creando una catena cronologica
        articoli = Articolo.objects.filter(approvato=True).order_by('-data_pubblicazione')

        if skip > 0:
            articoli = articoli[skip:]

        if limit:
            articoli = articoli[:limit]

        total = articoli.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f'\n[DRY RUN] Modalità simulazione attiva\n'))

        self.stdout.write(f'=== Applicazione Internal Links a {total} articoli ===')
        self.stdout.write(f'Delay tra richieste: {delay}s\n')

        polisher = ContentPolisher()
        processed = 0
        with_links = 0
        errors = 0

        for idx, articolo in enumerate(articoli, 1):
            try:
                contenuto_originale = articolo.contenuto

                # Applica internal links (escludendo l'articolo corrente)
                contenuto_con_link = polisher.add_internal_links(
                    articolo.contenuto,
                    article_title=articolo.titolo,
                    current_article_slug=articolo.slug
                )

                # Conta i link aggiunti
                import re
                links_trovati = re.findall(
                    r'<a href="/articolo/([^"]+)/" class="internal-link"',
                    contenuto_con_link
                )

                # Progress
                status = f'[{idx}/{total}] {articolo.titolo[:50]}...'

                if links_trovati:
                    with_links += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'{status} -> {len(links_trovati)} link')
                    )

                    if not dry_run and contenuto_con_link != contenuto_originale:
                        articolo.contenuto = contenuto_con_link
                        articolo.save(update_fields=['contenuto'])
                else:
                    self.stdout.write(f'{status} -> nessun link')

                processed += 1

                # Delay per evitare rate limiting
                if idx < total:
                    time.sleep(delay)

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(f'[{idx}/{total}] ERRORE su "{articolo.titolo[:40]}...": {str(e)}')
                )
                logger.error(f'Errore apply_internal_links_bulk su {articolo.slug}: {e}', exc_info=True)

        # Summary
        self.stdout.write('\n=== Riepilogo ===')
        self.stdout.write(f'Processati: {processed}/{total}')
        self.stdout.write(f'Con link: {with_links}')
        self.stdout.write(f'Senza link: {processed - with_links}')
        self.stdout.write(f'Errori: {errors}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] Nessuna modifica salvata'))
        else:
            self.stdout.write(self.style.SUCCESS('\n[COMPLETATO] Modifiche salvate nel database'))
