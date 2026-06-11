# Assetto server di produzione (ombradelportico.it)

Aggiornato: 2026-06-10. Server "ombraserver", repo in `/var/www/carpi-news`, branch di produzione `banners`, venv in `/var/www/carpi-news/venv`, DB **PostgreSQL**.

## Servizi systemd

| Unità | Ruolo | Utente |
|---|---|---|
| `gunicorn.service` | Web (3 worker, socket `carpi_news.sock`, dietro Apache) | www-data |
| `carpi-monitors.service` | Monitor sorgenti notizie (`manage.py start_monitors --daemon --stagger 5`) | www-data |

`AUTO_START_MONITORS=False` nel `.env`: Gunicorn NON avvia più monitor né scheduler in-process. Comandi:

```bash
sudo systemctl restart gunicorn         # solo web, non tocca i monitor
sudo systemctl restart carpi-monitors   # solo monitor (es. dopo modifiche in /admin/home/monitorconfig/)
```

Unit file `/etc/systemd/system/carpi-monitors.service`:

```ini
[Unit]
Description=Carpi News - monitor sorgenti notizie
After=network-online.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/carpi-news/carpi_news
ExecStart=/var/www/carpi-news/venv/bin/python manage.py start_monitors --daemon --stagger 5
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

## Cron

**root** (`crontab -l`):
- `*/15min` — `process_pending_pubbliredazionali`
- `17:30` — `send_newsletter`
- `*/30min` — `retry_failed_social_shares` (con flock)

**www-data** (`crontab -u www-data -l`):
- `7:50` (ora italiana) — `manage.py reshare_tomorrow_events` → `logs/reshare_cron.log`
- `8:00` (ora italiana) — `editoriale.py` → `logs/editoriale_cron.log`
- `8:05` (ora italiana) — `manage.py genera_cosa_fare_oggi` → `logs/cosa_fare_oggi_cron.log`

Tutte le righe usano `/var/www/carpi-news/venv/bin/python` e `flock`.

**⚠ TRAPPOLA FUSO ORARIO**: il server è su UTC e il cron di Ubuntu **ignora `CRON_TZ`**. Gli orari nelle righe cron classiche sono UTC. Per orari in ora italiana (a prova di ora legale) usare il pattern minuto-per-minuto, come fa anche la riga newsletter di root:
```
* * * * * [ "$(TZ=Europe/Rome date +\%H:\%M)" = "08:00" ] && <comando>
```

## Unit rimosse (storia)

- `carpi-editoriale.service` (creata ~maggio 2026, lanciava `editoriale_scheduler.py` h24): **rimossa il 2026-06-10**, sostituita dalla riga cron delle 8:00. Se ricompare un processo `editoriale_scheduler.py`, qualcuno l'ha ricreata — l'editoriale deve girare SOLO via cron, altrimenti esce doppio.

## Regole d'oro

1. **Sul server solo `migrate`, MAI `makemigrations` né `--merge`** — le migration si generano in locale e arrivano col `git pull`. (A giugno 2026 sono state bonificate 33 migration generate sul server nel corso dei mesi, di cui 2 duplicate di migration tracciate.)
2. Backup DB con `pg_dump` (è PostgreSQL, NON copiare db.sqlite3).
3. Gli scheduler in-app di `apps.py` (editoriale, cosa_fare_oggi, reshare, newsletter) sono disattivati da `AUTO_START_MONITORS=False`: i sostituti sono le righe cron sopra. Non riattivarli, altrimenti doppia esecuzione (es. doppio invio newsletter alle 17:30).

## Log

Tutti in `/var/www/carpi-news/carpi_news/logs/` (NON in `/var/www/carpi-news/logs/`): `monitors.log`, `carpi_news.log`, `*_cron.log`, ecc.

## Deploy standard

```bash
cd /var/www/carpi-news
git pull origin banners
source venv/bin/activate && cd carpi_news
pip install -r requirements.txt --quiet
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart gunicorn
# se il deploy tocca i monitor: sudo systemctl restart carpi-monitors
```
