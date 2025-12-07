# Configurazione Cache Headers Apache per /media/

## Problema
Gli header di cache in `.htaccess` non vengono applicati alle risorse in `/media/` perché Apache le serve tramite `Alias` diretto che bypassa `.htaccess`.

## Soluzione
Aggiungere gli header di cache direttamente nella configurazione del VirtualHost Apache.

## Istruzioni

### 1. Modifica configurazione VirtualHost

```bash
sudo nano /etc/apache2/sites-available/ombradelportico.conf
```

### 2. Trova la sezione `<Directory>` per `/media/`

Cerca questa sezione:

```apache
Alias /media /var/www/carpi-news/carpi_news/media
<Directory /var/www/carpi-news/carpi_news/media>
    Require all granted
</Directory>
```

### 3. Sostituisci con questa configurazione completa

```apache
Alias /media /var/www/carpi-news/carpi_news/media
<Directory /var/www/carpi-news/carpi_news/media>
    Require all granted

    # Cache headers per performance
    <IfModule mod_headers.c>
        # Immagini - cache 1 anno (immutabili con hash nel nome)
        <FilesMatch "\.(jpg|jpeg|png|gif|webp|svg|ico)$">
            Header set Cache-Control "public, max-age=31536000, immutable"
        </FilesMatch>

        # Altri file media
        <FilesMatch "\.(pdf|mp4|webm)$">
            Header set Cache-Control "public, max-age=2592000"
        </FilesMatch>
    </IfModule>

    # Expires headers (fallback per client che non supportano Cache-Control)
    <IfModule mod_expires.c>
        ExpiresActive On
        ExpiresByType image/jpeg "access plus 1 year"
        ExpiresByType image/png "access plus 1 year"
        ExpiresByType image/webp "access plus 1 year"
        ExpiresByType image/svg+xml "access plus 1 year"
        ExpiresByType image/gif "access plus 1 year"
    </IfModule>
</Directory>
```

### 4. Verifica e ricarica Apache

```bash
# Verifica sintassi
sudo apache2ctl configtest

# Se OK, ricarica configurazione
sudo systemctl reload apache2
```

### 5. Verifica cache headers

```bash
# Test con curl
curl -I https://ombradelportico.it/media/images/downloaded/comune_carpi_xxx.webp

# Dovresti vedere:
# Cache-Control: public, max-age=31536000, immutable
```

## Risultato atteso

- **Prima**: `TTL cache: None` (0 secondi)
- **Dopo**: `TTL cache: 1 year` (31536000 secondi)
- **PageSpeed**: warning "Utilizza durate della memorizzazione nella cache efficienti" risolto
- **Risparmio**: -206 KiB nelle visite successive (immagini non ri-scaricate)

## Note

- I file con hash nel nome (es. `comune_carpi_xxx_abc123.webp`) sono immutabili → cache di 1 anno sicura
- Se aggiorni un'immagine, verrà generato un nuovo hash → nuovo URL → cache non interferisce
- La direttiva `immutable` dice al browser di non rivalidare mai il file cached (massima performance)
