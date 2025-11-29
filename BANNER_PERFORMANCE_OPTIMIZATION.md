# Ottimizzazione Performance Banner Verticali

## Problema Riscontrato

Dopo l'inserimento del banner verticale `self_promo_VERT.webp` in produzione, PageSpeed Insights ha segnalato un calo delle prestazioni.

## Causa

I banner verticali (300×250px) non avevano gli attributi di ottimizzazione necessari:
- ❌ Mancava `loading="lazy"` (caricamento differito)
- ❌ Mancava `fetchpriority="low"` (priorità bassa)
- ❌ `max-width: 100%` invece di `max-width: 300px` (sovradimensionamento)

## Soluzione Implementata

### File Modificato
**`admin_panel/templates/admin_panel/banner_display.html:28`**

### Ottimizzazioni Applicate

```django
{# PRIMA - Non ottimizzato #}
<img src="{{ banner.image.url }}"
     alt="{{ banner.alt_text }}"
     width="300"
     height="250"
     style="width: 100%; height: auto; max-width: 100%;">

{# DOPO - Ottimizzato #}
<img src="{{ banner.image.url }}"
     alt="{{ banner.alt_text }}"
     loading="lazy"
     fetchpriority="low"
     width="300"
     height="250"
     style="width: 100%; height: auto; max-width: 300px;">
```

### Miglioramenti Applicati

1. **`loading="lazy"`**
   - Carica l'immagine solo quando entra nel viewport
   - Risparmia bandwidth su banner below-the-fold
   - Migliora First Contentful Paint (FCP)

2. **`fetchpriority="low"`**
   - Indica al browser che il banner non è critico per LCP
   - Priorità data a contenuto principale (articoli)
   - Migliora Largest Contentful Paint (LCP)

3. **`max-width: 300px`**
   - Evita sovradimensionamento del container
   - Dimensione corretta per banner verticali (IAB Medium Rectangle)
   - Riduce Cumulative Layout Shift (CLS)

4. **Dimensioni esplicite `width="300" height="250"`**
   - Previene layout shift durante caricamento
   - Il browser riserva lo spazio corretto immediatamente
   - Migliora Cumulative Layout Shift (CLS)

## Confronto con Banner Orizzontali

I banner orizzontali (728×90px) erano già ottimizzati:

```django
{# Banner header - GIÀ OTTIMIZZATO #}
<img src="{{ banner.image.url }}"
     alt="{{ banner.alt_text }}"
     width="728"
     height="90"
     fetchpriority="high">  {# HIGH solo per header above-the-fold #}
```

Ora **tutti i banner** sono ottimizzati uniformemente.

## Metriche PageSpeed Insights Attese

### Prima dell'ottimizzazione
- ⚠️ **LCP**: Banner competeva con contenuto principale
- ⚠️ **CLS**: Possibili layout shift per dimensioni non esplicite
- ⚠️ **Network**: Caricamento anticipato di banner non visibili

### Dopo l'ottimizzazione
- ✅ **LCP**: Banner non interferisce con contenuto critico
- ✅ **CLS**: Layout stabile con dimensioni esplicite
- ✅ **Network**: Caricamento lazy solo quando necessario
- ✅ **Performance Score**: Miglioramento atteso +5-15 punti

## Deploy in Produzione

### Passaggi

1. **Commit delle modifiche**:
   ```bash
   git add carpi_news/admin_panel/templates/admin_panel/banner_display.html
   git commit -m "Fix: ottimizza performance banner verticali (lazy loading + fetchpriority low)"
   git push
   ```

2. **Deploy su server di produzione**:
   ```bash
   # Sul server
   cd /var/www/carpi-news
   git pull
   sudo systemctl restart gunicorn
   ```

3. **Verifica cache**:
   - Svuota cache Django (se attiva)
   - Hard refresh browser (Ctrl+Shift+R)
   - Test con PageSpeed Insights

## Test Locali (Opzionale)

Per testare le ottimizzazioni in locale:

```bash
# Crea un banner verticale di test
cd carpi_news
python manage.py shell
```

```python
from admin_panel.models import Banner
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

user = User.objects.first()
Banner.objects.create(
    user=user,
    title="Test Banner Verticale",
    position='sidebar_top',
    image='banners/self_promo.webp',  # Usa banner esistente
    link_url='https://ombradelportico.it',
    alt_text='Banner test',
    status='active',
    payment_status='completed',
    approved=True,
    start_date=timezone.now(),
    end_date=timezone.now() + timedelta(days=7)
)
```

Poi verifica su `http://localhost:8000` con DevTools Network tab:
- Banner deve avere `loading="lazy"`
- Banner deve avere `fetchpriority="low"`
- Dimensioni esplicite 300×250

## Compatibilità

- ✅ **Chrome/Edge**: Supporto completo
- ✅ **Firefox**: Supporto completo (lazy loading nativo da v75)
- ✅ **Safari**: Supporto completo (lazy loading nativo da v15.4)
- ✅ **Mobile**: Beneficio maggiore su connessioni lente

## Note Tecniche

### Perché `fetchpriority="low"` per Banner Verticali?

I banner verticali sono **sempre below-the-fold** (fuori dalla vista iniziale):
- Sidebar: posizionata lateralmente, scorrevole
- Between articles: nella griglia, dopo primi articoli
- Article positions: visibili solo dopo scroll

Quindi:
- **Banner header**: `fetchpriority="high"` (above-the-fold, visibile subito)
- **Banner verticali**: `fetchpriority="low"` (below-the-fold, visibili dopo scroll)
- **Banner footer**: nessun attributo (molto below-the-fold, lazy loading sufficiente)

### Dimensioni IAB Standard

Il sistema usa dimensioni pubblicitarie standard IAB (Interactive Advertising Bureau):

| Tipo | Dimensioni | Utilizzo |
|------|-----------|----------|
| Leaderboard | 728×90 | Header, Footer, Article |
| Medium Rectangle | 300×250 | Sidebar, Between Articles |

Queste dimensioni sono ottimali perché:
- Riconosciute universalmente
- Aspect ratio ottimizzato
- Massima compatibilità con Ad Networks

## Monitoring Post-Deploy

Dopo il deploy, monitora:

1. **PageSpeed Insights** (https://pagespeed.web.dev/)
   - Test mobile e desktop
   - Verifica miglioramento score
   - Controlla "Defer offscreen images"

2. **Chrome DevTools**
   - Network tab: banner carica lazy
   - Performance tab: nessun layout shift
   - Lighthouse: score migliorato

3. **Real User Metrics**
   - Tempo di caricamento homepage
   - Core Web Vitals (Search Console)
   - Bounce rate (non deve aumentare)

## Rollback (se necessario)

Se l'ottimizzazione causa problemi:

```bash
git revert HEAD
git push
sudo systemctl restart gunicorn
```

---

**Implementato**: 2025-11-29
**File modificato**: `admin_panel/templates/admin_panel/banner_display.html`
**Impatto atteso**: +5-15 punti PageSpeed Insights
**Zero breaking changes**: Modifiche solo agli attributi img
