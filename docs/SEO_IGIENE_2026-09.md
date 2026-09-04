# Igiene SEO – settembre 2026

Contesto: dal 24 giugno 2026 (June 2026 spam update) Google ha smesso di scansionare
i nuovi articoli ("Rilevata, ma attualmente non indicizzata" cresce di ~8 URL/giorno).
Queste modifiche non risolvono da sole la classificazione, ma tolgono il crawl sprecato
e i duplicati che oggi fanno sembrare il sito piu' "industriale" di quanto sia.

## Cosa cambia

| File | Modifica | Perche' |
|---|---|---|
| `home/middleware/security.py` | `SEOMiddleware` legge l'host reale da `X-Forwarded-Host` (primo valore, senza porta) | dietro Apache Django vedeva l'host del backend: il middleware non intercettava mai `www.` e `https://www.ombradelportico.it/...` rispondeva 200 con il sito duplicato. **Non** usare `USE_X_FORWARDED_HOST`: provato il 04/09/2026, Apache manda un valore che `ALLOWED_HOSTS` rifiuta e tutto il sito risponde 400 |
| `home/templates/robots.txt` | `Disallow: /s/` e `Disallow: /articolo/*/fonti/` (anche per Googlebot-News); rimosso `Crawl-delay` | l'8% delle richieste di Googlebot erano 302 sui short link; le pagine `/fonti/` (noindex) assorbivano scansione "di rilevamento" |
| `home/templates/dettaglio_articolo.html` | `rel="nofollow"` sul link "Visualizza le fonti" | coerente con il blocco in robots |
| `home/templates/homepage.html` | rimosso `potentialAction/SearchAction` con `?categoria={search_term_string}` | generava URL `/?categoria=...` scoperti da Google (duplicati delle pagine categoria); markup deprecato |
| `home/views.py` | canonical di `/?categoria=Nome` -> `/categoria/<slug>/` | prima puntava alla homepage |
| `home/tests_seo_hygiene.py` | 11 test nuovi | middleware con `X-Forwarded-Host` (anche lista e porta), robots, canonical, nofollow, JSON-LD |

Nota: la Google Indexing API per gli articoli era gia' disattivata dal 23/11/2025
(`indexing_notifier.py`); resta solo IndexNow. Nessuna modifica necessaria.

## Deploy

```bash
ssh root@ombradelportico.it
cd /var/www/carpi-news && git pull
sudo systemctl restart gunicorn
curl -sI https://ombradelportico.it/ | head -1   # 200
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

**Fatto il 04/09/2026 direttamente in Apache.** Il VirtualHost :443
(`/etc/apache2/sites-enabled/000-default-le-ssl.conf`) contiene `RequestHeader set
X-Forwarded-Host "ombradelportico.it"` scritto a mano, quindi Django non vede mai l'host
"www" (ed e' anche la causa del 400 con `USE_X_FORWARDED_HOST`: mod_proxy accoda un secondo
valore). Il redirect e' stato messo nel VirtualHost, subito dopo `ServerAlias`, prima del proxy
(backup in `/root/000-default-le-ssl.conf.bak-*`):

```apache
RewriteEngine On
RewriteCond %{HTTP_HOST} ^www\.ombradelportico\.it$ [NC]
RewriteRule ^ https://ombradelportico.it%{REQUEST_URI} [R=301,L]
```

poi `sudo apachectl configtest && sudo systemctl reload apache2`. Verificato: `https://www...` -> 301
verso il dominio nudo, query string conservata. Resta un doppio salto solo per `http://www...`
(prima su `https://www`, poi sul dominio nudo): innocuo, viene dal RewriteRule di certbot nel :80.

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

Eseguiti il 04/09/2026: 11/11 OK. `ShareLinkTests` + `ErrorPageTests`: 48/50, i 2 che
falliscono (`og:image` con varianti immagine) falliscono anche senza queste modifiche.

## Dopo il deploy: cosa guardare in Search Console

- Impostazioni > Statistiche di scansione > "Per risposta": la quota 302 deve scendere.
- "Per scopo" > Rilevamento: e' il segnale della rivalutazione; oggi e' ~0 dal 24/6.
- Indicizzazione > Pagine > "Rilevata, ma attualmente non indicizzata": oggi 1.390, in crescita.

---

# Banner cookie e Consent Mode (04/09/2026, secondo giro)

Il contatore `views` resta com'era (incremento in `dettaglio_articolo` a ogni richiesta
non riconosciuta come bot, dedup di sessione): e' un contatore di richieste, non di
lettori. Le letture reali si misurano con il tool "visite" (log Apache, bot esclusi).
Per riferimento: sui 243 articoli pubblicati dal 18/07 il contatore segnava 89.035
contro 6.494 letture umane nei log (x13,7), perche' `facebookexternalhit` non contiene
"bot" e ricarica la pagina a ogni condivisione. Un beacon JS cookieless era stato
provato e ritirato lo stesso giorno per scelta editoriale.

| File | Modifica |
|---|---|
| `home/templates/base.html` | testo del banner senza "continuando la navigazione accetti" (non e' consenso valido per il Garante e non corrispondeva al codice); link "Preferenze cookie" nel footer che riapre il banner; Consent Mode v2 (`gtag('consent','default', tutto denied)` + `update` a granted su "Accetta tutti") |
| `home/templates/robots.txt` | `Disallow: /banner/impression/` (beacon impression banner) |

## Consenso: numeri e doppio prompt
Dal 13/07/2026 GA parte solo con "Accetta tutti". Tra il 18/07 e il 02/09 GA ha visto il
39% delle pagine e il 27% dei visitatori rispetto ai log del server: sei lettori su dieci
rifiutano o ignorano il banner. Il secondo prompt che compare dopo "Accetta tutti" e' il
messaggio Funding Choices di AdSense (CMP certificato richiesto da Google per l'EEA): si
configura in AdSense, non nel repo. Per avere un solo prompt: usare il CMP di Google come
unico banner (con Consent Mode gia' predisposto qui), oppure disattivare il messaggio in
AdSense > Privacy e messaggi (solo con un altro CMP certificato).
