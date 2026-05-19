"""
Ritenta in batch le pubblicazioni social fallite.

Esempi:
    python manage.py retry_failed_social_shares
    python manage.py retry_failed_social_shares --platform instagram_story --platform instagram_reel
    python manage.py retry_failed_social_shares --older-than-minutes 15 --limit 10 --execute
"""

from collections import OrderedDict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from home.models import Articolo, SocialPublicationLog
from home.social_sharing import social_manager


PLATFORMS = [
    "telegram",
    "facebook",
    "facebook_story",
    "instagram",
    "instagram_story",
    "instagram_reel",
]


class Command(BaseCommand):
    help = "Ritenta tutte le pubblicazioni social fallite o rimaste In progress obsolete."

    def add_arguments(self, parser):
        parser.add_argument(
            "--platform",
            action="append",
            choices=PLATFORMS,
            help="Piattaforma da ritentare. Ripetibile. Default: tutte.",
        )
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=15,
            help="Considera solo fallimenti piu' vecchi di N minuti. Default: 15.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Numero massimo di coppie articolo/piattaforma da ritentare. Default: 20.",
        )
        parser.add_argument(
            "--article-limit",
            type=int,
            default=0,
            help="Numero massimo di articoli distinti da processare. Default: nessun limite oltre --limit.",
        )
        parser.add_argument(
            "--in-progress-only",
            action="store_true",
            help="Ritenta solo log con error_message='In progress...'.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Esegue davvero i retry. Senza questo flag mostra solo il piano.",
        )

    def handle(self, *args, **opts):
        retry_items = self._retry_items(opts)

        if not retry_items:
            self.stdout.write(self.style.SUCCESS("Nessuna pubblicazione fallita da ritentare."))
            return

        if not opts["execute"]:
            self.stdout.write(self.style.WARNING(
                "Dry-run: nessun retry eseguito. Aggiungi --execute per pubblicare davvero."
            ))

        articles = OrderedDict()
        for articolo, platform, log in retry_items:
            articles.setdefault(articolo.id, {"articolo": articolo, "items": []})
            articles[articolo.id]["items"].append((platform, log))

        for group in articles.values():
            articolo = group["articolo"]
            platforms = [platform for platform, _log in group["items"]]
            self.stdout.write("")
            self.stdout.write(f"Articolo {articolo.id}: {articolo.titolo}")
            for platform, log in group["items"]:
                err = (log.error_message or "").replace("\n", " ")[:140]
                self.stdout.write(f"  - {platform}: {err}")

            if not opts["execute"]:
                continue

            self.stdout.write(self.style.NOTICE(
                f"Retry articolo {articolo.id} piattaforme: {', '.join(platforms)}"
            ))
            results = social_manager.retry_failed_platforms_only(
                articolo,
                only_platforms=platforms,
            )
            for platform, ok in results.items():
                style = self.style.SUCCESS if ok else self.style.ERROR
                self.stdout.write(style(f"  {platform}: {'OK' if ok else 'FALLITO'}"))

    def _retry_items(self, opts):
        cutoff = timezone.now() - timedelta(minutes=opts["older_than_minutes"])
        selected_platforms = opts["platform"] or PLATFORMS

        qs = (
            SocialPublicationLog.objects
            .filter(
                success=False,
                platform__in=selected_platforms,
                published_at__lte=cutoff,
                articolo__approvato=True,
            )
            .select_related("articolo")
            .order_by("published_at")
        )
        if opts["in_progress_only"]:
            qs = qs.filter(error_message="In progress...")

        unique = OrderedDict()
        for log in qs:
            key = (log.articolo_id, log.platform)
            if key in unique:
                continue
            if SocialPublicationLog.objects.filter(
                articolo_id=log.articolo_id,
                platform=log.platform,
                success=True,
            ).exists():
                continue
            unique[key] = log
            if len(unique) >= opts["limit"]:
                break

        article_limit = opts["article_limit"]
        article_ids = set()
        items = []
        for (article_id, platform), log in unique.items():
            if article_limit and article_id not in article_ids and len(article_ids) >= article_limit:
                continue
            article_ids.add(article_id)
            items.append((log.articolo, platform, log))

        return items
