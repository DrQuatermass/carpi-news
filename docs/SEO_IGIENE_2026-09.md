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

# Contatore letture, banner cookie, Consent Mode (04/09/2026, secondo giro)

## Perche'
Il contatore `views` veniva incrementato a ogni richiesta della pagina che non avesse
"bot/crawler/spider/..." nello user-agent. `facebookexternalhit` (il crawler di Facebook,
che ricarica la pagina a ogni condivisione o anteprima) non contiene quelle parole e da
solo faceva l'85% delle richieste bot sugli articoli. Misura sui 243 articoli pubblicati
dal 18/07 (log Apache completi): 89.035 views nel DB contro 6.494 letture umane (x13,7);
per articolo: DB ≈ 300 richieste di crawler + 2,6 x letture umane.

## Cosa cambia
| File | Modifica |
|---|---|
| `home/views.py` | `dettaglio_articolo` non incrementa piu' `views` e non crea piu' la sessione; nuova vista `article_view_beacon` (POST, csrf-exempt, 204): filtra i crawler per user-agent (incluso facebookexternalhit, whatsapp, telegram, lighthouse...), dedup 30 minuti su hash (articolo, IP, UA) in cache, nessun dato utente salvato |
| `carpi_news/urls.py` | `beacon/view/<id>/` |
| `home/templates/dettaglio_articolo.html` | `navigator.sendBeacon` dopo 2 s di pagina visibile |
| `home/templates/robots.txt` | `Disallow: /beacon/` e `/banner/impression/` |
| `home/templates/base.html` | testo del banner senza "continuando la navigazione accetti" (non e' consenso valido per il Garante e non corrispondeva al codice); link "Preferenze cookie" nel footer che riapre il banner; Consent Mode v2 (`gtag('consent','default', tutto denied)` + `update` a granted su "Accetta tutti") |
| `home/management/commands/ricalibra_views.py` | ricalibra i contatori: dai log (CSV `slug,views_umane`) per gli articoli dal 18/07, per divisione (default 13,7) per gli altri; backup in `views_precedente.csv`; `--dry-run` |
| `home/tests_views_beacon.py` | 8 test |

## Deploy
```bash
cd /var/www/carpi-news && git pull origin banners && sudo systemctl restart gunicorn
# ricalibrazione (CSV in analisi/views_umane.csv sul PC, da copiare sul server):
cd carpi_news && ../venv/bin/python manage.py ricalibra_views --csv /var/www/carpi-news/views_umane.csv --dry-run
../venv/bin/python manage.py ricalibra_views --csv /var/www/carpi-news/views_umane.csv
```
Nota: i valori ricalibrati per gli articoli precedenti al 18/07 sono una stima (divisione
per il rapporto medio misurato); l'ordinamento "piu' letti" non cambia. I contatori da
qui in avanti contano solo letture con JS eseguito.

## Consenso: numeri e doppio prompt
Dal 13/07/2026 GA parte solo con "Accetta tutti". Tra il 18/07 e il 02/09 GA ha visto il
39% delle pagine e il 27% dei visitatori rispetto ai log del server: sei lettori su dieci
rifiutano o ignorano il banner. Il secondo prompt che compare dopo "Accetta tutti" e' il
messaggio Funding Choices di AdSense (CMP certificato richiesto da Google per l'EEA): si
configura in AdSense, non nel repo. Per avere un solo prompt: usare il CMP di Google come
unico banner (con Consent Mode gia' predisposto qui), oppure disattivare il messaggio in
AdSense > Privacy e messaggi (solo con un altro CMP certificato).
