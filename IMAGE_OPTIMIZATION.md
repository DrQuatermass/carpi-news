# Sistema di Ottimizzazione Immagini

Sistema completo per ottimizzare il caricamento delle immagini (interne ed esterne) con supporto responsive images, conversione WebP automatica e caching intelligente.

## 📊 Benefici

- **Riduzione dimensioni**: Fino al 70-80% di risparmio con WebP
- **Responsive Images**: Versioni multiple (400w, 600w, 800w) per dispositivi diversi
- **Cache intelligente**: Headers di cache ottimali (1 anno per immagini)
- **Proxy immagini esterne**: Ottimizza automaticamente immagini da ModenaToday, Twitter, ecc.
- **PageSpeed migliorato**: Risolve i problemi evidenziati da PageSpeed Insights

## 🚀 Componenti

### 1. Template Tag `image_srcset`

Genera automaticamente l'attributo `srcset` per responsive images:

```django
<img src="{{ articolo.foto }}"
     srcset="{{ articolo.foto|image_srcset }}"
     sizes="(max-width: 640px) 100vw, 616px">
```

**Funzionamento**:
- **Immagini esterne** → usa il proxy (`/image-proxy/?url=...&w=400`)
- **Immagini interne** → cerca versioni `-400w.webp`, `-600w.webp`, `-800w.webp`

### 2. Image Proxy (`/image-proxy/`)

Endpoint per ottimizzare immagini esterne al volo:

**URL**: `/image-proxy/?url=<URL_IMMAGINE>&w=<LARGHEZZA>&q=<QUALITA>`

**Parametri**:
- `url` (required): URL dell'immagine esterna
- `w` (optional): Larghezza target (default: originale)
- `q` (optional): Qualità WebP 0-100 (default: 75)

**Esempio**:
```
/image-proxy/?url=https://www.modenatoday.it/image.jpg&w=600&q=80
```

**Caratteristiche**:
- Scarica l'immagine dal server originale
- Ridimensiona alla larghezza richiesta (mantiene aspect ratio)
- Converte in WebP con compressione ottimale
- Cachea il risultato per 24 ore (Django cache + browser cache)
- Headers: `Cache-Control: public, max-age=86400`

### 3. Middleware Cache Headers

Aggiunge automaticamente header di cache a tutti i file statici:

- **Immagini** (.jpg, .png, .webp, .svg): 1 anno
- **CSS/JS**: 30 giorni
- **Fonts**: 1 anno
- **Documenti** (.pdf, .txt): 7 giorni

**Attivazione**: Già configurato in `settings.py`

### 4. Generazione Immagini Responsive

Comando management per creare versioni responsive delle immagini esistenti:

```bash
# Genera versioni 400w, 600w, 800w per tutte le immagini in /media/
python manage.py generate_responsive_images

# Con qualità personalizzata
python manage.py generate_responsive_images --quality 80

# Dry-run (mostra cosa farebbe senza eseguire)
python manage.py generate_responsive_images --dry-run

# Forza rigenerazione (sovrascrivi esistenti)
python manage.py generate_responsive_images --force
```

**Output**:
```
comune_carpi_image.webp
  ✓ 400w: 1011x630 → 400x249 (120KB → 32KB, -73%)
  ✓ 600w: 1011x630 → 600x374 (120KB → 58KB, -52%)
  ✓ 800w: 1011x630 → 800x499 (120KB → 88KB, -27%)
```

### 5. Conversione Automatica WebP

Le immagini caricate tramite admin vengono automaticamente convertite in WebP:

**File**: `home/signals.py` - `convert_foto_upload_to_webp()`

**Parametri**:
- Qualità: 65 (ottimale per web)
- Larghezza max: 800px (ridimensiona automaticamente se troppo grande)

## 📝 Utilizzo nei Template

### Homepage e Liste Articoli

