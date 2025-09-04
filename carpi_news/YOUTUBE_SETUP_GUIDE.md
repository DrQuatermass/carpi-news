# Guida Setup YouTube per Consiglio Comunale

## Panoramica

Il sistema ora supporta il monitoraggio dinamico dei video del consiglio comunale di Carpi tramite YouTube API, eliminando la logica hardcoded.

## Setup Richiesto

### 1. Ottenere API Key YouTube

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuovo progetto o seleziona quello esistente
3. Abilita YouTube Data API v3
4. Crea credenziali → API Key
5. Configura restrizioni per sicurezza

### 2. Trovare Playlist ID o Channel ID

**Opzione A - Playlist specifica:**
```
https://www.youtube.com/playlist?list=PLxxxxxxxx
Il playlist ID è: PLxxxxxxxx
```

**Opzione B - Channel (tutti i video):**
```
https://www.youtube.com/channel/UCxxxxxxxx
Il channel ID è: UCxxxxxxxx
```

### 3. Configurare le Credenziali

Modifica `home/monitor_configs.py`:

```python
CARPI_CONSIGLIO_CONFIG = SiteConfig(
    name="Consiglio Comunale Carpi",
    # ... altre configurazioni ...
    
    # SOSTITUIRE QUESTI VALORI:
    api_key="TUA_API_KEY_REALE_QUI",
    playlist_id="TUO_PLAYLIST_ID_QUI",  # O channel_id per tutti i video
    max_results=3,  # Numero video da controllare
)
```

## Utilizzo

### Comando Dinamico (Raccomandato)
```python
from home.youtube_transcript import genera_articoli_dinamici
result = genera_articoli_dinamici()
```

### Monitor Universale Diretto
```python
from home.universal_news_monitor import UniversalNewsMonitor
from home.monitor_configs import get_config

config = get_config('carpi_consiglio')
monitor = UniversalNewsMonitor(config, 600)
monitor.check_for_new_articles()
```

### Vecchia Funzione (Deprecata)
```python
from home.youtube_transcript import genera_e_salva_articolo
result = genera_e_salva_articolo()  # Solo video hardcoded
```

## Funzionalità

✅ **Monitor Dinamico**: Controlla automaticamente nuovi video  
✅ **Trascrizioni Automatiche**: Estrae trascrizioni YouTube  
✅ **AI Umberto Eco**: Genera articoli nello stile richiesto  
✅ **Content Polishing**: Rimuove emoji e simboli  
✅ **Logging Centralizzato**: Tutto registrato in `logs/monitors.log`  
✅ **Fallback**: Se API fallisce, usa funzione hardcoded  

## Troubleshooting

**Errore: "YouTubeAPIScraper richiede api_key e playlist_id"**
- Verificare che api_key e playlist_id siano configurati correttamente

**Nessun video trovato:**
- Verificare che il playlist_id sia corretto
- Controllare che la playlist sia pubblica
- Aumentare max_results se necessario

**Errori di trascrizione:**
- Alcuni video potrebbero non avere trascrizioni disponibili
- Il sistema continuerà con altri video della playlist

**Quota API superata:**
- YouTube API ha limiti di quota giornalieri
- Monitorare l'uso tramite Google Cloud Console
- Ridurre max_results o frequenza di controllo