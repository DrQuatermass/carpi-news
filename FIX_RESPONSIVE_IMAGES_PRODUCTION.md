# Fix Immagini Responsive in Produzione

## Problema identificato

Il sistema di generazione automatica delle immagini responsive esiste già (`home/signals.py:192-236`), ma **non ha generato le versioni responsive per le immagini esistenti** in produzione.

## Possibili cause

1. **Signal non attivo**: I segnali Django potrebbero non essere registrati correttamente
2. **Pillow non installato**: La libreria PIL/Pillow potrebbe mancare in produzione
3. **Permessi insufficienti**: Django potrebbe non avere permessi di scrittura su `/media/images/`
4. **Logging insufficiente**: Gli errori potrebbero essere stati ignorati (usava `logger.debug`)
5. **Immagini pre-esistenti**: Le immagini caricate prima dell'implementazione del signal non hanno versioni responsive

## Modifiche applicate

### 1. Migliorato logging nel signal (`home/signals.py`)
- Cambiato `logger.debug` → `logger.warning` per errori di file non trovato
- Aggiunto `exc_info=True` per stack trace completi
- Aggiunto warning quando nessuna versione viene creata

### 2. Creato script diagnostico
File: `diagnose_responsive_images.py`

Verifica:
- Installazione PIL/Pillow
- Permessi directory
- Esistenza file
- Registrazione segnali Django
- Test generazione manuale

### 3. Creato script generazione batch
File: `generate_all_responsive_production.py`

Genera versioni responsive per:
- `/media/images/uploaded/`
- `/media/images/downloaded/`
- `/media/banners/`

## Istruzioni per risolvere in produzione

### Step 1: Verifica prerequisiti

```bash
# Connettiti al server di produzione
ssh user@ombradelportico.it

# Attiva virtual environment
cd /var/www/carpi-news
source venv/bin/activate

# Verifica Pillow installato
python -c "from PIL import Image; print(f'Pillow: {Image.__version__}')"
```

### Step 2: Esegui script diagnostico

```bash
cd /var/www/carpi-news/carpi_news
python diagnose_responsive_images.py
```

**Output atteso**:
- ✅ PIL/Pillow installato
- ✅ MEDIA_ROOT scrivibile
- ✅ Signal registrato
- ⚠️ File senza versioni responsive

### Step 3: Deploy modifiche codice

```bash
# Sul tuo computer locale (Windows)
cd C:\news
git add .
git commit -m "Fix: migliorato logging signal immagini responsive e creati script diagnostici"
git push

# Sul server
cd /var/www/carpi-news
git pull origin main  # o banners, a seconda del branch

# Riavvia Gunicorn per caricare le modifiche
sudo systemctl restart gunicorn
```

### Step 4: Genera versioni responsive mancanti

```bash
cd /var/www/carpi-news/carpi_news

# Esegui lo script di generazione batch
python generate_all_responsive_production.py

# Oppure solo per uploaded (più veloce)
python create_responsive_uploaded_images.py
```

**Tempo stimato**: 5-15 minuti a seconda del numero di immagini

### Step 5: Verifica risultati

```bash
# Conta versioni responsive create
find /var/www/carpi-news/carpi_news/media/images/uploaded -name "*-400w.webp" | wc -l
find /var/www/carpi-news/carpi_news/media/images/downloaded -name "*-400w.webp" | wc -l
find /var/www/carpi-news/carpi_news/media/banners -name "*-400w.webp" | wc -l

# Controlla un'immagine specifica
ls -lh /var/www/carpi-news/carpi_news/media/banners/catto*
```

**Output atteso**:
```
catto.webp           30 KB  (originale)
catto-400w.webp      15 KB  (responsive)
catto-600w.webp      24 KB  (responsive)
catto-800w.webp      30 KB  (responsive, uguale a originale se <= 800px)
```

### Step 6: Testa con Lighthouse

1. Apri Chrome DevTools → Lighthouse
2. Esegui audit Performance
3. Verifica miglioramento in "Properly size images"

