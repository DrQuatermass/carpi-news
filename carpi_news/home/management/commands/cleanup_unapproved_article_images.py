from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from home.models import Articolo


IMAGE_FIELDS = ("foto", "foto_upload", "image_16x9", "image_4x3", "image_1x1")


class Command(BaseCommand):
    help = "Pulisce immagini locali legate solo ad articoli non approvati vecchi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=60,
            help="Soglia in giorni basata su data_creazione (default 60).",
        )
        parser.add_argument(
            "--include-pubbliredazionali",
            action="store_true",
            help="Include anche pubbliredazionali non approvati. Default: esclusi.",
        )
        parser.add_argument("--limit", type=int, help="Limita il numero di articoli candidati.")
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Cancella davvero i file. Senza questo flag esegue solo dry-run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa cancellerebbe senza cancellare nulla. Default se manca --execute.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(days=options["older_than_days"])
        execute = options["execute"] and not options["dry_run"]
        media_root = Path(settings.MEDIA_ROOT).resolve()

        candidates = Articolo.objects.filter(
            approvato=False,
            data_creazione__lt=cutoff,
        ).order_by("id")

        if not options["include_pubbliredazionali"]:
            candidates = candidates.filter(is_pubbliredazionale=False)

        if options["limit"]:
            candidates = candidates[: options["limit"]]

        candidate_articles = list(candidates)
        candidate_ids = {article.id for article in candidate_articles}

        files = {}
        skipped_missing = 0
        skipped_non_media = 0

        for article in candidate_articles:
            for field in IMAGE_FIELDS:
                rel_path = self._field_media_relative_path(article, field)
                if not rel_path:
                    skipped_non_media += 1
                    continue

                file_path = (media_root / rel_path).resolve()
                if not self._is_inside(file_path, media_root):
                    skipped_non_media += 1
                    continue

                if not file_path.exists() or not file_path.is_file():
                    skipped_missing += 1
                    continue

                files.setdefault(rel_path, {"path": file_path, "articles": set(), "fields": set()})
                files[rel_path]["articles"].add(article.id)
                files[rel_path]["fields"].add(field)

        protected = {}
        deletable = {}
        for rel_path, info in files.items():
            refs = self._referencing_article_ids(rel_path)
            outside_refs = refs - candidate_ids
            if outside_refs:
                protected[rel_path] = outside_refs
            else:
                deletable[rel_path] = info

        total_bytes = sum(info["path"].stat().st_size for info in deletable.values())

        self.stdout.write(f"Articoli candidati: {len(candidate_articles)}")
        self.stdout.write(f"File locali trovati: {len(files)}")
        self.stdout.write(f"File protetti perche' referenziati altrove: {len(protected)}")
        self.stdout.write(f"File gia' mancanti: {skipped_missing}")
        self.stdout.write(f"Riferimenti non locali/media saltati: {skipped_non_media}")
        self.stdout.write(f"File cancellabili: {len(deletable)} ({total_bytes // 1024 // 1024} MB)")

        for rel_path, info in list(deletable.items())[:50]:
            self.stdout.write(
                f"{'[delete]' if execute else '[dry]'} {rel_path} "
                f"({info['path'].stat().st_size // 1024} KB, articoli={len(info['articles'])})"
            )

        if len(deletable) > 50:
            self.stdout.write(f"... altri {len(deletable) - 50} file")

        if not execute:
            self.stdout.write(self.style.WARNING("Dry-run: nessun file cancellato. Usa --execute per applicare."))
            return

        removed = 0
        removed_bytes = 0
        for rel_path, info in deletable.items():
            try:
                size = info["path"].stat().st_size
                info["path"].unlink()
                removed += 1
                removed_bytes += size
                self._clear_candidate_references(rel_path, candidate_articles)
            except OSError as exc:
                self.stderr.write(self.style.WARNING(f"Errore cancellazione {rel_path}: {exc}"))

        self.stdout.write(self.style.SUCCESS(
            f"Completato: rimossi {removed} file, liberati {removed_bytes // 1024 // 1024} MB."
        ))

    def _field_media_relative_path(self, article, field):
        value = getattr(article, field, None)
        if not value:
            return None

        raw = getattr(value, "name", None) or str(value)
        raw = raw.strip()
        if not raw:
            return None

        media_url = settings.MEDIA_URL or "/media/"
        parsed = urlparse(raw)
        path = parsed.path if parsed.scheme in ("http", "https") else raw

        if path.startswith(media_url):
            return path[len(media_url):].lstrip("/")
        if path.startswith("/"):
            return None
        return path

    def _referencing_article_ids(self, rel_path):
        media_url = (settings.MEDIA_URL or "/media/").rstrip("/") + "/" + rel_path
        query = (
            Q(foto=rel_path)
            | Q(foto=media_url)
            | Q(foto__endswith=media_url)
            | Q(foto_upload=rel_path)
            | Q(image_16x9=rel_path)
            | Q(image_4x3=rel_path)
            | Q(image_1x1=rel_path)
        )
        return set(Articolo.objects.filter(query).values_list("id", flat=True))

    def _clear_candidate_references(self, rel_path, candidate_articles):
        media_url = (settings.MEDIA_URL or "/media/").rstrip("/") + "/" + rel_path
        for article in candidate_articles:
            changed = []
            if article.foto in (rel_path, media_url) or (article.foto or "").endswith(media_url):
                article.foto = ""
                changed.append("foto")
            for field in ("foto_upload", "image_16x9", "image_4x3", "image_1x1"):
                field_file = getattr(article, field)
                if getattr(field_file, "name", "") == rel_path:
                    setattr(article, field, "")
                    changed.append(field)
            if changed:
                article.save(update_fields=changed)

    @staticmethod
    def _is_inside(path, parent):
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
