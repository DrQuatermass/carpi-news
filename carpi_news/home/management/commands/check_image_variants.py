from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from home.image_variants import get_article_source_image_path, missing_article_image_variants
from home.models import Articolo


class Command(BaseCommand):
    help = "Audita articoli con varianti immagine NewsArticle mancanti o non presenti su disco."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Numero massimo di articoli da controllare.")
        parser.add_argument("--slug", help="Controlla un solo articolo tramite slug.")
        parser.add_argument(
            "--include-unpublished",
            action="store_true",
            help="Include bozze, futuri e pubbliredazionali non pagati.",
        )

    def handle(self, *args, **options):
        queryset = Articolo.objects.order_by("-data_pubblicazione", "-id")
        if options["slug"]:
            queryset = queryset.filter(slug=options["slug"])
        if not options["include_unpublished"]:
            queryset = queryset.filter(
                Q(is_pubbliredazionale=False, approvato=True)
                | Q(is_pubbliredazionale=True, approvato=True, payment_status="completed"),
                data_pubblicazione__lte=timezone.now(),
            )
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        checked = 0
        broken = 0
        for articolo in queryset:
            checked += 1
            missing = missing_article_image_variants(articolo)
            image_count = 3 - len(missing)
            if missing:
                broken += 1
                source = get_article_source_image_path(articolo)
                source_label = str(source) if source else "<nessuna immagine locale>"
                self.stdout.write(
                    f"{articolo.slug} | NewsArticle.image={image_count}/3 | "
                    f"missing={','.join(missing)} | source={source_label}"
                )

        self.stdout.write(
            self.style.SUCCESS(f"Controllati: {checked}. Articoli con varianti mancanti: {broken}.")
        )
