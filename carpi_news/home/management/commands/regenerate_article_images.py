from django.core.management.base import BaseCommand

from home.image_variants import generate_article_image_variants
from home.models import Articolo


class Command(BaseCommand):
    help = "Rigenera le varianti WebP 16:9, 4:3 e 1:1 delle immagini articolo."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Rigenera anche le varianti gia' presenti.")
        parser.add_argument("--limit", type=int, default=None, help="Numero massimo di articoli da processare.")

    def handle(self, *args, **options):
        force = options["force"]
        limit = options["limit"]
        processed = 0
        generated = 0
        skipped = 0

        queryset = Articolo.objects.order_by("-data_pubblicazione", "-id")
        if limit:
            queryset = queryset[:limit]

        for articolo in queryset:
            processed += 1
            created = generate_article_image_variants(articolo, force=force)
            if created:
                generated += 1
                self.stdout.write(f"{articolo.slug}: {', '.join(sorted(created))}")
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processati: {processed}. Articoli aggiornati: {generated}. Saltati: {skipped}."
            )
        )
