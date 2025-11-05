# Integrazione Banner nel Sito

## Sistema Database-Driven

I banner pubblicitari sono completamente gestiti tramite **database** utilizzando il modello `Banner` in `admin_panel/models.py`.

## Come Funziona

### 1. Modello Database

```python
# admin_panel/models.py
class Banner(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to='banners/')
    link_url = models.URLField()
    position = models.CharField(max_length=50, choices=POSITION_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    payment_status = models.CharField(max_length=20)
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    # ... altri campi
```

### 2. Template Tag per Visualizzazione

Il template tag `{% show_banner 'posizione' %}` carica automaticamente:
- Banner attivi dal database
- Filtra per posizione
- Ordina per priorità
- Traccia le impressioni

```python
# admin_panel/templatetags/banner_tags.py
@register.inclusion_tag('admin_panel/banner_display.html')
def show_banner(position):
    banners = Banner.objects.filter(
        position=position,
        status='active',
        payment_status='completed',
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    ).order_by('-priority', '?')[:1]

    banner = banners.first()
    if banner:
        banner.impressions += 1
        banner.save(update_fields=['impressions'])

    return {'banner': banner}
```

### 3. Tracking Click

I click vengono tracciati attraverso URL di redirect:

```python
# admin_panel/views.py
def banner_click(request, banner_id):
    banner = get_object_or_404(Banner, id=banner_id)
    banner.clicks += 1
    banner.save(update_fields=['clicks'])
    return redirect(banner.link_url)
```

## Posizioni Banner Integrate

### Homepage (`home/templates/homepage.html`)

```django
{% load banner_tags %}

<!-- Banner sotto l'header -->
{% show_banner 'header' %}

<!-- Banner tra gli articoli (dopo il 3°) -->
{% if forloop.counter == 3 %}
    <div style="grid-column: 1 / -1;">
        {% show_banner 'between_articles' %}
    </div>
{% endif %}
```

### Pagina Articolo (`home/templates/dettaglio_articolo.html`)

```django
{% load banner_tags %}

<!-- Banner inizio articolo -->
{% show_banner 'article_top' %}

<!-- Contenuto articolo -->
{{ articolo.contenuto|safe }}

<!-- Banner fine articolo -->
{% show_banner 'article_bottom' %}
```

## Posizioni Disponibili

| Codice | Descrizione | Dove appare |
|--------|-------------|-------------|
| `header` | Header | Sotto il logo homepage |
| `sidebar_top` | Sidebar Alto | Parte superiore sidebar |
| `sidebar_middle` | Sidebar Centro | Centro sidebar |
| `sidebar_bottom` | Sidebar Basso | Fondo sidebar |
| `between_articles` | Tra articoli | Homepage dopo 3° articolo |
| `article_top` | Inizio articolo | Prima dell'immagine |
| `article_middle` | Centro articolo | Nel mezzo del testo |
| `article_bottom` | Fine articolo | Dopo il contenuto |
| `footer` | Footer | Nel footer del sito |

## Aggiungere Nuove Posizioni

### 1. Aggiorna il Modello

```python
# admin_panel/models.py
POSITION_CHOICES = [
    # ... posizioni esistenti
    ('sidebar_custom', 'Sidebar Personalizzata'),
]
```

### 2. Crea Migration

```bash
python manage.py makemigrations admin_panel
python manage.py migrate admin_panel
```

### 3. Usa nel Template

```django
{% load banner_tags %}
{% show_banner 'sidebar_custom' %}
```

## Statistiche in Tempo Reale

Ogni volta che un banner viene visualizzato o cliccato, i contatori vengono aggiornati automaticamente nel database:

- **Impressioni**: Incrementate quando `{% show_banner %}` viene renderizzato
- **Click**: Incrementati quando l'utente clicca sul banner
- **CTR**: Calcolato automaticamente come `(clicks / impressions) * 100`

## Gestione Utente

Gli utenti possono:

1. **Creare banner**: `/panel/banners/create/`
2. **Scegliere posizione**: Dropdown con tutte le opzioni
3. **Pagare**: Sistema di pagamento (simulato in dev)
4. **Monitorare**: Vedere statistiche in tempo reale
5. **Gestire**: Modificare, eliminare, rinnovare

## Gestione Admin

Gli amministratori possono:

1. **Approvare/Rifiutare**: Banner in moderazione
2. **Attivare/Disattivare**: Controllo manuale
3. **Vedere statistiche**: Per tutti i banner
4. **Filtrare**: Per stato, posizione, utente

## Vantaggi Sistema Database

✅ **Dinamico**: Nessun hardcoding, tutto configurabile
✅ **Scalabile**: Gestione di migliaia di banner
✅ **Tracking**: Statistiche dettagliate automatiche
✅ **User-Friendly**: Interfaccia web per gestione
✅ **Monetizzazione**: Sistema di pagamento integrato
✅ **Flessibile**: Facile aggiungere nuove posizioni
✅ **Performante**: Query ottimizzate, caching possibile

## Query Database Esempi

```python
# Ottieni banner attivi per una posizione
active_banners = Banner.objects.filter(
    position='header',
    status='active',
    payment_status='completed',
    end_date__gte=timezone.now()
).order_by('-priority')

# Banner più cliccati
top_banners = Banner.objects.filter(
    status='active'
).order_by('-clicks')[:10]

# CTR medio per posizione
from django.db.models import Avg, F
avg_ctr = Banner.objects.filter(
    impressions__gt=0
).annotate(
    ctr=F('clicks') * 100.0 / F('impressions')
).aggregate(Avg('ctr'))

# Revenue per utente
from django.db.models import Sum
user_revenue = Banner.objects.filter(
    payment_status='completed'
).values('user__username').annotate(
    total=Sum('total_price')
).order_by('-total')
```

## Ottimizzazioni Future

- [ ] **Caching**: Redis per banner ad alte visite
- [ ] **CDN**: Servire immagini da CDN
- [ ] **A/B Testing**: Rotazione intelligente banner
- [ ] **Geotargeting**: Banner per località
- [ ] **Scheduling**: Attivazione programmata
- [ ] **Analytics Dashboard**: Grafici dettagliati
- [ ] **API REST**: Gestione programmatica
- [ ] **Bulk Upload**: Caricamento multiplo

## Sicurezza

✅ Solo utenti autenticati possono creare banner
✅ Ogni utente vede solo i propri banner
✅ Moderazione admin prima dell'attivazione (opzionale)
✅ Validazione upload immagini
✅ Sanitizzazione URL
✅ CSRF protection

## Backup e Restore

```bash
# Backup banner
python manage.py dumpdata admin_panel.Banner > banners_backup.json

# Restore banner
python manage.py loaddata banners_backup.json
```
