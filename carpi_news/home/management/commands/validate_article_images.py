import time
from collections import defaultdict
from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from django.db.models import Q

from home.image_validation import validate_articolo_images
from home.image_variants import ArticleImageVariantError, ensure_article_image_variants, has_all_article_image_variants
from home.models import Articolo


class Command(BaseCommand):
    help = "Valida immagini articolo e genera varianti mancanti per articoli approvati."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Mostra il report senza salvare modifiche.")
        parser.add_argument("--only-broken", action="store_true", help="Riconvalida solo articoli con foto_valida=False.")
        parser.add_argument("--limit", type=int, default=None, help="Numero massimo di articoli da processare.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        only_broken = options["only_broken"]
        limit = options["limit"]

        queryset = Articolo.objects.filter(Q(foto__isnull=False) | Q(foto_upload__isnull=False)).exclude(
            foto="", foto_upload=""
        ).order_by("id")
        if only_broken:
            queryset = queryset.filter(foto_valida=False)
        if limit:
            queryset = queryset[:limit]

        checked = 0
        broken = 0
        corrected = 0
        variants_generated = 0
        variants_failed = 0
        last_request_by_domain = defaultdict(float)

        for articolo in queryset:
            checked += 1
            before = {
                "foto": articolo.foto or "",
                "foto_upload": getattr(articolo.foto_upload, "name", "") or "",
                "foto_valida": articolo.foto_valida,
            }

            domain = urlparse(str(articolo.foto or "")).netloc.lower()
            if domain:
                elapsed = time.monotonic() - last_request_by_domain[domain]
                if elapsed < 0.5:
                    time.sleep(0.5 - elapsed)
                last_request_by_domain[domain] = time.monotonic()

            is_valid = validate_articolo_images(articolo, save=not dry_run)
            after = {
                "foto": articolo.foto or "",
                "foto_upload": getattr(articolo.foto_upload, "name", "") or "",
                "foto_valida": articolo.foto_valida,
            }
            if not is_valid:
                broken += 1
            if before != after:
                corrected += 1
                self.stdout.write(f"{articolo.slug}: corretto {before} -> {after}")

            if articolo.approvato:
                try:
                    if dry_run:
                        if not has_all_article_image_variants(articolo):
                            variants_generated += 1
                    else:
                        created = ensure_article_image_variants(articolo)
                        if created:
                            variants_generated += 1
                            self.stdout.write(f"{articolo.slug}: varianti generate {', '.join(sorted(created))}")
                except ArticleImageVariantError as exc:
                    variants_failed += 1
                    self.stderr.write(self.style.WARNING(f"{articolo.slug}: varianti non processabili: {exc}"))

        mode = "DRY RUN - " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}Validati: {checked}. Rotti: {broken}. Corretti: {corrected}. "
                f"Varianti generate/mancanti: {variants_generated}. Varianti fallite: {variants_failed}."
            )
        )
