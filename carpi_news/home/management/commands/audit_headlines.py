from django.core.management.base import BaseCommand

from home.models import Articolo


class Command(BaseCommand):
    help = "Stampa gli articoli con headline editoriale oltre 95 caratteri."

    def handle(self, *args, **options):
        limit = Articolo.HEADLINE_MAX_LENGTH
        count = 0

        for articolo in Articolo.objects.only('slug', 'titolo').order_by('slug'):
            headline = articolo.editorial_headline
            length = len(headline)
            if length <= limit:
                continue

            count += 1
            self.stdout.write(f"{articolo.slug}\t{length}\t{headline}")

        if count == 0:
            self.stdout.write(self.style.SUCCESS(f"Nessuna headline oltre {limit} caratteri."))
        else:
            self.stdout.write(self.style.WARNING(f"Totale headline oltre {limit} caratteri: {count}"))
