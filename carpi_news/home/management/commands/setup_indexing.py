"""
Management command per configurare il sistema di indicizzazione.
Genera chiave IndexNow e fornisce istruzioni per Google Indexing API.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
import os
import secrets
from pathlib import Path


class Command(BaseCommand):
    help = 'Configura il sistema di notifica per motori di ricerca (IndexNow + Google Indexing API)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== Setup Sistema di Indicizzazione ===\n'))

        # 1. IndexNow Setup
        self.stdout.write(self.style.WARNING('1. IndexNow Configuration'))
        self.setup_indexnow()

        # 2. Google Indexing API Setup
        self.stdout.write(self.style.WARNING('\n2. Google Indexing API Configuration'))
        self.setup_google_indexing()

        self.stdout.write(self.style.SUCCESS('\n[OK] Setup completato!'))

    def setup_indexnow(self):
        """Genera chiave IndexNow e crea file di verifica."""
        # Genera chiave casuale (32 caratteri hex)
        indexnow_key = secrets.token_hex(16)

        self.stdout.write(f'\nChiave IndexNow generata: {indexnow_key}')
        self.stdout.write('\n=> Aggiungi al tuo file .env:')
        self.stdout.write(f'  INDEXNOW_KEY={indexnow_key}')

        # Crea file di verifica nella root del sito
        static_root = Path(settings.BASE_DIR) / 'static'
        key_file_path = static_root / f'{indexnow_key}.txt'

        try:
            key_file_path.parent.mkdir(parents=True, exist_ok=True)
            key_file_path.write_text(indexnow_key)
            self.stdout.write(self.style.SUCCESS(f'\n[OK] File di verifica creato: {key_file_path}'))
            self.stdout.write(f'  Verra servito su: {settings.SITE_URL}/{indexnow_key}.txt')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n[ERRORE] Errore creazione file: {e}'))

        self.stdout.write('\nDocs: https://www.indexnow.org/documentation')

    def setup_google_indexing(self):
        """Fornisce istruzioni per configurare Google Indexing API."""
        self.stdout.write('''
Google Indexing API richiede un Service Account di Google Cloud:

Step 1: Crea progetto Google Cloud
  > https://console.cloud.google.com/

Step 2: Abilita Google Indexing API
  > https://console.cloud.google.com/apis/library/indexing.googleapis.com

Step 3: Crea Service Account
  > https://console.cloud.google.com/iam-admin/serviceaccounts
  - Nome: "Indexing API Service Account"
  - Ruolo: Owner (o Editor)

Step 4: Genera chiave JSON
  > Vai al Service Account creato
  > Tab "Keys" > "Add Key" > "Create new key" > JSON
  > Scarica il file JSON

Step 5: Aggiungi il Service Account a Search Console
  > https://search.google.com/search-console
  > Impostazioni > Utenti e autorizzazioni
  > Aggiungi il Service Account email come proprietario
  > Email formato: nome@project-id.iam.gserviceaccount.com

Step 6: Configura Django
  > Carica il file JSON sul server
  > Aggiungi al .env:
    GOOGLE_INDEXING_CREDENTIALS=/percorso/completo/service-account.json

Quota giornaliera: 200 richieste/giorno (gratuito)
Docs: https://developers.google.com/search/apis/indexing-api/v3/quickstart
        ''')

        # Verifica se già configurato
        credentials_path = os.getenv('GOOGLE_INDEXING_CREDENTIALS')
        if credentials_path and os.path.exists(credentials_path):
            self.stdout.write(self.style.SUCCESS(f'\n[OK] Credentials trovate: {credentials_path}'))
        else:
            self.stdout.write(self.style.WARNING('\n[ATTENZIONE] Credentials non ancora configurate'))
