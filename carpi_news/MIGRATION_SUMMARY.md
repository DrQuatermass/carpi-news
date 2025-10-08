# Migrazione al Sistema Monitor Database-Driven

## ✅ Completato

Il sistema di monitoraggio è stato completamente migrato da un approccio basato su file Python (`monitor_configs.py`) a un sistema completamente gestito tramite database Django.

## 🎯 Cosa è cambiato

### Prima (Sistema Legacy)
```python
# monitor_configs.py
CARPI_CALCIO_CONFIG = SiteConfig(
    name="Carpi Calcio",
    base_url="https://www.carpicalcio.it/",
    scraper_type="html",
    # ... configurazioni hardcoded
)

# apps.py
from home.monitor_configs import get_config
config = get_config('carpi_calcio')
```

### Ora (Sistema Database-Driven)
```python
# Database
MonitorConfig.objects.create(
    name="Carpi Calcio",
    base_url="https://www.carpicalcio.it/",
    scraper_type="html",
    is_active=True,
    # ... configurazioni in database
)

# apps.py
active_monitors = MonitorConfig.objects.filter(is_active=True)
for monitor in active_monitors:
    config = monitor.to_site_config()
```

## 📋 File Modificati

### Nuovi File
1. **`home/models.py`** - Aggiunto `MonitorConfig` model (linea 109)
2. **`home/admin.py`** - Aggiunto `MonitorConfigAdmin` con controlli (linea 355)
3. **`home/management/commands/import_monitors.py`** - Comando per importare monitor
4. **`home/management/commands/start_monitors.py`** - Comando per avviare monitor dal DB
5. **`home/management/commands/manage_db_monitors.py`** - Comando per gestire monitor
6. **`MONITOR_DB_SYSTEM.md`** - Documentazione completa del nuovo sistema
7. **`home/migrations/0018_monitorconfig.py`** - Migrazione database

### File Modificati
1. **`home/apps.py`** - `start_universal_monitors_improved()` ora carica dal DB
2. **`home/monitor_manager.py`** - Aggiunto `add_monitor_from_config()`
3. **`CLAUDE.md`** - Aggiornata documentazione

### File Deprecati (ma ancora presenti)
- `monitor_configs.py` - Usato solo per import iniziale
- `start_universal_monitors.py` - Sostituito da comando Django

## 🚀 Come Usare il Nuovo Sistema

### 1. Prima Configurazione (solo una volta)
```bash
# Importa tutti i monitor esistenti nel database
python manage.py import_monitors

# Verifica importazione
python manage.py manage_db_monitors status
```

### 2. Gestione via Admin
```bash
# Avvia Django
python manage.py runserver

# Vai su http://localhost:8000/admin/home/monitorconfig/
# - Visualizza tutti i monitor
# - Start/Stop individuali
# - Test monitor
# - View logs
# - Crea nuovi monitor
```

### 3. Gestione via CLI
```bash
# Visualizza stato
python manage.py manage_db_monitors status

# Avvia tutti i monitor attivi
python manage.py start_monitors

# Avvia monitor specifico
python manage.py start_monitors --monitor "Carpi Calcio"

# Gestione rapida
python manage.py manage_db_monitors start    # Avvia tutti
python manage.py manage_db_monitors stop     # Ferma tutti
python manage.py manage_db_monitors restart  # Riavvia tutti
```

### 4. Aggiungere Nuovo Monitor

**Via Admin (Raccomandato):**
1. Vai su `/admin/home/monitorconfig/add/`
2. Compila:
   - Nome, URL base, Tipo scraper
   - Categoria
   - Attiva checkbox `is_active`
   - Configura AI se necessario
   - Aggiungi `config_data` in JSON:
   ```json
   {
     "interval": 600,
     "news_url": "https://example.com/news/",
     "selectors": [".article", ".news"]
   }
   ```
3. Salva
4. Clicca "▶ Start Monitor"

**Via Shell:**
```python
from home.models import MonitorConfig

MonitorConfig.objects.create(
    name="Nuovo Sito",
    base_url="https://example.com/",
    scraper_type="html",
    category="Attualità",
    is_active=True,
    use_ai_generation=True,
    enable_web_search=True,
    ai_system_prompt="Sei un giornalista...",
    config_data={
        "interval": 600,
        "news_url": "https://example.com/news/",
        "selectors": [".article"]
    }
)
```

## 📊 Monitor Attualmente Importati

