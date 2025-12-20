# Guida Migrazione a PostgreSQL

Questa guida spiega come migrare da SQLite a PostgreSQL dopo aver aumentato la RAM del server.

## Prerequisiti

- Server con almeno **1.5GB RAM disponibili** (2GB totali consigliati)
- Accesso root al server
- Backup recente del database

## Metodo 1: Script Automatico (Raccomandato)

### Passo 1: Esegui lo script di migrazione

```bash
cd /var/www/carpi-news/carpi_news
chmod +x migrate_to_postgresql.sh
sudo ./migrate_to_postgresql.sh
```

Lo script:
1. ✅ Verifica che PostgreSQL sia installato
2. ✅ Crea backup di `db.sqlite3`
3. ✅ Crea database PostgreSQL e utente
4. ✅ Genera password sicura
5. ✅ Salva credenziali in file protetto
6. ✅ Installa dipendenze Python (`psycopg2-binary`)
7. ✅ Ferma monitor e Gunicorn
8. ✅ Esporta tutti i dati da SQLite in JSON
9. ✅ Configura `DATABASE_URL` in `.env`

### Passo 2: Completa la migrazione manualmente

Dopo che lo script termina, esegui:

```bash
# Attiva virtualenv
source /var/www/carpi-news/venv/bin/activate
cd /var/www/carpi-news/carpi_news

# Esegui migrazioni su PostgreSQL
python manage.py migrate

# Importa dati da SQLite
python manage.py loaddata /var/www/carpi-news/backups/data_export_*.json

# Verifica che i dati siano stati importati
python manage.py shell
>>> from home.models import Articolo
>>> print(f"Articoli: {Articolo.objects.count()}")
>>> exit()

# Riavvia servizi
sudo systemctl start gunicorn
python manage.py start_monitors
```

### Passo 3: Verifica

1. Visita il sito web e controlla che gli articoli siano visibili
2. Controlla che i monitor stiano girando:
   ```bash
   python manage.py manage_db_monitors status
   ```
3. Monitora i log per verificare che non ci siano più errori "database locked":
   ```bash
   sudo journalctl -u gunicorn -f
   ```

---

## Metodo 2: Migrazione Manuale

Se preferisci fare tutto manualmente:

### 1. Installa PostgreSQL

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib libpq-dev
```

### 2. Crea Database e Utente

```bash
sudo -u postgres psql

-- In psql:
CREATE DATABASE carpi_news_db;
CREATE USER carpi_news_user WITH PASSWORD 'TUA_PASSWORD_SICURA';
GRANT ALL PRIVILEGES ON DATABASE carpi_news_db TO carpi_news_user;
\c carpi_news_db
GRANT ALL ON SCHEMA public TO carpi_news_user;
\q
```

### 3. Installa Dipendenze Python

```bash
source /var/www/carpi-news/venv/bin/activate
pip install psycopg2-binary dj-database-url
```

### 4. Backup SQLite

```bash
cp /var/www/carpi-news/carpi_news/db.sqlite3 /var/www/carpi-news/backups/db_backup_$(date +%Y%m%d).sqlite3
```

### 5. Esporta Dati

```bash
cd /var/www/carpi-news/carpi_news
python manage.py dumpdata --natural-foreign --natural-primary \
    --exclude auth.permission \
    --exclude contenttypes \
    --exclude admin.logentry \
    --exclude sessions.session \
    > /var/www/carpi-news/backups/data_export.json
```

### 6. Configura PostgreSQL

Aggiungi a `.env`:

```bash
DATABASE_URL=postgresql://carpi_news_user:TUA_PASSWORD@localhost:5432/carpi_news_db
```

### 7. Ferma Servizi

```bash
python manage.py manage_db_monitors stop
sudo systemctl stop gunicorn
```

### 8. Migra e Importa

```bash
# Esegui migrazioni
python manage.py migrate

