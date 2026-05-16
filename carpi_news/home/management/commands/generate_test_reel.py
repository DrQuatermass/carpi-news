"""
Genera un Reel Facebook in locale (senza pubblicarlo) per anteprima/QA.

Esempi:
    # Ultimo articolo approvato con foto
    python manage.py generate_test_reel

    # Articolo specifico tramite slug
    python manage.py generate_test_reel --slug la-danza-sorprendente-di-kataklo-in-aliena

    # Articolo specifico tramite id
    python manage.py generate_test_reel --id 1234

Il file viene salvato in MEDIA_ROOT/reels/<slug>.mp4 e il path viene stampato
a console. Nessuna chiamata alle API Facebook viene fatta.
"""

from django.core.management.base import BaseCommand, CommandError

from home.facebook_reels import FacebookReelGenerator, ReelConfig
from home.models import Articolo


class Command(BaseCommand):
    help = "Genera un Reel Facebook in locale partendo da un articolo (senza pubblicare)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            type=str,
            help="Slug dell'articolo da usare (default: ultimo approvato con foto)",
        )
        parser.add_argument(
            "--id",
            type=int,
            help="ID dell'articolo da usare (alternativa a --slug)",
        )
        parser.add_argument(
            "--duration",
            type=int,
            default=None,
            help="Durata in secondi (default da FACEBOOK_REEL_DURATION o 15)",
        )

    def handle(self, *args, **opts):
        articolo = self._pick_article(opts.get("slug"), opts.get("id"))

        if not articolo.foto:
            raise CommandError(
                f"L'articolo '{articolo.titolo}' non ha foto: Reel non generabile."
            )

        cfg = ReelConfig.from_settings()
        if opts.get("duration"):
            cfg.duration_seconds = opts["duration"]

        generator = FacebookReelGenerator(config=cfg)
        self.stdout.write(self.style.NOTICE(
            f"Genero Reel ({cfg.duration_seconds}s, {cfg.fps}fps) per: {articolo.titolo}"
        ))

        path = generator.generate(articolo)
        if not path:
            raise CommandError("Generazione fallita - controlla i log per dettagli.")

        self.stdout.write(self.style.SUCCESS(f"OK -> {path}"))

    def _pick_article(self, slug, pk) -> Articolo:
        if pk:
            try:
                return Articolo.objects.get(pk=pk)
            except Articolo.DoesNotExist:
                raise CommandError(f"Articolo con id={pk} non trovato")

        if slug:
            try:
                return Articolo.objects.get(slug=slug)
            except Articolo.DoesNotExist:
                raise CommandError(f"Articolo con slug='{slug}' non trovato")

        # Default: ultimo articolo approvato con foto
        articolo = (
            Articolo.objects
            .filter(approvato=True)
            .exclude(foto__isnull=True)
            .exclude(foto__exact="")
            .order_by("-data_pubblicazione", "-data_creazione")
            .first()
        )
        if not articolo:
            raise CommandError(
                "Nessun articolo approvato con foto trovato. "
                "Specifica --slug o --id."
            )
        return articolo
