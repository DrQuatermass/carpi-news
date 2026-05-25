from django.core.management.base import BaseCommand

from home.image_variants import generate_article_image_variants
from home.models import Articolo


def _current_image_path(articolo):
    if articolo.foto_upload:
        try:
            if articolo.foto_upload.name:
                return articolo.foto_upload.url
        except (ValueError, AttributeError):
            pass
    if articolo.foto and str(articolo.foto).startswith("/media/"):
        return articolo.foto
    return ""


def _redirect_line(old_path, new_path, redirect_format):
    if redirect_format == "apache":
        return f"Redirect 301 {old_path} {new_path}"
    return f"location = {old_path} {{ return 301 {new_path}; }}"


class Command(BaseCommand):
    help = "Rigenera le varianti WebP 16:9, 4:3 e 1:1 delle immagini articolo."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Rigenera anche le varianti gia' presenti.")
        parser.add_argument("--limit", type=int, default=None, help="Numero massimo di articoli da processare.")
        parser.add_argument("--redirect-map", help="Path file in cui scrivere redirect 301 dai vecchi URL immagine alla nuova 16:9.")
        parser.add_argument(
            "--redirect-format",
            choices=["nginx", "apache"],
            default="nginx",
            help="Formato mappa redirect: nginx location o Apache .htaccess Redirect 301.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        limit = options["limit"]
        redirect_map = options["redirect_map"]
        redirect_format = options["redirect_format"]
        processed = 0
        generated = 0
        skipped = 0
        redirect_lines = []

        queryset = Articolo.objects.order_by("-data_pubblicazione", "-id")
        if limit:
            queryset = queryset[:limit]

        for articolo in queryset:
            processed += 1
            old_image_path = _current_image_path(articolo)
            created = generate_article_image_variants(articolo, force=force)
            if created:
                generated += 1
                self.stdout.write(f"{articolo.slug}: {', '.join(sorted(created))}")
            else:
                skipped += 1

            if redirect_map and articolo.image_16x9 and old_image_path:
                new_image_path = articolo.image_16x9.url
                if old_image_path != new_image_path:
                    redirect_lines.append(_redirect_line(old_image_path, new_image_path, redirect_format))

        if redirect_map:
            with open(redirect_map, "w", encoding="utf-8") as handle:
                handle.write("\n".join(dict.fromkeys(redirect_lines)))
                if redirect_lines:
                    handle.write("\n")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Mappa redirect {redirect_format} scritta in {redirect_map} ({len(set(redirect_lines))} righe)."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processati: {processed}. Articoli aggiornati: {generated}. Saltati: {skipped}."
            )
        )
