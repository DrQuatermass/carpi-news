# Guida Deploy - Ombra del Portico

## 🚀 Deploy del Sito "Ombra del Portico"

### 1. Preparazione Iniziale

```bash
# 1. Genera una SECRET_KEY sicura
python generate_secret_key.py

# 2. Crea il file .env dalla template
cp .env.example .env

# 3. Configura le variabili nel file .env
```

### 2. Variabili d'Ambiente Obbligatorie

```bash
# .env file
DEBUG=False
SECRET_KEY=your-generated-secret-key-from-script
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 3. Opzioni di Deploy

#### A) Railway (Consigliato - Facile)

1. Push su GitHub
2. Connetti Railway al repository
3. Configura variabili d'ambiente su Railway
4. Deploy automatico

```bash
# Comandi locali
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic
```

#### B) PythonAnywhere (Hosting Economico)

1. Upload file via web interface o Git
2. Crea virtual environment
3. Configura WSGI file
4. Imposta variabili d'ambiente

#### C) DigitalOcean/Vultr (VPS)

```bash
# Server setup
sudo apt update
sudo apt install python3-pip python3-venv nginx
git clone your-repository
cd carpi_news
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup database e static files
python manage.py migrate
python manage.py collectstatic
python manage.py createsuperuser

# Run with Gunicorn
gunicorn carpi_news.wsgi:application
```

### 4. Configurazioni per Produzione

#### Database
```bash
# SQLite (default - ok per siti piccoli/medi)
# Nessuna configurazione aggiuntiva

# PostgreSQL (per siti grandi)
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

#### Security
```bash
# Per HTTPS obbligatorio
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

### 5. Monitoraggio e AI

#### Anthropic API
```bash
# Obbligatorio per editoriali AI
ANTHROPIC_API_KEY=sk-ant-api03-...
```

#### YouTube Monitor (Opzionale)
```bash
YOUTUBE_MONITOR_ENABLED=True
YOUTUBE_PLAYLIST_ID=your-playlist-id
YOUTUBE_API_KEY=your-youtube-key
```

### 6. Comandi Post-Deploy

```bash
# Creazione superuser admin
python manage.py createsuperuser

# Update immagini editoriali esistenti
python manage.py update_editorial_images

# Test del sistema
python manage.py test
```

### 7. Backup e Sicurezza

- ✅ File sensibili in .gitignore
- ✅ API keys in variabili d'ambiente  
- ✅ SECRET_KEY sicura generata
- ✅ Debug disabilitato in produzione
- ✅ HTTPS configurato
- ✅ Database protetto

### 8. Monitoraggio Logs

```bash
# Logs Django
tail -f logs/carpi_news.log

# Logs server web
tail -f /var/log/nginx/access.log
```

### 9. Aggiornamenti

```bash
# Deploy nuova versione
git pull origin main
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart your-app
```

### 🔒 Security Checklist

- [ ] DEBUG = False
- [ ] SECRET_KEY forte (50+ caratteri)
- [ ] ALLOWED_HOSTS configurato
- [ ] HTTPS attivato
- [ ] File .env non in Git
- [ ] API keys protette
- [ ] Database backup configurato