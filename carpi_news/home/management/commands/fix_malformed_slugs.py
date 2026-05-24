"""
Identifica articoli con slug malformati e propone/applica il rename
con redirect 301 dal vecchio al nuovo.

Uso:
  python manage.py fix_malformed_slugs --dry-run
  python manage.py fix_malformed_slugs --apply
  python manage.py fix_malformed_slugs --apply --limit 50
  python manage.py fix_malformed_slugs --dry-run --views-threshold 100
  python manage.py fix_malformed_slugs --dry-run --include-popular
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from home.models import Articolo, ArticoloRedirect
from home.utils import is_slug_malformed, safe_slugify


def _unique_slug_for_article(article, base_slug):
    new_slug = base_slug
    n = 1
    while (
        Articolo.objects.exclude(pk=article.pk).filter(slug=new_slug).exists()
        or ArticoloRedirect.objects.filter(old_slug=new_slug).exists()
    ):
        n += 1
        suffix = f"-{n}"
        candidate = base_slug[:75 - len(suffix)]
        last_dash = candidate.rfind('-')
        if last_dash > 10:
            candidate = candidate[:last_dash]
        new_slug = candidate + suffix
    return new_slug


class Command(BaseCommand):
    help = 'Identifica articoli con slug malformati e rinomina con redirect 301'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False)
        parser.add_argument('--apply', action='store_true', default=False)
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument(
            '--include-approved-only', action='store_true', default=True,
            help='Limita ad articoli approvati (default True)'
        )
        parser.add_argument(
            '--views-threshold', type=int, default=50,
            help='Skippa articoli con piu di N views. Default 50.'
        )
        parser.add_argument(
            '--include-popular', action='store_true', default=False,
            help='Forza rename anche degli articoli sopra views-threshold.'
        )

    def handle(self, *args, **opts):
        if not opts['dry_run'] and not opts['apply']:
            self.stderr.write('Devi specificare --dry-run o --apply')
            return

        qs = Articolo.objects.all()
        if opts['include_approved_only']:
            qs = qs.filter(approvato=True)
        qs = qs.order_by('-data_pubblicazione')

        total_malformed = 0
        skipped_popular = 0
        skipped_unfixable = 0
        problematici = []

        for art in qs.iterator(chunk_size=200):
            bad, reason = is_slug_malformed(art.slug)
            if not bad:
                continue

            total_malformed += 1

            if (
                not opts['include_popular']
                and (art.views or 0) > opts['views_threshold']
            ):
                skipped_popular += 1
                continue

            source = (art.titolo_seo or '').strip() or art.titolo
            new_slug = safe_slugify(source, max_length=75)
            bad_new, _ = is_slug_malformed(new_slug)
            if bad_new and art.titolo_seo:
                new_slug = safe_slugify(art.titolo, max_length=75)
                bad_new, _ = is_slug_malformed(new_slug)
            if bad_new:
                skipped_unfixable += 1
                continue

            new_slug = _unique_slug_for_article(art, new_slug)
            if new_slug == art.slug:
                skipped_unfixable += 1
                continue

            if opts['limit'] is None or len(problematici) < opts['limit']:
                problematici.append((art, reason, new_slug))

        self.stdout.write(self.style.NOTICE(
            f'\nTotale slug malformati identificati: {total_malformed}'
        ))
        self.stdout.write(self.style.NOTICE(
            f'Candidati al rename selezionati: {len(problematici)}'
        ))
        if skipped_popular:
            self.stdout.write(
                f'Skippati per views > {opts["views_threshold"]}: {skipped_popular}'
            )
        if skipped_unfixable:
            self.stdout.write(f'Skippati per nuovo slug ancora problematico: {skipped_unfixable}')
        self.stdout.write('')

        for art, reason, new_slug in problematici[:30]:
            self.stdout.write(f'  ID {art.pk}: {reason} (views={art.views or 0})')
            self.stdout.write(f'    OLD: {art.slug}')
            self.stdout.write(f'    NEW: {new_slug}\n')

        if len(problematici) > 30:
            self.stdout.write(f'\n... e altri {len(problematici) - 30} articoli.')

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(
                '\nDRY RUN - nessuna modifica applicata.'
            ))
            return

        if opts['apply']:
            with transaction.atomic():
                for art, reason, new_slug in problematici:
                    old_slug = art.slug
                    ArticoloRedirect.objects.get_or_create(
                        old_slug=old_slug,
                        defaults={
                            'new_slug': new_slug,
                            'articolo': art,
                            'motivo': reason,
                        }
                    )
                    art.slug = new_slug
                    art.save(update_fields=['slug'])
            self.stdout.write(self.style.SUCCESS(
                f'\nApplicate {len(problematici)} rinominate.'
            ))