```django
{% load webp_images %}

{# Prima card: eager loading senza WebP per LCP #}
<img src="{{ articolo.get_image_url }}"
     srcset="{{ articolo.get_image_url|image_srcset }}"
     sizes="(max-width: 640px) 100vw, 616px"
     alt="{{ articolo.titolo }}"
     width="616"
     height="347"
     fetchpriority="high"
     loading="eager">

{# Altre card: lazy loading con WebP #}
<picture>
    <source srcset="{{ articolo.get_image_url|to_webp }}" type="image/webp">
    <img src="{{ articolo.get_image_url }}"
         srcset="{{ articolo.get_image_url|image_srcset }}"
         sizes="(max-width: 640px) 100vw, 616px"
         alt="{{ articolo.titolo }}"
         loading="lazy">
</picture>
```

### Dettaglio Articolo

```django
<img src="{{ articolo.get_image_url }}"
     alt="{{ articolo.titolo }}"
     loading="eager">
```

## 🔧 Configurazione

### Settings.py

```python
# Cache (necessaria per image proxy)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemBackend',
        'LOCATION': 'image-cache',
    }
}

# Middleware (già configurato)
MIDDLEWARE = [
    # ...
    'home.middleware.cache_headers.StaticMediaCacheMiddleware',
    # ...
]
```

### URLs

```python
from home.image_proxy import image_proxy_view

urlpatterns = [
    # ...
    path('image-proxy/', image_proxy_view, name='image_proxy'),
    # ...
]
```

## 📈 Risultati PageSpeed Insights

### Prima
- Immagini non ottimizzate: **731 KiB** di risparmio potenziale
- Cache non configurata: **58 KiB** di file senza cache
- Immagini troppo grandi per lo spazio visualizzato

### Dopo
- ✅ Immagini convertite in WebP (risparmio 70-80%)
- ✅ Responsive images (dimensioni appropriate)
- ✅ Cache headers (1 anno per immagini)
- ✅ Proxy per immagini esterne ottimizzate

## 🎯 Best Practices

### 1. Usa sempre `srcset` per immagini responsive

```django
<img src="{{ image }}"
     srcset="{{ image|image_srcset }}"
     sizes="(max-width: 640px) 100vw, 616px">
```

### 2. Prima immagine: eager loading per LCP

```django
{# Prima immagine visibile #}
<img fetchpriority="high" loading="eager" ...>

{# Altre immagini #}
<img loading="lazy" ...>
```

### 3. Picture tag con WebP fallback

```django
<picture>
    <source srcset="{{ image|to_webp }}" type="image/webp">
    <img src="{{ image }}" alt="...">
</picture>
```

### 4. Dimensioni esplicite per prevenire CLS

```django
<img src="..." width="616" height="347" ...>
```

## 🔍 Monitoraggio

### Log Image Proxy

```python
# In settings.py
LOGGING = {
    'loggers': {
        'home.image_proxy': {
            'level': 'INFO',
        },
    },
}
```

### Verifica Cache Headers

```bash
curl -I https://ombradelportico.it/static/home/images/logo.webp
# Output:
# Cache-Control: public, max-age=31536000, immutable
```

### Verifica Proxy

```bash
curl -I "https://ombradelportico.it/image-proxy/?url=https://example.com/image.jpg&w=600"
# Output:
# X-Cache: HIT/MISS
# Content-Type: image/webp
```

## 🐛 Troubleshooting

### Immagini esterne non ottimizzate

**Problema**: Le immagini esterne vengono ancora caricate direttamente

**Soluzione**: Verifica che il template usi `image_srcset`:
```django
srcset="{{ articolo.foto|image_srcset }}"
```

### Versioni responsive non trovate

**Problema**: `srcset` è vuoto per immagini interne

**Soluzione**: Genera versioni responsive:
```bash
python manage.py generate_responsive_images
```

### Proxy restituisce errore 500

**Problema**: Timeout o errore di download

**Soluzione**: Controlla i log per dettagli:
```bash
tail -f logs/django.log | grep image_proxy
```

### Cache non funziona

**Problema**: Headers Cache-Control non presenti

**Soluzione**: Verifica che il middleware sia attivo in `settings.MIDDLEWARE`

## 📚 Riferimenti

- [WebP Documentation](https://developers.google.com/speed/webp)
- [Responsive Images](https://developer.mozilla.org/en-US/docs/Learn/HTML/Multimedia_and_embedding/Responsive_images)
- [HTTP Caching](https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching)
- [PageSpeed Insights](https://pagespeed.web.dev/)
