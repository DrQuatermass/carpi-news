# ✅ Deploy Checklist - Ombra del Portico su Aruba

## Pre-Deploy Completato ✅
- [x] Configurazione email Aruba testata e funzionante
- [x] Django configurato per produzione (DEBUG=False)
- [x] File statici raccolti in staticfiles/
- [x] Database SQLite pronto (119 articoli, 71 approvati)
- [x] Sistema di monitoraggio universale configurato
- [x] File .htaccess creato per Apache/Aruba
- [x] Script deploy.py testato con successo

## File Pronti per Caricamento 📁
Caricare TUTTI i file e directory su Aruba via FTP/SFTP:

### File di Configurazione
- `.env` (configurazioni produzione)
- `.htaccess` (configurazione Apache)
- `requirements.txt` (dipendenze Python)
- `runtime.txt` (versione Python)
- `Procfile` (configurazione server)

### Directory Principali
- `carpi_news/` (progetto Django)
- `home/` (app principale)
- `staticfiles/` (file statici raccolti)
- `media/` (directory upload)
- `logs/` (directory log)
- `locks/` (directory lock files)
- `db.sqlite3` (database con articoli)

### Script di Gestione
- `start_universal_monitors.py` (avvio monitoraggio)
- `deploy.py` (script deploy)
- `manage.py` (Django management)

## Configurazioni Server Aruba 🔧

### 1. Caricamento File
```bash
# Via FTP/SFTP caricare tutti i file nella directory web del dominio
# Es: /home/username/public_html/ o /var/www/ombradelportico.it/
```

### 2. Configurazione Python
- Verificare Python 3.12.3 disponibile
- Installare dipendenze: `pip install -r requirements.txt`
- Attivare virtual environment se necessario

### 3. Configurazione Apache
- Il file `.htaccess` è già configurato
- Verifica che mod_rewrite sia abilitato
- Controlla che il dominio punti alla directory corretta

### 4. Post-Deploy
```bash
# Sul server Aruba:
python manage.py migrate
python manage.py collectstatic --noinput
python start_universal_monitors.py &  # avvia in background
```

## Verifiche Finali 🧪
- [ ] Sito accessibile su https://ombradelportico.it
- [ ] Homepage mostra articoli approvati
- [ ] Admin panel accessibile su /admin/
- [ ] Email di notifica funzionanti
- [ ] Sistema di monitoraggio attivo
- [ ] File statici (CSS/JS/immagini) caricati correttamente

## Monitoraggio Post-Deploy 📊
- Logs disponibili in `logs/monitors.log`
- Monitor status controllabile nei log
- Email di notifica per nuovi articoli
- Database SQLite gestibile via admin Django

## Contatti Supporto 📞
- Email: redazione@ombradelportico.it  
- Sistema configurato per notifiche automatiche
- Monitor multiscreen: Carpi Calcio, Comune, YouTube, ANSA, etc.

---
**Deploy completato**: Tutti i componenti testati e pronti per produzione Aruba ✨