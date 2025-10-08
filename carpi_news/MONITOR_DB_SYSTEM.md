# Sistema Monitor Basato su Database

Il sistema di monitoraggio è ora completamente gestito tramite database Django, permettendo la configurazione e gestione dinamica dei monitor senza modificare il codice.

## 🎯 Vantaggi

- ✅ **Gestione via Admin**: Configura, attiva/disattiva monitor dall'interfaccia admin
- ✅ **Nessuna modifica al codice**: Aggiungi o modifica monitor senza toccare `monitor_configs.py`
- ✅ **Controllo granulare**: Start/Stop individuale per ogni monitor
- ✅ **Test facilitati**: Testa monitor singolarmente prima di attivarli
- ✅ **Log centralizzati**: Visualizza i log di ogni monitor dall'admin

## 📊 Modello Database

### MonitorConfig (`home/models.py`)

Campi principali:
- `name`: Nome identificativo del monitor (unique)
- `base_url`: URL base del sito
- `scraper_type`: Tipo di scraper (html, wordpress_api, youtube_api, graphql, email)
- `category`: Categoria articoli
- `is_active`: Monitor attivo/disattivo
- `auto_approve`: Approva automaticamente articoli
- `use_ai_generation`: Usa AI per generare contenuto
- `enable_web_search`: Abilita ricerca web durante AI generation
- `ai_system_prompt`: Prompt personalizzato per l'AI
- `config_data`: JSON con configurazioni specifiche (selectors, API keys, intervalli, etc.)
- `last_run`: Timestamp ultima esecuzione

## 🚀 Comandi Disponibili

### 1. Importare Monitor Esistenti

Importa tutti i monitor da `monitor_configs.py` nel database (solo la prima volta):

```bash
python manage.py import_monitors
```

Opzioni:
- `--update`: Aggiorna monitor esistenti invece di saltarli
- `--delete-existing`: Elimina e ricrea tutti i monitor

### 2. Avviare Monitor

Avvia tutti i monitor attivi dal database:

```bash
python manage.py start_monitors
```

Opzioni:
- `--monitor "Nome Monitor"`: Avvia solo un monitor specifico
- `--daemon`: Esegui in modalità daemon (continua in esecuzione)

### 3. Gestire Monitor

Gestisci lo stato dei monitor:

```bash
# Visualizza stato
python manage.py manage_db_monitors status

# Visualizza stato di un monitor specifico
python manage.py manage_db_monitors status --monitor "Nome Monitor"

# Avvia tutti i monitor attivi
python manage.py manage_db_monitors start

# Ferma tutti i monitor
python manage.py manage_db_monitors stop

# Riavvia tutti i monitor
python manage.py manage_db_monitors restart
```

## 🎛️ Interfaccia Admin

### Accesso

1. Vai su `/admin/`
2. Cerca **"Configurazioni Monitor"** nella sezione Home

### Funzionalità

**Lista Monitor:**
- Indicatori di stato colorati (Attivo/Disattivo)
- Filtri per tipo, categoria, stato, AI generation
- Ricerca per nome e URL
- Colonna con pulsanti di controllo

**Pulsanti di Controllo:**
- **▶ Start/⏸ Stop**: Attiva/disattiva il monitor
- **🧪 Test**: Testa il monitor senza salvare articoli
- **📋 View Logs**: Visualizza gli ultimi 50 log del monitor

**Form di Editing:**
- Sezioni organizzate (Base, AI, Configurazioni Avanzate)
- Campo JSON per configurazioni specifiche del monitor
- Help text per ogni campo

## 📝 Configurazione Monitor

### Struttura config_data (JSON)

Il campo `config_data` contiene tutte le configurazioni specifiche del monitor:

```json
{
  "interval": 300,  // Intervallo in secondi

  // HTML Scraping
  "news_url": "https://example.com/news/",
  "rss_url": "https://example.com/feed/",
  "disable_rss": true,
  "selectors": [".news", ".article"],
  "content_selectors": [".content", "article"],
  "image_selectors": ["img.featured"],
  "content_filter_keywords": ["Carpi"],

  // WordPress API
  "api_url": "https://example.com/wp-json/wp/v2/posts",
  "per_page": 10,

  // YouTube API
  "api_key": "YOUR_API_KEY",
  "playlist_id": "PLxxxxxx",
  "max_results": 5,
  "transcript_delay": 60,

  // GraphQL
  "graphql_endpoint": "https://api.example.com/graphql",
  "graphql_headers": {...},
  "graphql_query": "query {...}",
  "graphql_variables": {...},
  "fallback_to_wordpress": true,
  "download_images": true,

  // Email
  "imap_server": "imap.example.com",
  "imap_port": 993,
  "email": "user@example.com",
  "password": "password",
  "mailbox": "INBOX"
}
```

