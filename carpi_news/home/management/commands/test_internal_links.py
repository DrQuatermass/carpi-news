"""
Comando per testare il sistema di internal linking su un articolo esistente
"""
from django.core.management.base import BaseCommand
from home.models import Articolo
from home.content_polisher import ContentPolisher
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Testa il sistema di internal linking su un articolo'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug',
            type=str,
            required=True,
            help='Slug dell\'articolo da testare'
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Applica le modifiche al database (default: solo preview)'
        )

    def handle(self, *args, **options):
        slug = options['slug']
        apply_changes = options.get('apply', False)

        try:
            articolo = Articolo.objects.get(slug=slug, approvato=True)
        except Articolo.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Articolo con slug "{slug}" non trovato o non approvato'))
            return

        self.stdout.write(f'\n=== Testing Internal Links ===')
        self.stdout.write(f'Articolo: {articolo.titolo}')
        self.stdout.write(f'Slug: {articolo.slug}')
        self.stdout.write(f'Lunghezza contenuto originale: {len(articolo.contenuto)} caratteri\n')

        # Salva contenuto originale
        contenuto_originale = articolo.contenuto

        # Applica internal links
        polisher = ContentPolisher()
        self.stdout.write('Elaborazione in corso...')

        try:
            contenuto_con_link = polisher.add_internal_links(
                articolo.contenuto,
                article_title=articolo.titolo,
                current_article_slug=articolo.slug
            )

            # Conta i link aggiunti
            import re
            links_trovati = re.findall(r'<a href="/articolo/([^"]+)/" class="internal-link"[^>]*>([^<]+)</a>', contenuto_con_link)

            if links_trovati:
                self.stdout.write(self.style.SUCCESS(f'\n[OK] Trovati {len(links_trovati)} link interni:\n'))
                for idx, (target_slug, anchor_text) in enumerate(links_trovati, 1):
                    self.stdout.write(f'  {idx}. "{anchor_text}" -> /articolo/{target_slug}/')

                # Mostra diff lunghezza
                diff = len(contenuto_con_link) - len(contenuto_originale)
                self.stdout.write(f'\nDifferenza lunghezza: +{diff} caratteri')

                if apply_changes:
                    # Salva nel database
                    articolo.contenuto = contenuto_con_link
                    articolo.save(update_fields=['contenuto'])
                    self.stdout.write(self.style.SUCCESS('\n[SAVED] Modifiche salvate nel database!'))
                else:
                    self.stdout.write(self.style.WARNING('\n[PREVIEW] Modifiche NON salvate (usa --apply per salvare)'))

            else:
                self.stdout.write(self.style.WARNING('[WARN] Nessun link interno trovato per questo articolo'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'[ERROR] Errore durante elaborazione: {str(e)}'))
            logger.error(f'Errore test internal links: {e}', exc_info=True)
