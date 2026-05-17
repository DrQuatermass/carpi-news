"""
Mostra la configurazione social effettiva del processo Django in esecuzione.

Utile sul server per verificare cosa vede Gunicorn (non solo il file .env).

    python manage.py show_social_config
    python manage.py show_social_config --article-id 2699
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from home.models import Articolo, SocialPublicationLog
from home.social_sharing import social_manager


class Command(BaseCommand):
    help = "Mostra piattaforme social abilitate e log di un articolo"

    def add_arguments(self, parser):
        parser.add_argument("--article-id", type=int, help="Mostra log social per questo articolo")
        parser.add_argument("--slug", type=str, help="Slug articolo (alternativa a --article-id)")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.NOTICE("=== Variabili .env (via Django settings) ==="))
        flags = [
            ("FACEBOOK_AUTO_SHARE", getattr(settings, "FACEBOOK_AUTO_SHARE", False)),
            ("FACEBOOK_STORY_ENABLED", getattr(settings, "FACEBOOK_STORY_ENABLED", False)),
            ("FACEBOOK_REEL_ENABLED", getattr(settings, "FACEBOOK_REEL_ENABLED", False)),
            ("INSTAGRAM_AUTO_SHARE", getattr(settings, "INSTAGRAM_AUTO_SHARE", False)),
            ("INSTAGRAM_STORY_ENABLED", getattr(settings, "INSTAGRAM_STORY_ENABLED", False)),
            ("INSTAGRAM_REEL_ENABLED", getattr(settings, "INSTAGRAM_REEL_ENABLED", False)),
        ]
        for name, val in flags:
            style = self.style.SUCCESS if val else self.style.WARNING
            self.stdout.write(style(f"  {name} = {val}"))

        self.stdout.write(self.style.NOTICE("\n=== Piattaforme attive (SocialMediaManager) ==="))
        for key, cfg in social_manager.platforms.items():
            en = cfg.get("enabled", False)
            style = self.style.SUCCESS if en else self.style.WARNING
            self.stdout.write(style(f"  {key}: {'ON' if en else 'OFF'} ({cfg.get('name', key)})"))

        pk = opts.get("article_id")
        slug = opts.get("slug")
        if not pk and slug:
            try:
                pk = Articolo.objects.values_list("pk", flat=True).get(slug=slug)
            except Articolo.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Articolo slug='{slug}' non trovato"))
                return

        if pk:
            try:
                art = Articolo.objects.get(pk=pk)
            except Articolo.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Articolo id={pk} non trovato"))
                return

            self.stdout.write(self.style.NOTICE(f"\n=== Articolo id={pk} ==="))
            self.stdout.write(f"  Titolo: {art.titolo}")
            self.stdout.write(f"  Foto: {art.foto or '(vuota)'}")
            self.stdout.write(f"  Approvato: {art.approvato}")

            from home.facebook_reels import FacebookReelGenerator
            img = FacebookReelGenerator()._resolve_image_path(art)
            if img:
                self.stdout.write(self.style.SUCCESS(f"  Immagine reel: {img}"))
            else:
                self.stdout.write(self.style.ERROR("  Immagine reel: NON RISOLVIBILE"))

            logs = SocialPublicationLog.objects.filter(articolo=art).order_by("platform")
            self.stdout.write(self.style.NOTICE(f"\n=== Log social ({logs.count()}) ==="))
            if not logs:
                self.stdout.write("  (nessun log — story/reel non sono partiti o codice vecchio)")
            for log in logs:
                st = "OK" if log.success else "ERR"
                err = f" | {log.error_message[:100]}" if log.error_message and not log.success else ""
                self.stdout.write(f"  [{st}] {log.platform} @ {log.published_at:%Y-%m-%d %H:%M}{err}")
