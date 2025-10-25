"""
Comando per rimuovere auto-riferimenti (link a se stesso) dagli articoli
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
import re
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Rimuove link interni che puntano all\'articolo stesso'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula l\'operazione senza salvare (default: salva)'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] Modalità simulazione attiva\n'))

        # Prendi tutti gli articoli approvati
        articoli = Articolo.objects.filter(approvato=True)
        total = articoli.count()

        self.stdout.write(f'=== Rimozione Auto-Riferimenti da {total} articoli ===\n')

        fixed = 0
        errors = 0

        for idx, articolo in enumerate(articoli, 1):
            try:
                contenuto_originale = articolo.contenuto

                # Pattern per trovare link interni che puntano a questo articolo
                # <a href="/articolo/{slug}/" class="internal-link"...>...</a>
                self_link_pattern = re.compile(
                    rf'<a href="/articolo/{re.escape(articolo.slug)}/" class="internal-link"[^>]*><strong>([^<]+)</strong></a>',
                    re.IGNORECASE
                )

                # Cerca auto-riferimenti
                self_links = self_link_pattern.findall(contenuto_originale)

                if self_links:
                    # Sostituisci con solo <strong>testo</strong> (rimuovi il link)
                    contenuto_pulito = self_link_pattern.sub(r'<strong>\1</strong>', contenuto_originale)

                    self.stdout.write(
                        self.style.WARNING(
                            f'[{idx}/{total}] {articolo.titolo[:50]}... -> {len(self_links)} auto-link rimossi'
                        )
                    )

                    # Mostra quali link sono stati rimossi
                    for link_text in self_links:
                        self.stdout.write(f'  - Rimosso: "{link_text}"')

                    if not dry_run:
                        articolo.contenuto = contenuto_pulito
                        articolo.save(update_fields=['contenuto'])

                    fixed += 1
                else:
                    if idx % 50 == 0:  # Progress ogni 50 articoli
                        self.stdout.write(f'[{idx}/{total}] Processati...')

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(f'[{idx}/{total}] ERRORE su "{articolo.titolo[:40]}...": {str(e)}')
                )
                logger.error(f'Errore remove_self_links su {articolo.slug}: {e}', exc_info=True)

        # Summary
        self.stdout.write('\n=== Riepilogo ===')
        self.stdout.write(f'Processati: {total}')
        self.stdout.write(f'Con auto-link: {fixed}')
        self.stdout.write(f'Senza auto-link: {total - fixed}')
        self.stdout.write(f'Errori: {errors}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] Nessuna modifica salvata'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\n[COMPLETATO] {fixed} articoli corretti nel database'))
