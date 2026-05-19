import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Diagnostica il token usato per inviare DM Instagram."

    def add_arguments(self, parser):
        parser.add_argument("--token", default="", help="Token da controllare. Default: INSTAGRAM_PAGE_ACCESS_TOKEN/FACEBOOK_ACCESS_TOKEN")

    def handle(self, *args, **options):
        token = options["token"] or getattr(settings, "INSTAGRAM_PAGE_ACCESS_TOKEN", "") or getattr(settings, "FACEBOOK_ACCESS_TOKEN", "")
        app_id = getattr(settings, "FACEBOOK_APP_ID", "")
        app_secret = getattr(settings, "FACEBOOK_APP_SECRET", "")
        if not token:
            raise CommandError("Token mancante: configura INSTAGRAM_PAGE_ACCESS_TOKEN o FACEBOOK_ACCESS_TOKEN.")
        if not app_id or not app_secret:
            raise CommandError("FACEBOOK_APP_ID e FACEBOOK_APP_SECRET sono richiesti per /debug_token.")

        response = requests.get(
            "https://graph.facebook.com/v24.0/debug_token",
            params={
                "input_token": token,
                "access_token": f"{app_id}|{app_secret}",
            },
            timeout=20,
        )
        self.stdout.write(f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            self.stdout.write(response.text[:1000])
            return

        data = payload.get("data", {})
        self.stdout.write(f"app_id: {data.get('app_id')}")
        self.stdout.write(f"type: {data.get('type')}")
        self.stdout.write(f"is_valid: {data.get('is_valid')}")
        self.stdout.write(f"expires_at: {data.get('expires_at')}")
        self.stdout.write(f"scopes: {', '.join(data.get('scopes', []))}")
        if "error" in payload:
            self.stdout.write(self.style.ERROR(str(payload["error"])))
