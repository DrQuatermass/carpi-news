"""
Comando per rimuovere link interni a termini generici dagli articoli esistenti

Rimuove i link a: Data, Orari, Organizzazione, Info, Prezzi, Luogo
mantenendo il testo in grassetto (<strong>).
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
import re
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Rimuove link interni a termini generici (Data, Orari, Organizzazione, Info, Prezzi, Luogo) dagli articoli esistenti'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra cosa verrebbe modificato senza applicare le modifiche',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Lista dei termini generici da de-linkare
        generic_terms = ['data', 'orari', 'organizzazione', 'info', 'prezzi', 'luogo']

        if dry_run:
            self.stdout.write(self.style.WARNING('=== MODALITÀ DRY-RUN: Nessuna modifica verrà applicata ==='))

        self.stdout.write(f'Cerco link ai termini generici: {", ".join(generic_terms)}')

        # Recupera tutti gli articoli approvati
        articoli = Articolo.objects.filter(approvato=True)
        total_articles = articoli.count()

        self.stdout.write(f'Scansione di {total_articles} articoli approvati...\n')

        fixed = 0
        total_links_removed = 0

        for articolo in articoli:
            contenuto_originale = articolo.contenuto
            contenuto_pulito = contenuto_originale
            article_links_removed = 0

            # Per ogni termine generico
            for term in generic_terms:
                # Pattern per trovare link interni che contengono questo termine
                # Cerca varianti case-insensitive
                pattern = re.compile(
                    rf'<a\s+href="/articolo/[^"]+/"\s+class="internal-link"[^>]*>\s*<strong>({term})</strong>\s*</a>',
                    re.IGNORECASE
                )

                # Trova tutte le occorrenze
                matches = pattern.findall(contenuto_pulito)

                if matches:
                    # Sostituisci con solo <strong>testo</strong>
                    contenuto_pulito = pattern.sub(r'<strong>\1</strong>', contenuto_pulito)
                    article_links_removed += len(matches)

            # Se ci sono state modifiche
            if contenuto_pulito != contenuto_originale:
                if not dry_run:
                    articolo.contenuto = contenuto_pulito
                    articolo.save(update_fields=['contenuto'])

                fixed += 1
                total_links_removed += article_links_removed

                self.stdout.write(
                    self.style.SUCCESS(
                        f'{"[DRY-RUN] " if dry_run else ""}✓ {articolo.titolo[:60]}... '
                        f'({article_links_removed} link rimossi)'
                    )
                )

        # Riepilogo finale
        self.stdout.write('\n' + '=' * 70)
        if dry_run:
            self.stdout.write(self.style.WARNING('RIEPILOGO DRY-RUN (nessuna modifica applicata):'))
        else:
            self.stdout.write(self.style.SUCCESS('RIEPILOGO:'))

        self.stdout.write(f'Articoli totali scansionati: {total_articles}')
        self.stdout.write(f'Articoli con link generici trovati: {fixed}')
        self.stdout.write(f'Link totali rimossi: {total_links_removed}')

        if fixed == 0:
            self.stdout.write(self.style.SUCCESS('\n✓ Nessun link generico trovato. Tutti gli articoli sono puliti!'))
        elif dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\nEsegui senza --dry-run per applicare le modifiche a {fixed} articoli'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✓ Completato! {fixed} articoli puliti, {total_links_removed} link generici rimossi'
                )
            )
