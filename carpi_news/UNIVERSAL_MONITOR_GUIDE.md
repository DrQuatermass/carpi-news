# Guida al Sistema di Monitoraggio Universale - Ombra del Portico

## Panoramica

Il nuovo sistema di monitoraggio universale sostituisce i singoli monitor con un'architettura modulare e configurabile che supporta diversi tipi di siti web:

- **HTML Scraping**: Per siti web standard
- **WordPress API**: Per siti WordPress
- **YouTube API**: Per playlist YouTube

## Vantaggi del Nuovo Sistema

✅ **Un'unica classe universale** invece di tanti monitor separati  
✅ **Configurazioni centralizzate** in `monitor_configs.py`  
✅ **File lock integrato** per evitare esecuzioni multiple  
✅ **Gestione immagini migliorata** con strategie multiple  
✅ **Logging dettagliato** e gestione errori  
✅ **Manager centralizzato** per controllare tutti i monitor  

## File Principali

| File | Descrizione |
|------|-------------|
| `universal_news_monitor.py` | Classe base e scraper specifici |
| `monitor_configs.py` | Configurazioni per ogni sito |
| `monitor_manager.py` | Gestione multipli monitor |
| `start_universal_monitors.py` | Script di avvio principale |
| `migrate_to_universal.py` | Script di migrazione/test |

## Configurazioni Disponibili

### Carpi Calcio (HTML Scraping)
```python
CARPI_CALCIO_CONFIG = SiteConfig(
    name="Carpi Calcio",
    base_url="https://www.carpicalcio.it/",
    scraper_type="html",
    category="Sport",
    use_ai_generation=True,  # Rielabora con AI
    # ... selettori CSS personalizzati
)
```

### Comune Carpi (WordPress API)
```python
COMUNE_CARPI_CONFIG = SiteConfig(
    name="Comune Carpi", 
    base_url="https://www.comune.carpi.mo.it/",
    scraper_type="wordpress_api",
    category="Comunicazioni",
    use_ai_generation=True,  # Rielabora con AI
    per_page=10
)
```

## Come Usare

### 1. Avvio Rapido
```bash
cd C:\news\carpi_news
python start_universal_monitors.py
```

### 2. Uso Programmatico
```python
from home.monitor_manager import MonitorManager

# Crea manager
manager = MonitorManager()

# Aggiungi monitor
manager.add_monitor('carpi_calcio', check_interval=900)
manager.add_monitor('comune_carpi', check_interval=1200)

# Avvia tutto
manager.start_all_monitors()

# Mostra stato
manager.print_status()
```

### 3. Configurazione Personalizzata
```python
from home.universal_news_monitor import SiteConfig
from home.monitor_manager import MonitorManager

# Crea configurazione custom
custom_config = SiteConfig(
    name="Nuovo Sito",
    base_url="https://example.com/",
    scraper_type="html",
    category="Generale",
    news_url="https://example.com/news/",
    selectors=['.news-item', '.article'],
    use_ai_generation=False  # Salva diretto senza AI
)

# Aggiungi al manager
manager = MonitorManager()
manager.add_custom_monitor(custom_config, check_interval=600)
manager.start_monitor('nuovo_sito')
```

## Tipi di Scraper

### HTML Scraper
Per siti web standard che richiedono parsing HTML:
- Usa selettori CSS configurabili
- Estrazione automatica di titolo, contenuto, immagini
- Fallback su selettori generici se quelli specifici falliscono
- Filtri per dimensioni immagini e contenuti generici

### WordPress API Scraper  
Per siti WordPress con API REST attiva:
- Accesso diretto ai post via `/wp-json/wp/v2/posts`
- Supporto featured media tramite `/wp-json/wp/v2/media/{id}`
- Ricerca immagini nel contenuto come fallback
- Contenuto già pulito da HTML