**Risultato atteso**:
- ✅ Risparmio stimato ridotto da ~100 KiB a < 10 KiB
- ✅ LCP migliorato (immagini più leggere)

## Monitoraggio futuro

### Verifica signal funziona per nuove immagini

```bash
# Carica una nuova immagine dall'admin Django
# Poi verifica che vengano create le versioni responsive
tail -f /var/www/carpi-news/logs/django.log | grep "responsive"
```

**Output atteso**:
```
INFO: Generazione versioni responsive per: /path/to/image.webp
INFO: Generate 3 versioni responsive per [Titolo Articolo]
```

### Se il signal non funziona

Verifica che i segnali siano registrati in `home/apps.py`:

```python
class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'home'

    def ready(self):
        import home.signals  # <-- IMPORTANTE: deve essere presente
```

## Risultati Lighthouse previsti

**Prima** (problemi identificati):
```
Le_immagini_della_celebrazione_del_1955_2.webp
  Dimensioni risorsa: 39.1 KiB
  Risparmi stimati: 27.3 KiB

catto.webp (banner)
  Dimensioni risorsa: 30.0 KiB
  Risparmi stimati: 21.3 KiB

Totale risparmio: ~102 KiB
```

**Dopo** (con versioni responsive):
```
Le_immagini_della_celebrazione_del_1955_2-400w.webp (mobile)
  Dimensioni risorsa: ~12 KiB ✅
  Risparmi stimati: < 1 KiB ✅

catto-400w.webp (banner mobile)
  Dimensioni risorsa: ~15 KiB ✅
  Risparmi stimati: < 1 KiB ✅

Totale risparmio: < 10 KiB ✅
```

## Script disponibili

| Script | Scopo | Quando usare |
|--------|-------|--------------|
| `diagnose_responsive_images.py` | Diagnostica | Prima di tutto, per capire il problema |
| `create_responsive_uploaded_images.py` | Genera responsive per `/uploaded/` | Per immagini caricate manualmente |
| `generate_all_responsive_production.py` | Genera per tutte le directory | Una tantum per risolvere tutto |

## Troubleshooting

### Errore: PIL/Pillow non installato
```bash
pip install Pillow
```

### Errore: Permission denied
```bash
# Verifica owner directory
ls -ld /var/www/carpi-news/carpi_news/media/images/

# Dovrebbe essere: drwxr-xr-x www-data www-data

# Se necessario, correggi permessi
sudo chown -R www-data:www-data /var/www/carpi-news/carpi_news/media/
sudo chmod -R 755 /var/www/carpi-news/carpi_news/media/
```

### Signal non si attiva
```bash
# Verifica che home/signals.py sia importato
python manage.py shell
>>> from home import signals
>>> from django.db.models.signals import post_save
>>> from home.models import Articolo
>>> receivers = post_save._live_receivers(Articolo)
>>> [r.__name__ for r in receivers if hasattr(r, '__name__')]
```

Dovrebbe mostrare `generate_responsive_images_on_save` nella lista.

## Note finali

- Le versioni responsive verranno generate automaticamente per **nuove immagini** caricate
- Per le **immagini esistenti**, esegui gli script una volta
- Dopo la generazione, **non eliminare** i file originali (servono come fallback)
- I banner ora usano `srcset` nel template, le versioni responsive verranno caricate automaticamente

## Commit da fare

```bash
git add carpi_news/home/signals.py
git add carpi_news/admin_panel/templates/admin_panel/banner_display.html
git add carpi_news/diagnose_responsive_images.py
git add carpi_news/create_responsive_uploaded_images.py
git add carpi_news/generate_all_responsive_production.py
git add FIX_RESPONSIVE_IMAGES_PRODUCTION.md

git commit -m "Fix: risolto problema immagini responsive in produzione

- Migliorato logging signal generate_responsive_images_on_save
- Aggiunto srcset ai banner per caricamento responsive
- Creati script diagnostici e di generazione batch
- Documentazione completa per fix in produzione"

git push
```
