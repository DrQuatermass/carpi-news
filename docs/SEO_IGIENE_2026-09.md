# Igiene SEO – settembre 2026

Contesto: dal 24 giugno 2026 (June 2026 spam update) Google ha smesso di scansionare
i nuovi articoli ("Rilevata, ma attualmente non indicizzata" cresce di ~8 URL/giorno).
Queste modifiche non risolvono da sole la classificazione, ma tolgono il crawl sprecato
e i duplicati che oggi fanno sembrare il sito piu' "industriale" di quanto sia.

## Cosa cambia

| File | Modifica | Perche' |
|---|---|---|
| `carpi_news/settings.py` | `USE_X_FORWARDED_HOST = True` (solo produzione) | dietro Apache Django vedeva l'host del backend: il `SEOMiddleware` non intercettava mai `www.` e `https://www.ombradelportico.it/...` rispondeva 200 con il sito duplicato |
| `home/templates/robots.txt` | `Disallow: /s/` e `Disallow: /articolo/*/fonti/` (anche per Googlebot-News); rimosso `Crawl-delay` | l'8% delle richieste di Googlebot erano 302 sui short link; le pagine `/fonti/` (noindex) assorbivano scansione "di rilevamento" |
| `home/templates/dettaglio_articolo.html` | `rel="nofollow"` sul link "Visualizza le fonti" | coerente con il blocco in robots |
| `home/templates/homepage.html` | rimosso `potentialAction/SearchAction` con `?categoria={search_term_string}` | generava URL `/?categoria=...` scoperti da Google (duplicati delle pagine categoria); markup deprecato |
| `home/views.py` | canonical di `/?categoria=Nome` -> `/categoria/<slug>/` | prima puntava alla homepage |
| `home/tests_seo_hygiene.py` | 8 test nuovi | middleware con `X-Forwarded-Host`, robots, canonical, nofollow, JSON-LD |

Nota: la Google Indexing API per gli articoli era gia' disattivata dal 23/11/2025
(`indexing_notifier.py`); resta solo IndexNow. Nessuna modifica necessaria.

## Deploy

```bash
ssh root@ombradelportico.it
cd /var/www/carpi-news && git pull
grep -n "^ALLOWED_HOSTS" carpi_news/.env   # DEVE contenere ombradelportico.it e www.ombradelportico.it
sudo systemctl restart gunicorn
```

## Verifica (dal PC)

```bash
curl -sI https://www.ombradelportico.it/ | grep -i -E "^HTTP|^location"
#   atteso: HTTP/1.1 301  +  Location: https://ombradelportico.it/
curl -s https://ombradelportico.it/robots.txt | grep -E "Disallow: /s/|fonti|Crawl-delay"
#   attesi i due Disallow, nessun Crawl-delay
curl -s "https://ombradelportico.it/?categoria=Cronaca" | grep -o '<link rel="canonical"[^>]*>'
#   atteso: href="https://ombradelportico.it/categoria/cronaca/"
```

Se `www` risponde ancora 200: Apache non inoltra `X-Forwarded-Host`
(`ProxyAddHeaders Off`?). In quel caso aggiungere nel VirtualHost :443, prima dei ProxyPass:

```apache
RewriteEngine On
RewriteCond %{HTTP_HOST} ^www\.ombradelportico\.it$ [NC]
RewriteRule ^ https://ombradelportico.it%{REQUEST_URI} [R=301,L]
```

poi `sudo apachectl configtest && sudo systemctl reload apache2`.

## Test

La catena di migrazioni di `home` ha due `0016` che aggiungono entrambe `fonti_web`:
`manage.py test` su un DB vuoto fallisce prima di partire (`duplicate column name: fonti_web`).
Per eseguire i test senza toccare le migrazioni:

```bash
# odp_test_settings.py (fuori dal repo)
from carpi_news.settings import *
MIGRATION_MODULES = {'home': None, 'admin_panel': None}
```

```bash
DJANGO_SETTINGS_MODULE=odp_test_settings PYTHONPATH=<cartella del file> python manage.py test home.tests_seo_hygiene
```

Eseguiti il 04/09/2026: 8/8 OK. `ShareLinkTests` + `ErrorPageTests`: 48/50, i 2 che
falliscono (`og:image` con varianti immagine) falliscono anche senza queste modifiche.

## Dopo il deploy: cosa guardare in Search Console

- Impostazioni > Statistiche di scansione > "Per risposta": la quota 302 deve scendere.
- "Per scopo" > Rilevamento: e' il segnale della rivalutazione; oggi e' ~0 dal 24/6.
- Indicizzazione > Pagine > "Rilevata, ma attualmente non indicizzata": oggi 1.390, in crescita.
