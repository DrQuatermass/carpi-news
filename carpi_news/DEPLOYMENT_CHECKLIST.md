# 🚀 Checklist Deploy Aruba VPS

## Pre-Deploy (Da fare ora)

- [ ] **Dominio registrato su Aruba**
  - Suggeriti: ombradelportico.it, ombradelportico.com
  - Costo: ~15€/anno (.it) o ~12€/anno (.com)
  - Annotare nome dominio scelto

- [ ] **VPS Aruba ordinato**
  - Ubuntu 22.04 LTS
  - Minimo 2GB RAM, 1 vCPU
  - IP pubblico annotato
  - Password root sicura

- [ ] **DNS configurato (dopo aver ricevuto IP VPS)**
  - Nel pannello Aruba Domini → Gestione DNS
  - A record: yourdomain.com → IP VPS
  - A record: www.yourdomain.com → IP VPS
  - TTL: 3600 (1 ora)

- [ ] **Chiavi generate localmente**
```bash
cd C:\news\carpi_news
python generate_secret_key.py
```

- [ ] **File .env preparato**
```bash
cp .env.example .env
# Modifica con i tuoi dati reali
```

## Post-Deploy (Dopo aver ricevuto il VPS)

### Connessione Iniziale
- [ ] **Test connessione SSH**
```bash
ssh root@YOUR-VPS-IP
```

### Setup Sistema
- [ ] **Aggiornamento sistema**
```bash
apt update && apt upgrade -y
```

- [ ] **Installazione dipendenze**
```bash
apt install -y python3 python3-pip python3-venv nginx git certbot python3-certbot-nginx
```

### Upload Progetto
- [ ] **Caricamento file progetto**
  - Opzione A: Git clone dal repository
  - Opzione B: Upload via SFTP/SCP

- [ ] **Creazione virtual environment**
```bash
cd /var/www/ombra-del-portico
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configurazione Django
- [ ] **File .env sul server**
```bash
nano /var/www/ombra-del-portico/.env
```

- [ ] **Database setup**
```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### Servizi Sistema
- [ ] **Gunicorn service**
```bash
nano /etc/systemd/system/ombra-del-portico.service
systemctl enable ombra-del-portico
systemctl start ombra-del-portico
```

- [ ] **Nginx configurazione**
```bash
nano /etc/nginx/sites-available/ombra-del-portico
ln -s /etc/nginx/sites-available/ombra-del-portico /etc/nginx/sites-enabled
systemctl restart nginx
```

### SSL e Sicurezza
- [ ] **Certificato Let's Encrypt**
```bash
certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

- [ ] **Test rinnovo automatico**
```bash
certbot renew --dry-run
```

### Test Finali
- [ ] **Sito accessibile via HTTPS**
- [ ] **Admin panel funzionante**
- [ ] **Upload articoli test**
- [ ] **Sistema monitoring attivo**

## 🆘 In Caso di Problemi

### Debug Comandi Utili
```bash
# Status servizi
systemctl status ombra-del-portico
systemctl status nginx

# Log Django
journalctl -u ombra-del-portico -f

# Log Nginx
tail -f /var/log/nginx/error.log

# Test configurazione
nginx -t
python manage.py check --deploy
```

### Contatti Support
- **Aruba VPS**: Ticket dal pannello cloud.aruba.it
- **Django Issues**: Controlla i log sopra
- **SSL Problems**: `certbot renew --force-renewal`

## 📱 Contatti Post-Deploy

Quando il sito è online:
1. **Testa tutti i link**
2. **Verifica form contatto**
3. **Upload primo articolo**
4. **Configura backup automatico**
5. **Setup monitoring email**

---
**Tempo stimato setup completo**: 2-3 ore
**Costo mensile**: ~20€ (VPS + dominio)