# Importa dati
python manage.py loaddata /var/www/carpi-news/backups/data_export.json
```

### 9. Riavvia Servizi

```bash
sudo systemctl start gunicorn
python manage.py start_monitors
```

---

## Rollback in Caso di Problemi

Se qualcosa va storto:

### 1. Rimuovi DATABASE_URL

Commenta o rimuovi la riga `DATABASE_URL` da `.env`:

```bash
nano .env
# Commenta la riga DATABASE_URL con #
```

### 2. Ripristina Backup SQLite (se necessario)

```bash
cp /var/www/carpi-news/backups/db_backup_*.sqlite3 /var/www/carpi-news/carpi_news/db.sqlite3
```

### 3. Riavvia Gunicorn

```bash
sudo systemctl restart gunicorn
python manage.py start_monitors
```

---

## Ottimizzazione PostgreSQL Post-Migrazione

Dopo la migrazione, ottimizza PostgreSQL per il tuo server:

### 1. Configura PostgreSQL per Server con Poca RAM

Modifica `/etc/postgresql/*/main/postgresql.conf`:

```bash
sudo nano /etc/postgresql/14/main/postgresql.conf
```

Imposta (per server con 2GB RAM):

```conf
shared_buffers = 256MB
effective_cache_size = 512MB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 4.0
effective_io_concurrency = 2
work_mem = 4MB
min_wal_size = 1GB
max_wal_size = 4GB
max_connections = 50
```

### 2. Riavvia PostgreSQL

```bash
sudo systemctl restart postgresql
```

---

## Vantaggi Post-Migrazione

Dopo la migrazione a PostgreSQL:

✅ **Zero errori "database locked"** - concorrenza nativa
✅ **Prestazioni migliori** - fino a 3-5x più veloce con molte scritture
✅ **Scalabilità** - supporta crescita futura (più monitor, traffico)
✅ **Affidabilità** - transazioni ACID più robuste
✅ **Standard produzione** - usato da tutti i progetti Django seri

---

## Monitoraggio Post-Migrazione

### Verifica Connessioni PostgreSQL

```bash
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'carpi_news_db';"
```

### Dimensione Database

```bash
sudo -u postgres psql -c "SELECT pg_size_pretty(pg_database_size('carpi_news_db'));"
```

### Performance Query

```bash
# Abilita logging query lente (>1s)
sudo nano /etc/postgresql/14/main/postgresql.conf

# Aggiungi:
log_min_duration_statement = 1000

# Riavvia
sudo systemctl restart postgresql

# Monitora log
sudo tail -f /var/log/postgresql/postgresql-14-main.log
```

---

## Manutenzione PostgreSQL

### Vacuum Automatico

PostgreSQL ha autovacuum abilitato di default, ma puoi ottimizzarlo:

```bash
sudo -u postgres psql carpi_news_db -c "VACUUM ANALYZE;"
```

### Backup Automatici

Crea uno script di backup giornaliero:

```bash
#!/bin/bash
# /usr/local/bin/backup_postgres.sh

BACKUP_DIR="/var/www/carpi-news/backups/postgres"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup database
sudo -u postgres pg_dump carpi_news_db | gzip > "$BACKUP_DIR/carpi_news_db_$DATE.sql.gz"

# Mantieni solo ultimi 7 giorni
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete

echo "Backup completato: carpi_news_db_$DATE.sql.gz"
```

Aggiungi a crontab per backup giornaliero alle 3:00 AM:

```bash
0 3 * * * /usr/local/bin/backup_postgres.sh >> /var/log/postgres_backup.log 2>&1
```

---

## Troubleshooting

### "FATAL: Peer authentication failed"

Modifica `/etc/postgresql/*/main/pg_hba.conf`:

```bash
sudo nano /etc/postgresql/14/main/pg_hba.conf
```

Cambia:
```
local   all   all   peer
```

In:
```
local   all   all   md5
```

Riavvia:
```bash
sudo systemctl restart postgresql
```

### "Too many connections"

Aumenta `max_connections` in `postgresql.conf` (max consigliato: 100 per 2GB RAM)

### Performance Lente

1. Verifica indici con:
   ```bash
   python manage.py dbshell
   \d+ home_articolo
   ```

2. Esegui ANALYZE:
   ```bash
   sudo -u postgres psql carpi_news_db -c "ANALYZE;"
   ```

---

## Supporto

In caso di problemi:

1. Controlla log PostgreSQL: `sudo tail -f /var/log/postgresql/postgresql-*-main.log`
2. Controlla log Gunicorn: `sudo journalctl -u gunicorn -f`
3. Verifica credenziali in `/var/www/carpi-news/backups/postgresql_credentials_*.txt`
4. Ripristina da backup se necessario (vedi sezione Rollback)
