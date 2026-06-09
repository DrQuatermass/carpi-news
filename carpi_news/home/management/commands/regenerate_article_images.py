from django.db.models import Q
from django.core.management.base import BaseCommand
from django.utils import timezone

from home.image_variants import (
    ArticleImageVariantError,
    ensure_article_image_variants,
    generate_article_image_variants,
    get_article_source_image_path,
    missing_article_image_variants,
)
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
        parser.add_argument("--slug", help="Processa un solo articolo tramite slug.")
        parser.add_argument(
            "--include-unpublished",
            action="store_true",
            help="Processa anche articoli non pubblicati, bozze, futuri e pubbliredazionali non pagati.",
        )
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
        slug = options["slug"]
        include_unpublished = options["include_unpublished"]
        redirect_map = options["redirect_map"]
        redirect_format = options["redirect_format"]
        processed = 0
        generated = 0
        skipped = 0
        failed = 0
        redirect_lines = []

        queryset = Articolo.objects.order_by("-data_pubblicazione", "-id")
        if slug:
            queryset = queryset.filter(slug=slug)
        if not include_unpublished:
            queryset = queryset.filter(
                Q(is_pubbliredazionale=False, approvato=True)
                | Q(is_pubbliredazionale=True, approvato=True, payment_status="completed"),
                data_pubblicazione__lte=timezone.now(),
            )
        if limit:
            queryset = queryset[:limit]

        if slug and not queryset.exists():
            self.stderr.write(self.style.ERROR(f"Nessun articolo trovato con slug: {slug}"))
            return

        for articolo in queryset:
            processed += 1
            old_image_path = _current_image_path(articolo)
            try:
                if include_unpublished and not articolo.approvato:
                    source = get_article_source_image_path(articolo)
                    created = generate_article_image_variants(articolo, source_path=source, force=True) if source else {}
                else:
                    created = ensure_article_image_variants(articolo, force=force)
            except ArticleImageVariantError as exc:
                failed += 1
                self.stderr.write(self.style.WARNING(f"{articolo.slug}: immagine non processabile, salto. {exc}"))
                continue

            if created:
                generated += 1
                self.stdout.write(f"{articolo.slug}: {', '.join(sorted(created))}")
            else:
                missing = missing_article_image_variants(articolo)
                if missing:
                    failed += 1
                    source = get_article_source_image_path(articolo)
                    source_label = str(source) if source else "<nessuna immagine locale>"
                    self.stderr.write(
                        self.style.WARNING(
                            f"{articolo.slug}: varianti ancora mancanti ({','.join(missing)}), "
                            f"source={source_label}, foto={articolo.foto or ''}, foto_upload={getattr(articolo.foto_upload, 'name', '') or ''}"
                        )
                    )
                    continue
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
                f"Processati: {processed}. Articoli aggiornati: {generated}. Saltati: {skipped}. Falliti: {failed}."
            )
        )
