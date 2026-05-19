import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Controlla le subscription webhook della Pagina Facebook collegata a Instagram."

    def add_arguments(self, parser):
        parser.add_argument("--page-id", default="", help="Page ID. Default: FACEBOOK_PAGE_ID")
        parser.add_argument("--token", default="", help="Page token. Default: INSTAGRAM_PAGE_ACCESS_TOKEN/FACEBOOK_ACCESS_TOKEN")

    def handle(self, *args, **options):
        page_id = options["page_id"] or getattr(settings, "FACEBOOK_PAGE_ID", "")
        token = options["token"] or getattr(settings, "INSTAGRAM_PAGE_ACCESS_TOKEN", "") or getattr(settings, "FACEBOOK_ACCESS_TOKEN", "")
        if not page_id:
            raise CommandError("FACEBOOK_PAGE_ID non configurato e --page-id non passato.")
        if not token:
            raise CommandError("Token mancante: configura INSTAGRAM_PAGE_ACCESS_TOKEN o FACEBOOK_ACCESS_TOKEN.")

        response = requests.get(
            f"https://graph.facebook.com/v24.0/{page_id}/subscribed_apps",
            params={"access_token": token},
            timeout=20,
        )
        self.stdout.write(f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            self.stdout.write(response.text[:1000])
            return

        if "error" in payload:
            self.stdout.write(self.style.ERROR(str(payload["error"])))
            return
        for app in payload.get("data", []):
            fields = app.get("subscribed_fields", [])
            self.stdout.write(f"app: {app.get('name') or app.get('id')}")
            self.stdout.write(f"fields: {', '.join(fields)}")
