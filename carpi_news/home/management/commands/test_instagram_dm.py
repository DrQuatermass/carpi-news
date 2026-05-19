import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from home.models import InstagramAutoDMLog, SocialPublicationLog
from home.share_links import build_short_share_url, get_or_create_short_link
from home.views_webhooks import _extract_events, _handle_event, _send_dm


class Command(BaseCommand):
    help = "Testa il DM automatico Instagram per un media_id Story/Reel gia' pubblicato."

    def add_arguments(self, parser):
        parser.add_argument("--article-id", type=int, help="ID articolo da usare per trovare l'ultimo media IG")
        parser.add_argument("--media-id", type=str, help="Instagram media_id specifico")
        parser.add_argument("--sender-id", type=str, help="IG sender id ricevuto dal webhook")
        parser.add_argument("--trigger", type=str, default="reaction", help="Valore trigger da loggare")
        parser.add_argument(
            "--fixture",
            type=str,
            help="Nome file fixture in home/tests/fixtures/ig_webhook/ oppure path JSON completo.",
        )
        parser.add_argument(
            "--handle-fixture",
            action="store_true",
            help="Esegue _handle_event sugli eventi estratti dalla fixture. Senza --send mocka l'invio DM.",
        )
        parser.add_argument(
            "--send",
            action="store_true",
            help="Invia davvero il DM. Senza questo flag stampa solo anteprima messaggio/link.",
        )

    def handle(self, *args, **options):
        if options.get("fixture"):
            self._handle_fixture(options)
            return

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

    def _handle_fixture(self, options):
        path = self._fixture_path(options["fixture"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        events = list(_extract_events(payload))
        self.stdout.write(self.style.NOTICE(f"Fixture: {path}"))
        self.stdout.write(f"Eventi estratti: {len(events)}")
        for event in events:
            self.stdout.write(
                f"  sender={event[0]} media={event[1]} type={event[2]} value={event[3]} trigger={event[4]}"
            )

        if not options["handle_fixture"]:
            self.stdout.write(self.style.WARNING("Dry-run: parsing soltanto. Usa --handle-fixture per gestire gli eventi."))
            return

        if options["send"]:
            for event in events:
                _handle_event(*event)
            return

        with patch("home.views_webhooks._send_dm", return_value=(True, "mock")):
            for event in events:
                _handle_event(*event)
        self.stdout.write(self.style.SUCCESS("Fixture gestita con invio DM mockato."))

    def _fixture_path(self, value: str) -> Path:
        candidate = Path(value)
        if candidate.exists():
            return candidate
        fixture_dir = Path(settings.BASE_DIR) / "home" / "tests" / "fixtures" / "ig_webhook"
        candidate = fixture_dir / value
        if candidate.exists():
            return candidate
        if not value.endswith(".json"):
            candidate = fixture_dir / f"{value}.json"
            if candidate.exists():
                return candidate
        raise CommandError(f"Fixture non trovata: {value}")
