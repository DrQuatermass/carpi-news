import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Scambia un User token Facebook e stampa il Page Access Token della pagina configurata."

    def add_arguments(self, parser):
        parser.add_argument("--user-token", required=True, help="User access token generato da Graph API Explorer")
        parser.add_argument("--page-id", default="", help="Page ID. Default: FACEBOOK_PAGE_ID")
        parser.add_argument(
            "--skip-exchange",
            action="store_true",
            help="Non scambia in long-lived token; usa direttamente lo user token passato.",
        )

    def handle(self, *args, **options):
        page_id = options["page_id"] or getattr(settings, "FACEBOOK_PAGE_ID", "")
        app_id = getattr(settings, "FACEBOOK_APP_ID", "")
        app_secret = getattr(settings, "FACEBOOK_APP_SECRET", "")
        user_token = options["user_token"]

        if not page_id:
            raise CommandError("FACEBOOK_PAGE_ID non configurato e --page-id non passato.")

        token_for_pages = user_token
        if not options["skip_exchange"]:
            if not app_id or not app_secret:
                raise CommandError("FACEBOOK_APP_ID/FACEBOOK_APP_SECRET richiesti per lo scambio long-lived.")
            token_for_pages = self._exchange_long_lived_user_token(app_id, app_secret, user_token)
            self.stdout.write(self.style.SUCCESS("User token scambiato in long-lived token."))

        page_token = self._fetch_page_token(page_id, token_for_pages)
        self._validate_page_token(page_id, page_token)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Page Access Token trovato. Aggiorna .env cosi':"))
        self.stdout.write("")
        self.stdout.write(f"FACEBOOK_ACCESS_TOKEN='{page_token}'")
        self.stdout.write(f"INSTAGRAM_PAGE_ACCESS_TOKEN='{page_token}'")

    def _exchange_long_lived_user_token(self, app_id: str, app_secret: str, user_token: str) -> str:
        response = requests.get(
            "https://graph.facebook.com/v24.0/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": user_token,
            },
            timeout=20,
        )
        if response.status_code != 200:
            raise CommandError(f"Scambio token fallito: {response.status_code} {response.text[:500]}")
        token = response.json().get("access_token")
        if not token:
            raise CommandError(f"Scambio token senza access_token: {response.text[:500]}")
        return token

    def _fetch_page_token(self, page_id: str, user_token: str) -> str:
        response = requests.get(
            f"https://graph.facebook.com/v24.0/{page_id}",
            params={"fields": "access_token,name", "access_token": user_token},
            timeout=20,
        )
        if response.status_code != 200:
            raise CommandError(f"Recupero Page token fallito: {response.status_code} {response.text[:500]}")
        token = response.json().get("access_token")
        if not token:
            raise CommandError(f"Nessun Page token nella risposta: {response.text[:500]}")
        self.stdout.write(f"Pagina: {response.json().get('name', page_id)}")
        return token

    def _validate_page_token(self, page_id: str, page_token: str) -> None:
        response = requests.get(
            "https://graph.facebook.com/v24.0/me",
            params={"fields": "id,name", "access_token": page_token},
            timeout=20,
        )
        if response.status_code != 200:
            raise CommandError(f"Validazione Page token fallita: {response.status_code} {response.text[:500]}")
        payload = response.json()
        if str(payload.get("id")) != str(page_id):
            raise CommandError(f"Il token ottenuto appartiene a {payload}, non alla pagina {page_id}.")
