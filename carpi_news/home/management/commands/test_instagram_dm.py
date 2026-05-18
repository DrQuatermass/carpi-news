from django.core.management.base import BaseCommand, CommandError

from home.models import InstagramAutoDMLog, SocialPublicationLog
from home.share_links import build_short_share_url, get_or_create_short_link
from home.views_webhooks import _send_dm


class Command(BaseCommand):
    help = "Testa il DM automatico Instagram per un media_id Story/Reel gia' pubblicato."

    def add_arguments(self, parser):
        parser.add_argument("--article-id", type=int, help="ID articolo da usare per trovare l'ultimo media IG")
        parser.add_argument("--media-id", type=str, help="Instagram media_id specifico")
        parser.add_argument("--sender-id", type=str, help="IG sender id ricevuto dal webhook")
        parser.add_argument("--trigger", type=str, default="reaction", help="Valore trigger da loggare")
        parser.add_argument(
            "--send",
            action="store_true",
            help="Invia davvero il DM. Senza questo flag stampa solo anteprima messaggio/link.",
        )

    def handle(self, *args, **options):
        log = self._find_log(options.get("article_id"), options.get("media_id"))
        articolo = log.articolo
        short_link = get_or_create_short_link(articolo, "instagram", "instagram_dm")
        short_url = build_short_share_url(articolo, "instagram", "instagram_dm")
        message = (
            "Ciao! 👋 Ecco l'articolo che ti interessava:\n\n"
            f"{articolo.titolo}\n{short_url}\n\n"
            "Grazie per seguirci su Ombra del Portico! 🙏"
        )

        self.stdout.write(self.style.NOTICE("Anteprima DM Instagram"))
        self.stdout.write(f"Articolo: {articolo.id} - {articolo.titolo}")
        self.stdout.write(f"Media ID: {log.instagram_media_id}")
        self.stdout.write(f"ShortLink: {short_link.token} -> {short_url}")
        self.stdout.write("")
        self.stdout.write(message)

        if not options["send"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry-run: nessun DM inviato. Usa --send --sender-id <id> per inviare."))
            return

        sender_id = options.get("sender_id")
        if not sender_id:
            raise CommandError("--sender-id e' obbligatorio con --send")

        sent, info = _send_dm(sender_id, articolo, short_url)
        InstagramAutoDMLog.objects.create(
            articolo=articolo,
            ig_user_id=sender_id,
            trigger_type="story_reaction",
            trigger_value=options["trigger"][:255],
            media_id=log.instagram_media_id,
            short_link=short_link,
            dm_sent=sent,
            dm_error="" if sent else info,
        )
        if sent:
            self.stdout.write(self.style.SUCCESS(f"DM inviato a {sender_id}"))
        else:
            raise CommandError(f"DM fallito: {info}")

    def _find_log(self, article_id, media_id):
        qs = SocialPublicationLog.objects.filter(
            platform__in=["instagram_story", "instagram_reel"],
            success=True,
        ).exclude(instagram_media_id="")
        if media_id:
            qs = qs.filter(instagram_media_id=media_id)
        elif article_id:
            qs = qs.filter(articolo_id=article_id)
        else:
            raise CommandError("Specifica --article-id oppure --media-id")

        log = qs.select_related("articolo").order_by("-published_at").first()
        if not log:
            raise CommandError("Nessun SocialPublicationLog IG valido trovato con media_id valorizzato.")
        return log
