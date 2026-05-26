from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from home.models import Articolo


class Command(BaseCommand):
    help = "Stampa un campione di articoli con contentLocation rilevato."

    def add_arguments(self, parser):
        parser.add_argument("--sample", type=int, default=20, help="Numero di articoli casuali da mostrare.")

    def handle(self, *args, **options):
        sample = options["sample"]
        publishable_filter = (
            Q(is_pubbliredazionale=False, approvato=True)
            | Q(is_pubbliredazionale=True, approvato=True, payment_status="completed")
        )
        queryset = (
            Articolo.objects.filter(publishable_filter, data_pubblicazione__lte=timezone.now())
            .order_by("?")[:sample]
        )

        for articolo in queryset:
            location = articolo.seo_location
            locality = location.get("addressLocality", location["name"])
            if locality == location["name"]:
                location_label = location["name"]
            else:
                location_label = f"{location['name']} ({locality})"
            self.stdout.write(f"{articolo.slug} | {articolo.titolo} | {location_label}")
