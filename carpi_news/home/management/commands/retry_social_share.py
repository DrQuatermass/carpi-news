"""
Ripubblica un articolo sulle piattaforme social abilitate (o solo quelle fallite).

Esempi:
    python manage.py retry_social_share --id 2699
    python manage.py retry_social_share --slug processione-dellascensione-a-novi
    python manage.py retry_social_share --id 2699 --failed-only
    python manage.py retry_social_share --id 2699 --platform facebook_story
"""

from django.core.management.base import BaseCommand, CommandError
from contextlib import contextmanager

from home.models import Articolo, SocialPublicationLog
from home.social_sharing import social_manager


class Command(BaseCommand):
    help = "Ripubblica un articolo sui social (tutte le piattaforme o solo quelle fallite)"

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, help="ID articolo")
        parser.add_argument("--slug", type=str, help="Slug articolo")
        parser.add_argument(
            "--search",
            type=str,
            help="Cerca per titolo se lo slug non è noto (es. 'Processione')",
        )
        parser.add_argument(
            "--failed-only",
            action="store_true",
            help="Riprova solo piattaforme senza log di successo",
        )
        parser.add_argument(
            "--platform",
            type=str,
            choices=[
                "telegram", "facebook", "facebook_story", "facebook_reel",
                "instagram", "instagram_story", "instagram_reel",
            ],
            help="Ripubblica solo questa piattaforma (cancella il log precedente)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Cancella tutti i log dell'articolo prima di ripubblicare",
        )

    def handle(self, *args, **opts):
        articolo = self._get_article(opts.get("id"), opts.get("slug"), opts.get("search"))

        if not articolo.approvato:
            raise CommandError(f"L'articolo '{articolo.titolo}' non è approvato.")

        if opts.get("force"):
            deleted, _ = SocialPublicationLog.objects.filter(articolo=articolo).delete()
            self.stdout.write(self.style.WARNING(f"Rimossi {deleted} log esistenti."))

        if opts.get("platform"):
            SocialPublicationLog.objects.filter(
                articolo=articolo, platform=opts["platform"]
            ).delete()
            self.stdout.write(f"Log '{opts['platform']}' resettato.")

        self.stdout.write(self.style.NOTICE(
            f"Ripubblicazione social: {articolo.titolo} (id={articolo.id})"
        ))
        social_manager._log_enabled_platforms()

        if opts.get("platform"):
            with self._force_facebook_reel_if_requested(opts["platform"]):
                results = social_manager.retry_failed_platforms_only(
                    articolo,
                    only_platforms=[opts["platform"]],
                )
        elif opts.get("failed_only"):
            results = social_manager.retry_failed_platforms_only(articolo)
        else:
            results = social_manager.share_article_on_approval(articolo)

        if not results:
            self.stdout.write(self.style.WARNING(
                "Nessuna piattaforma abilitata o nessuna azione eseguita."
            ))
            return

        for platform, ok in results.items():
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"  {platform}: {'OK' if ok else 'FALLITO'}"))

        logs = SocialPublicationLog.objects.filter(articolo=articolo).order_by("platform")
        for log in logs:
            status = "OK" if log.success else "ERR"
            err = f" — {log.error_message[:120]}" if log.error_message and not log.success else ""
            self.stdout.write(f"    [{status}] {log.platform}{err}")

    def _get_article(self, pk, slug, search=None) -> Articolo:
        if pk:
            try:
                return Articolo.objects.get(pk=pk)
            except Articolo.DoesNotExist:
                raise CommandError(f"Articolo id={pk} non trovato")
        if slug:
            try:
                return Articolo.objects.get(slug=slug)
            except Articolo.DoesNotExist:
                raise CommandError(
                    f"Articolo slug='{slug}' non trovato. "
                    "Prova --search 'Processione' per trovare id e slug corretti."
                )
        if search:
            matches = list(
                Articolo.objects.filter(titolo__icontains=search)
                .order_by("-data_pubblicazione", "-data_creazione")[:2]
            )
            if not matches:
                raise CommandError(f"Nessun articolo con titolo contenente '{search}'")
            if len(matches) > 1:
                lines = [f"  id={a.id} slug={a.slug}" for a in matches]
                raise CommandError(
                    f"Trovati più articoli per '{search}':\n" + "\n".join(lines)
                    + "\nSpecifica --id o --slug."
                )
            return matches[0]
        raise CommandError("Specifica --id, --slug o --search")

    @staticmethod
    @contextmanager
    def _force_facebook_reel_if_requested(platform):
        config = social_manager.platforms.get("facebook_reel", {})
        previous = config.get("enabled")
        if platform == "facebook_reel" and config.get("access_token") and config.get("page_id"):
            config["enabled"] = True
        try:
            yield
        finally:
            config["enabled"] = previous