17 monitor attivi nel database:
- ANSA Emilia-Romagna (html, 300s)
- Carpi Calcio (html, 300s)
- Comune Campogalliano (graphql, 900s)
- Comune Carpi (wordpress_api, 600s)
- Comune Carpi GraphQL (graphql, 600s)
- Comune Novi di Modena (graphql, 900s)
- Comune Soliera (graphql, 900s)
- Email Comunicati Stampa (email, 300s)
- Eventi Carpi GraphQL (graphql, 1800s)
- La Voce di Carpi (html, 600s)
- La Voce di Carpi Sport (html, 600s)
- Questura di Modena (html, 600s)
- TempoNews (html, 600s)
- Terre d'Argine (wordpress_api, 900s)
- YouTube Carpi (youtube_api, 1800s)
- YouTube Carpi 2 (youtube_api, 1800s)

(Sito Generico disattivato - era solo esempio)

## 🔧 Dettagli Tecnici

### Modello MonitorConfig
```python
class MonitorConfig(models.Model):
    # Base
    name = models.CharField(max_length=200, unique=True)
    base_url = models.URLField(max_length=500)
    scraper_type = models.CharField(max_length=20, choices=SCRAPER_TYPES)
    category = models.CharField(max_length=100, default='Generale')

    # Controllo
    is_active = models.BooleanField(default=True)
    auto_approve = models.BooleanField(default=False)

    # AI
    use_ai_generation = models.BooleanField(default=False)
    enable_web_search = models.BooleanField(default=False)
    ai_system_prompt = models.TextField(blank=True)

    # Config specifiche (JSON)
    config_data = models.JSONField(default=dict, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run = models.DateTimeField(null=True, blank=True)

    def to_site_config(self):
        """Converte in SiteConfig per compatibility"""
        # ...
```

### Admin Interface
```python
@admin.register(MonitorConfig)
class MonitorConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'scraper_type', 'category',
                   'status_indicator', 'last_run', 'control_buttons')

    # Pulsanti personalizzati
    def control_buttons(self, obj):
        # Start/Stop, Test, View Logs
        # ...
```

### Auto-Start (apps.py)
```python
def start_universal_monitors_improved(self):
    # Carica monitor attivi dal DB
    active_monitors = MonitorConfig.objects.filter(is_active=True)

    # Avvia automaticamente
    for monitor in active_monitors:
        site_config = monitor.to_site_config()
        interval = monitor.config_data.get('interval', 600)
        manager.add_monitor_from_config(site_config, interval)

    manager.start_all_monitors()
```

## ✨ Vantaggi del Nuovo Sistema

1. **Nessuna modifica al codice**: Aggiungi/modifica monitor via admin
2. **Controllo granulare**: Start/Stop individuale
3. **Testing facilitato**: Testa prima di attivare
4. **Logging integrato**: View logs direttamente dall'admin
5. **Hot reload**: Riavvia singoli monitor senza fermare tutto
6. **Backup semplice**: Esporta configurazioni dal database
7. **Multi-utente**: Più admin possono gestire monitor
8. **Audit trail**: Traccia modifiche con `created_at`/`updated_at`

## 🔄 Workflow Produzione

### Aggiungere Nuovo Monitor
1. Admin crea monitor su `/admin/home/monitorconfig/add/`
2. Salva con `is_active=False`
3. Usa "🧪 Test Monitor" per verificare
4. Se OK, attiva con checkbox `is_active=True`
5. Usa "▶ Start Monitor" o aspetta auto-start al prossimo riavvio Django

### Modificare Monitor Esistente
1. Admin apre monitor su `/admin/home/monitorconfig/{id}/`
2. Modifica configurazione
3. Salva
4. Usa "Restart Monitor" se necessario

### Deployment
```bash
# Su server produzione
git pull
python manage.py migrate  # Applica migrazione se prima volta
python manage.py collectstatic --noinput

# Monitor si auto-avviano con Django
systemctl restart gunicorn
# oppure
supervisorctl restart carpi_news
```

## 📚 Documentazione Completa

Vedi **`MONITOR_DB_SYSTEM.md`** per:
- Guida completa all'uso
- Esempi di configurazione per ogni tipo scraper
- Troubleshooting
- Best practices
- API reference

## ⚠️ Note Importanti

1. **Monitor configs.py**: Ancora presente per riferimento, ma NON più utilizzato dal sistema
2. **Lock files**: Il sistema usa ancora lock files in `locks/` per prevenire duplicati
3. **API Keys**: Salvate in `config_data` JSON - considera encryption per produzione
4. **Backup**: Fai backup del database prima di modifiche massive
5. **Intervalli**: Rispetta rate limits dei siti (minimo raccomandato 300s)

## 🎉 Conclusione

Il sistema è ora completamente migrato e funzionante. Tutti i 17 monitor sono stati importati con successo e possono essere gestiti via admin interface o CLI.

**Prossimi passi suggeriti:**
- [ ] Rimuovere `monitor_configs.py` (opzionale, dopo conferma che tutto funziona)
- [ ] Implementare encryption per API keys in `config_data`
- [ ] Creare dashboard con statistiche monitor
- [ ] Aggiungere webhook notifications