## 🔄 Workflow Tipico

### 1. Prima Configurazione

```bash
# Importa monitor esistenti da monitor_configs.py
python manage.py import_monitors

# Verifica stato
python manage.py manage_db_monitors status

# Avvia tutti i monitor
python manage.py start_monitors
```

### 2. Aggiungere Nuovo Monitor

**Via Admin:**
1. Vai su `/admin/home/monitorconfig/add/`
2. Compila i campi:
   - Nome, URL, Tipo scraper, Categoria
   - Attiva/disattiva
   - Configura AI se necessario
   - Aggiungi config_data in JSON
3. Salva
4. Usa il pulsante "Start Monitor"

**Via Shell:**
```python
from home.models import MonitorConfig

monitor = MonitorConfig.objects.create(
    name="Nuovo Monitor",
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

### 3. Modificare Monitor Esistente

**Via Admin:**
1. Vai su `/admin/home/monitorconfig/`
2. Clicca sul monitor da modificare
3. Modifica i campi necessari
4. Salva
5. Usa "Restart Monitor" se era già attivo

### 4. Test Monitor

Prima di attivare un nuovo monitor, testalo:

1. Dall'admin, clicca sul monitor
2. Clicca "🧪 Test Monitor"
3. Controlla i log in `/admin/home/monitorconfig/{id}/logs/`
4. Se il test è OK, attiva con "▶ Start Monitor"

## 🔧 Integrazione con Sistema Esistente

### Avvio Automatico (apps.py)

Il sistema si avvia automaticamente quando Django parte:

```python
# home/apps.py
def start_universal_monitors_improved(self):
    # Carica monitor attivi dal database
    active_monitors = MonitorConfig.objects.filter(is_active=True)

    # Crea manager e avvia
    manager = MonitorManager()
    for monitor_config in active_monitors:
        site_config = monitor_config.to_site_config()
        interval = monitor_config.config_data.get('interval', 600)
        manager.add_monitor_from_config(site_config, interval)

    manager.start_all_monitors()
```

### Conversione a SiteConfig

Il metodo `to_site_config()` converte il modello DB in oggetto SiteConfig:

```python
# home/models.py
def to_site_config(self):
    config_dict = {
        'name': self.name,
        'base_url': self.base_url,
        'scraper_type': self.scraper_type,
        'category': self.category,
        'auto_approve': self.auto_approve,
        'use_ai_generation': self.use_ai_generation,
        'enable_web_search': self.enable_web_search,
        'ai_system_prompt': self.ai_system_prompt,
        'ai_api_key': settings.ANTHROPIC_API_KEY
    }
    config_dict.update(self.config_data)
    return SiteConfig(**config_dict)
```

## 📦 File Obsoleti (Non più necessari)

Questi file possono essere conservati per riferimento ma non sono più usati:

- ~~`monitor_configs.py`~~ - Sostituito da database
- ~~`start_universal_monitors.py`~~ - Usa `python manage.py start_monitors`
- ~~`migrate_to_universal.py`~~ - Non più necessario

## ⚠️ Note Importanti

1. **Backup Database**: Prima di eliminare monitor, fai backup
2. **API Keys**: Le API keys sono salvate in `config_data`, considera l'encryption per produzione
3. **Intervalli**: Intervalli troppo brevi possono causare rate limiting
4. **Lock Files**: Il sistema usa lock files per prevenire esecuzioni multiple
5. **Log Rotation**: I log sono ruotati automaticamente (vedi `logger_config.py`)

## 🐛 Troubleshooting

### Monitor non si avvia

1. Controlla stato: `python manage.py manage_db_monitors status --monitor "Nome"`
2. Verifica config_data: Apri admin e controlla JSON
3. Testa: Usa pulsante "🧪 Test Monitor"
4. Controlla log: Usa pulsante "📋 View Logs"

### Errori nel config_data

```python
# Valida JSON prima di salvare
import json
config_data = {...}
json.dumps(config_data)  # Solleva errore se non valido
```

### Monitor duplicati

```bash
# Verifica duplicati
python manage.py shell
>>> from home.models import MonitorConfig
>>> MonitorConfig.objects.values('name').annotate(count=Count('id')).filter(count__gt=1)
```

## 🚀 Prossimi Passi

1. **Encryption API Keys**: Implementa encryption per password/API keys in `config_data`
2. **Webhook Integration**: Aggiungi notifiche webhook per eventi monitor
3. **Dashboard**: Crea dashboard con statistiche e grafici
4. **Scheduling Avanzato**: Aggiungi scheduling basato su cron expressions
5. **Health Checks**: Implementa health check automatici per ogni monitor
