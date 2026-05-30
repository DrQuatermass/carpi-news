from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

from home.models import Articolo


REFERENCE_FIELDS = ("foto", "foto_upload", "image_16x9", "image_4x3", "image_1x1")


class Command(BaseCommand):
    help = "Pulisce file in media/images/articles non referenziati da nessun articolo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-hours",
            type=int,
            default=24,
            help="Cancella solo file con mtime piu' vecchio della soglia (default 24).",
        )
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
        execute = options["execute"] and not options["dry_run"]
        media_root = Path(settings.MEDIA_ROOT).resolve()
        variants_dir = media_root / "images" / "articles"

        if not variants_dir.exists():
            self.stdout.write(self.style.WARNING(f"Cartella non trovata: {variants_dir}"))
            return

        referenced = self._referenced_media_paths()
        cutoff_ts = self._cutoff_timestamp(options["older_than_hours"])

        scanned = 0
        protected = 0
        too_recent = 0
        deletable = []

        for path in variants_dir.iterdir():
            if not path.is_file():
                continue
            scanned += 1
            rel_path = path.relative_to(media_root).as_posix()

            if rel_path in referenced:
                protected += 1
                continue
            if path.stat().st_mtime >= cutoff_ts:
                too_recent += 1
                continue
            deletable.append(path)

        total_bytes = sum(path.stat().st_size for path in deletable)

        self.stdout.write(f"File scansionati: {scanned}")
        self.stdout.write(f"File referenziati/protetti: {protected}")
        self.stdout.write(f"File troppo recenti: {too_recent}")
        self.stdout.write(f"File orfani cancellabili: {len(deletable)} ({total_bytes // 1024 // 1024} MB)")

        for path in deletable[:50]:
            rel_path = path.relative_to(media_root).as_posix()
            self.stdout.write(
                f"{'[delete]' if execute else '[dry]'} {rel_path} ({path.stat().st_size // 1024} KB)"
            )

        if len(deletable) > 50:
            self.stdout.write(f"... altri {len(deletable) - 50} file")

        if not execute:
            self.stdout.write(self.style.WARNING("Dry-run: nessun file cancellato. Usa --execute per applicare."))
            return

        removed = 0
        removed_bytes = 0
        for path in deletable:
            try:
                size = path.stat().st_size
                path.unlink()
                removed += 1
                removed_bytes += size
            except OSError as exc:
                self.stderr.write(self.style.WARNING(f"Errore cancellazione {path}: {exc}"))

        self.stdout.write(self.style.SUCCESS(
            f"Completato: rimossi {removed} file, liberati {removed_bytes // 1024 // 1024} MB."
        ))

    def _referenced_media_paths(self):
        referenced = set()
        media_url = settings.MEDIA_URL or "/media/"

        for article in Articolo.objects.all().only(*REFERENCE_FIELDS):
            for field in REFERENCE_FIELDS:
                value = getattr(article, field, None)
                raw = getattr(value, "name", None) or str(value or "")
                raw = raw.strip()
                if not raw:
                    continue

                parsed = urlparse(raw)
                path = parsed.path if parsed.scheme in ("http", "https") else raw

                if path.startswith(media_url):
                    referenced.add(path[len(media_url):].lstrip("/"))
                elif not path.startswith("/"):
                    referenced.add(path)

        return referenced

    @staticmethod
    def _cutoff_timestamp(older_than_hours):
        import time

        return time.time() - (older_than_hours * 3600)
