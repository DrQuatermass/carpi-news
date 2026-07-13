"""
Forza il re-scrape di Facebook (aggiorna la cache Open Graph) per gli URL degli
articoli. Serve dopo un cambio di og:image (es. passaggio da WebP a JPEG): finche'
Facebook non ri-scrapa, continua a mostrare la vecchia anteprima in cache.

Usa la Graph API: POST /?id=<url>&scrape=true

Autenticazione: preferisce l'APP access token (app_id|app_secret, non scade e ha
limiti piu' alti), con fallback al FACEBOOK_ACCESS_TOKEN.

ORDINE CORRETTO: eseguire DOPO aver deployato il codice e lanciato
`generate_social_jpeg`, cosi' il re-scrape trova gia' il JPEG online.
"""
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse

from home.models import Articolo

GRAPH_VERSION = "v21.0"
# Codici di errore Graph che indicano rate limit / throttling.
RATE_LIMIT_CODES = {4, 17, 32, 341, 613}


class Command(BaseCommand):
    help = "Forza il re-scrape Open Graph di Facebook sugli URL degli articoli"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Elenca gli URL senza chiamare Facebook')
        parser.add_argument('--limit', type=int, default=0,
                            help='Elabora al massimo N articoli (0 = tutti)')
        parser.add_argument('--days', type=int, default=0,
                            help='Solo articoli pubblicati negli ultimi N giorni (0 = tutti)')
        parser.add_argument('--sleep', type=float, default=0.6,
                            help='Pausa in secondi tra una chiamata e l altra (default 0.6)')
        parser.add_argument('--verify', action='store_true',
                            help="Stampa l'immagine restituita da Facebook per ogni URL")
        parser.add_argument('--all', action='store_true',
                            help='Ri-scrapa TUTTI gli articoli approvati, non solo quelli '
                                 'con og:image cambiato (image_16x9). Sconsigliato: quota FB.')

    def _access_token(self):
        app_id = getattr(settings, 'FACEBOOK_APP_ID', '')
        app_secret = getattr(settings, 'FACEBOOK_APP_SECRET', '')
        if app_id and app_secret:
            return f"{app_id}|{app_secret}"
        return getattr(settings, 'FACEBOOK_ACCESS_TOKEN', '')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        days = options['days']
        sleep = options['sleep']
        verify = options['verify']

        token = self._access_token()
        if not token and not dry_run:
            self.stderr.write(self.style.ERROR(
                'Nessun token Facebook configurato (FACEBOOK_APP_ID/SECRET o FACEBOOK_ACCESS_TOKEN).'
            ))
            return

        site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it').rstrip('/')

        qs = Articolo.objects.filter(approvato=True).exclude(slug='').order_by('-data_pubblicazione')
        if not options['all']:
            # Default: solo gli articoli il cui og:image e' effettivamente cambiato
            # (hanno la variante 16x9 -> ora servita in JPEG). Ri-scrapare gli altri
            # non cambia nulla e brucia la quota di scrape di Facebook.
            qs = qs.exclude(image_16x9='').filter(image_16x9__isnull=False)
        if days:
            from django.utils import timezone
            from datetime import timedelta
            qs = qs.filter(data_pubblicazione__gte=timezone.now() - timedelta(days=days))
        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f'Articoli da ri-scrapare: {total}')
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY-RUN (nessuna chiamata a Facebook) ===\n'))
        self.stdout.write('=' * 70)

        ok = failed = 0
        endpoint = f"https://graph.facebook.com/{GRAPH_VERSION}/"

        aborted = False
        for i, art in enumerate(qs.iterator(), 1):
            url = f"{site_url}{reverse('dettaglio_articolo', args=[art.slug])}"

            if dry_run:
                self.stdout.write(url)
                continue

            status, payload = self._scrape(endpoint, url, token)
            if status == 'ok':
                ok += 1
                if verify:
                    self.stdout.write(f'[OK] {url}\n     img: {payload or "(nessuna)"}')
            elif status == 'rate':
                # Limite app: tutte le chiamate successive fallirebbero fino al
                # reset (circa 1 ora). Inutile continuare: fermati e informa.
                self.stdout.write(self.style.ERROR(
                    f'\nRate limit Facebook raggiunto (code {payload}). Interrompo.'
                ))
                aborted = True
                break
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f'[FAIL] {url}\n       {payload}'))

            if i % 25 == 0:
                self.stdout.write(f'  ... {i}/{total} (ok={ok} fail={failed})')

            time.sleep(sleep)

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('RIEPILOGO:'))
        self.stdout.write(f'Re-scrape OK: {ok}')
        self.stdout.write(f'Falliti: {failed}')
        if aborted:
            self.stdout.write(self.style.WARNING(
                'Quota di scrape Facebook esaurita. Gli URL gia fatti restano validi.\n'
                'Riprova tra circa 1 ora, oppure restringi con --days N (es. --days 15)\n'
                'e/o aumenta --sleep. Facebook comunque ri-scrapa da solo al primo share.'
            ))
        self.stdout.write('=' * 70)

    def _scrape(self, endpoint, url, token):
        """Ritorna una tupla (status, payload):
          ('ok', img_url|None) | ('rate', code) | ('error', messaggio)."""
        try:
            r = requests.post(
                endpoint,
                params={'id': url, 'scrape': 'true', 'access_token': token},
                timeout=30,
            )
        except requests.RequestException as exc:
            return ('error', f'richiesta fallita: {exc}')

        try:
            data = r.json()
        except ValueError:
            return ('error', f'HTTP {r.status_code}: risposta non JSON')

        if 'error' in data:
            err = data['error']
            code = err.get('code')
            if code in RATE_LIMIT_CODES or r.status_code == 429:
                return ('rate', code)
            return ('error', f"errore Graph: {err.get('message')} (code {code})")

        img = data.get('image')
        if isinstance(img, list) and img:
            return ('ok', img[0].get('url', ''))
        return ('ok', None)
