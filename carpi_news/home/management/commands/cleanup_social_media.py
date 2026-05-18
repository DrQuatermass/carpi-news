"""
Pulizia periodica dei file media generati dalle pipeline social.

Le pipeline (Reel/Story FB, Reel/Story IG, post IG template) salvano file
temporanei in `media/reels/`, `media/ig_video/`, `media/ig_reel_covers/`,
`media/stories/` (legacy) e `media/images/instagram_temp/`. Dopo l'upload
verso Meta i file non sono piu' utili: Meta li ospita lui sul suo CDN.

Questo comando rimuove i file piu' vecchi di N ore (default 24) da quelle
cartelle. Da schedulare con cron / systemd timer.

Esempi:
    # Dry-run: vedi cosa rimuoverebbe ma non cancella
    python manage.py cleanup_social_media --dry-run

    # Cancella i file piu' vecchi di 24 ore (default)
    python manage.py cleanup_social_media

    # Cancella solo file piu' vecchi di 48 ore
    python manage.py cleanup_social_media --older-than-hours 48

    # Pulisci solo una cartella specifica
    python manage.py cleanup_social_media --only ig_video
"""

import os
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


# Cartelle dove le pipeline social salvano file temporanei generati.
# Tutte sotto MEDIA_ROOT, contengono solo file derivati e ricreabili: e' sicuro
# rimuoverli passato il TTL perche' a quel punto Meta li ha gia' scaricati.
SOCIAL_DIRS = [
    ("ig_video", "media/ig_video"),                       # IG Story + IG Reel (condiviso)
    ("ig_reel_covers", "media/ig_reel_covers"),           # Cover thumbnail Reel IG
    ("reels", "media/reels"),                             # FB Story video
    ("stories", "media/stories"),                         # legacy IG Story (pre-share)
    ("ig_reels", "media/ig_reels"),                       # legacy IG Reel (pre-share)
    ("instagram_temp", "media/images/instagram_temp"),    # template post IG (1080x1080)
]


class Command(BaseCommand):
    help = "Pulisce i file media social piu' vecchi di N ore (default 24)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-hours",
            type=int,
            default=24,
            help="Soglia in ore: rimuove file con mtime piu' vecchio (default 24)",
        )
        parser.add_argument(
            "--only",
            type=str,
            choices=[k for k, _ in SOCIAL_DIRS],
            help="Limita pulizia a una sola cartella (es. 'ig_video', 'instagram_temp')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa cancellerebbe, ma non cancella nulla",
        )

    def handle(self, *args, **opts):
        ttl_s = opts["older_than_hours"] * 3600
        cutoff = time.time() - ttl_s
        dry = opts["dry_run"]
        only = opts.get("only")

        base = Path(settings.BASE_DIR)
        targets = [(k, base / rel) for k, rel in SOCIAL_DIRS]
        if only:
            targets = [(k, p) for k, p in targets if k == only]

        total_removed = 0
        total_freed_kb = 0

        for label, dir_path in targets:
            if not dir_path.exists():
                self.stdout.write(self.style.NOTICE(f"  [skip] {label}: cartella non esiste ({dir_path})"))
                continue

            removed = 0
            freed_kb = 0
            kept = 0
            for entry in dir_path.iterdir():
                if not entry.is_file():
                    continue
                try:
                    mtime = entry.stat().st_mtime
                    size_kb = entry.stat().st_size // 1024
                except OSError:
                    continue

                if mtime < cutoff:
                    if dry:
                        self.stdout.write(f"  [dry] {entry.name} ({size_kb} KB, age={int((time.time()-mtime)/3600)}h)")
                    else:
                        try:
                            entry.unlink()
                            removed += 1
                            freed_kb += size_kb
                        except OSError as e:
                            self.stderr.write(self.style.WARNING(f"  errore rimozione {entry}: {e}"))
                else:
                    kept += 1

            label_msg = f"{label} ({dir_path.name})"
            if dry:
                self.stdout.write(self.style.NOTICE(
                    f"  {label_msg}: {kept} mantenuti, dry-run completato"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"  {label_msg}: rimossi {removed} file ({freed_kb} KB liberati), {kept} mantenuti"
                ))
                total_removed += removed
                total_freed_kb += freed_kb

        if not dry:
            self.stdout.write(self.style.SUCCESS(
                f"\nTotale: {total_removed} file rimossi, {total_freed_kb // 1024} MB liberati"
            ))