### YouTube API Scraper
Per playlist YouTube (richiede API key):
- Accesso alla YouTube Data API v3
- Estrazione automatica thumbnail
- Integrazione con sistema di transcript esistente

## File Lock e Sicurezza

Il sistema include file lock automatici per prevenire esecuzioni multiple:

- **Windows**: Usa `msvcrt.locking()`
- **Unix/Linux**: Usa `fcntl.lockf()`
- **File lock**: `%TEMP%\{site_name}_monitor.lock`
- **PID tracking**: Il lock contiene il PID del processo

## Migrazione dai Vecchi Monitor

### Test di Compatibilità
```bash
python home/migrate_to_universal.py
```

Questo script:
1. Confronta risultati vecchio vs nuovo sistema
2. Testa tutti i monitor configurati  
3. Crea lo script di avvio
4. Verifica compatibilità

### Sostituzioni
| Vecchio Monitor | Nuovo Sistema |
|----------------|---------------|
| `ComuneNotizieMonitor` | `UniversalNewsMonitor` con `comune_carpi` config |
| `CarpiCalcioMonitor` | `UniversalNewsMonitor` con `carpi_calcio` config |
| `YouTubePlaylistMonitor` | `UniversalNewsMonitor` con `youtube_playlist` config |

## Logging

Il sistema produce log dettagliati:

```
2025-09-01 09:00:00 - home.universal_news_monitor - INFO - Lock acquisito per Carpi Calcio
2025-09-01 09:00:01 - home.universal_news_monitor - INFO - Trovati 12 articoli per Carpi Calcio
2025-09-01 09:00:01 - home.universal_news_monitor - INFO - Articoli con immagini: 8, senza immagini: 4
```

## Gestione Errori

- **Lock non acquisibile**: Un'altra istanza è già in esecuzione
- **Errori di rete**: Retry automatico dopo 1 minuto
- **Errori di parsing**: Skip dell'articolo, continua con il prossimo
- **Errori AI**: Fallback a salvataggio diretto senza elaborazione

## Estensibilità

### Aggiungere un Nuovo Tipo di Scraper
1. Crea classe che eredita da `BaseScraper`
2. Implementa `scrape_articles()` e `get_full_content()`
3. Aggiungi alla factory in `UniversalNewsMonitor._create_scraper()`

### Aggiungere una Nuova Configurazione
1. Crea `SiteConfig` in `monitor_configs.py`
2. Aggiungi a `MONITOR_CONFIGS` dictionary
3. Testa con `MonitorManager.add_monitor()`

## Status e Debugging

```python
# Controlla stato di tutti i monitor
manager.print_status()

# Output:
# === STATO MONITOR ===
# CARPI_CALCIO:
#   Nome: Carpi Calcio
#   Tipo: html
#   Categoria: Sport  
#   Stato: [ATTIVO]
#   Intervallo: 900s
#   Articoli visti: 45
```

## Confronto Prestazioni

| Metrica | Vecchio Sistema | Nuovo Sistema |
|---------|----------------|---------------|
| **File Monitor** | 3 file separati | 1 sistema universale |
| **Configurazione** | Hardcoded in classi | Centralizzata in config |
| **File Lock** | Solo Comune monitor | Tutti i monitor |
| **Gestione Errori** | Base | Avanzata con retry |
| **Estensibilità** | Nuova classe per ogni sito | Nuova config per ogni sito |
| **Manutenzione** | Alta (codice duplicato) | Bassa (logica condivisa) |

## Prossimi Passi

1. ✅ Testare il nuovo sistema con `migrate_to_universal.py`
2. ⏳ Avviare il nuovo sistema con `start_universal_monitors.py`  
3. ⏳ Monitorare log per una settimana
4. ⏳ Rimuovere i vecchi file monitor quando tutto è stabile

## Supporto

Per problemi o domande:
1. Controlla i log in `monitor.log`
2. Verifica che non ci siano file lock rimasti in `%TEMP%`
3. Testa la configurazione specifica con il manager