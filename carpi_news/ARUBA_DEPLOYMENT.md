# Deploy Django su Aruba VPS

## 🏗️ Prerequisiti Aruba
- **VPS Cloud Aruba** con Linux (Ubuntu 22.04 consigliato)
- Accesso SSH al server
- Dominio configurato sui DNS di Aruba

## 1. Configurazione Iniziale VPS

```bash
# Connessione SSH al VPS
ssh root@your-vps-ip

# Aggiornamento sistema
apt update && apt upgrade -y

# Installazione dipendenze
apt install -y python3 python3-pip python3-venv nginx git certbot python3-certbot-nginx
```

## 2. Setup Progetto

```bash
# Creazione directory progetto
mkdir -p /var/www/ombra-del-portico
cd /var/www/ombra-del-portico

# Clone repository (sostituisci con il tuo repo)
git clone https://github.com/your-username/carpi-news.git .
# OPPURE carica i file via FTP/SFTP

# Creazione virtual environment
python3 -m venv venv
source venv/bin/activate

# Installazione dipendenze
pip install -r requirements.txt
```

## 3. Configurazione Environment

```bash
# Crea file .env
nano .env
```

Contenuto `.env`:
```bash
DEBUG=False
SECRET_KEY=your-generated-secret-key-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,your-vps-ip
ANTHROPIC_API_KEY=your-anthropic-api-key

# Database (SQLite per iniziare)
# Per PostgreSQL:
# DATABASE_URL=postgresql://user:pass@localhost:5432/carpi_news

# Email (opzionale)
EMAIL_HOST=smtps.aruba.it
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_HOST_USER=your@yourdomain.com
EMAIL_HOST_PASSWORD=your-email-password

# Security per HTTPS
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## 4. Setup Database e Static Files

```bash
# Migrazione database
python manage.py migrate

# Raccolta file statici
python manage.py collectstatic --noinput

# Creazione superuser
python manage.py createsuperuser
```

## 5. Configurazione Gunicorn

```bash
# Test Gunicorn
gunicorn carpi_news.wsgi:application --bind 0.0.0.0:8000

# Creazione servizio systemd
nano /etc/systemd/system/ombra-del-portico.service
```

Contenuto servizio:
```ini
[Unit]
Description=Ombra del Portico Django app
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/ombra-del-portico
Environment="PATH=/var/www/ombra-del-portico/venv/bin"
EnvironmentFile=/var/www/ombra-del-portico/.env
ExecStart=/var/www/ombra-del-portico/venv/bin/gunicorn --access-logfile - --workers 3 --bind unix:/var/www/ombra-del-portico/ombra-del-portico.sock carpi_news.wsgi:application

[Install]
WantedBy=multi-user.target
```

```bash
# Avvio servizio
systemctl daemon-reload
systemctl enable ombra-del-portico
systemctl start ombra-del-portico
systemctl status ombra-del-portico
```

## 6. Configurazione Nginx

```bash
nano /etc/nginx/sites-available/ombra-del-portico
```

Contenuto Nginx:
```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        root /var/www/ombra-del-portico;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        root /var/www/ombra-del-portico;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/ombra-del-portico/ombra-del-portico.sock;
    }
}
```

```bash
# Attivazione sito
ln -s /etc/nginx/sites-available/ombra-del-portico /etc/nginx/sites-enabled
nginx -t
systemctl restart nginx
```

## 7. Configurazione SSL con Let's Encrypt

```bash
# Certificato SSL automatico
certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Test rinnovo automatico
certbot renew --dry-run
```

## 8. DNS Aruba

Nel pannello Aruba, configura:
- **Record A**: `yourdomain.com` → IP del VPS
- **Record A**: `www.yourdomain.com` → IP del VPS

## 9. Monitoring e Manutenzione

```bash
# Controllo logs
journalctl -u ombra-del-portico -f
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Aggiornamenti
cd /var/www/ombra-del-portico
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
systemctl restart ombra-del-portico
```

## 10. Backup Automatico

```bash
# Script backup database
nano /opt/backup-django.sh
```

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/backups"
mkdir -p $BACKUP_DIR

# Backup database SQLite
cp /var/www/ombra-del-portico/db.sqlite3 $BACKUP_DIR/db_$DATE.sqlite3

# Backup file statici e media
tar -czf $BACKUP_DIR/files_$DATE.tar.gz /var/www/ombra-del-portico/staticfiles/ /var/www/ombra-del-portico/media/

# Rimuovi backup vecchi di 30 giorni
find $BACKUP_DIR -name "*.sqlite3" -mtime +30 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete
```

```bash
chmod +x /opt/backup-django.sh
crontab -e
# Aggiungi: 0 2 * * * /opt/backup-django.sh
```

## 💰 Costi Stimati Aruba

- **VPS Small**: ~15-25€/mese
- **Dominio**: ~15€/anno
- **Backup Cloud**: ~5€/mese (opzionale)

## 🔧 Troubleshooting

**Errore 502 Bad Gateway:**
```bash
systemctl status ombra-del-portico
journalctl -u ombra-del-portico -f
```

**File statici non caricati:**
```bash
python manage.py collectstatic --noinput
systemctl restart nginx
```

**Database locked:**
```bash
# Verifica permessi
chown -R www-data:www-data /var/www/ombra-del-portico/
```