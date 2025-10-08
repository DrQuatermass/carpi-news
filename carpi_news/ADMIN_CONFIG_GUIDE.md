# Guida alla Configurazione Monitor dall'Admin

## 🎯 Miglioramenti User-Friendly

Il campo "Configurazioni Specifiche (JSON)" ora include:

### ✨ Caratteristiche

1. **Template Pronti all'Uso**
   - Template JSON per ogni tipo di scraper
   - Pulsanti "Copia Template" per copia rapida
   - Esempi commentati

2. **Documentazione Integrata**
   - Help text dinamico basato sul tipo di scraper
   - Descrizione di ogni campo
   - Suggerimenti sui valori

3. **Validazione Automatica**
   - Verifica che il JSON sia valido
   - Controllo intervallo minimo (300s)
   - Messaggi d'errore chiari

4. **Widget Migliorato**
   - Font monospace per leggibilità
   - Textarea più grande (20 righe)
   - Scroll automatico per JSON lunghi

## 📋 Come Usare

### 1. Creare Nuovo Monitor

1. Vai su `/admin/home/monitorconfig/add/`
2. Compila i campi base:
   - Nome: "Mio Sito News"
   - URL: "https://example.com/"
   - Tipo scraper: Seleziona (HTML, WordPress, YouTube, GraphQL, Email)
   - Categoria: "Attualità"

3. **Configurazioni Specifiche (JSON)**:
   - Espandi la sezione "Template Configurazioni"
   - Trova il template per il tuo tipo di scraper
   - Clicca "📋 Copia Template"
   - Incolla nel campo `config_data`
   - Personalizza i valori

4. Configura AI (opzionale):
   - Attiva "use_ai_generation"
   - Attiva "enable_web_search" se desiderato
   - Scrivi il prompt personalizzato

5. Salva

### 2. Template Disponibili

#### HTML Scraping
```json
{
  "interval": 600,
  "news_url": "https://example.com/news/",
  "disable_rss": true,
  "selectors": [".article", ".news", "article"],
  "content_selectors": [".content", ".article-body", "main"],
  "image_selectors": ["img.featured", ".post-thumbnail img"],
  "content_filter_keywords": ["Carpi"]
}
```

**Campi:**
- `interval`: Intervallo esecuzione in secondi (min 300)
- `news_url`: URL pagina con le notizie
- `disable_rss`: Disabilita discovery RSS
- `selectors`: CSS selectors per trovare articoli nella lista
- `content_selectors`: Selectors per estrarre contenuto da pagina articolo
- `image_selectors`: Selectors per trovare immagini
- `content_filter_keywords`: Filtra articoli per keyword

#### WordPress API
```json
{
  "interval": 600,
  "api_url": "https://example.com/wp-json/wp/v2/posts",
  "per_page": 10
}
```

**Campi:**
- `api_url`: Endpoint API WordPress (di solito /wp-json/wp/v2/posts)
- `per_page`: Numero articoli per richiesta (default 10)

#### YouTube API
```json
{
  "interval": 1800,
  "api_key": "YOUR_YOUTUBE_API_KEY",
  "playlist_id": "PLxxxxxx",
  "max_results": 5,
  "transcript_delay": 60,
  "live_stream_retry_delay": 3600
}
```

**Campi:**
- `api_key`: YouTube Data API v3 key (da Google Cloud Console)
- `playlist_id`: ID playlist YouTube (formato PLxxxxxx)
- `max_results`: Numero max video da processare
- `transcript_delay`: Pausa tra richieste trascrizioni (secondi)
- `live_stream_retry_delay`: Attesa prima di riprovare dirette (secondi)

#### GraphQL API
```json
{
  "interval": 600,
  "graphql_endpoint": "https://api.example.com/graphql",
  "graphql_headers": {
    "accept": "*/*",
    "content-language": "it"
  },
  "graphql_query": "query { posts { id title content } }",
  "fallback_to_wordpress": true,
  "download_images": true
}
```

**Campi:**
- `graphql_endpoint`: URL endpoint GraphQL
- `graphql_headers`: Headers HTTP da includere nella richiesta
- `graphql_query`: Query GraphQL da eseguire
- `fallback_to_wordpress`: Usa WordPress API se GraphQL fallisce
- `download_images`: Scarica immagini in locale (in /media/)

#### Email IMAP
```json
{
  "interval": 300,
  "imap_server": "imap.example.com",
  "imap_port": 993,
  "email": "user@example.com",
  "password": "YOUR_PASSWORD",
  "mailbox": "INBOX",
  "sender_filter": [],
  "subject_filter": []
}
```

**Campi:**
- `imap_server`: Server IMAP (es. imap.gmail.com, imaps.aruba.it)
- `imap_port`: Porta IMAP (di solito 993 per SSL)
- `email`: Indirizzo email da monitorare
- `password`: Password email (⚠️ sarà salvata in chiaro nel DB)
- `mailbox`: Cartella da monitorare (default INBOX)
- `sender_filter`: Lista mittenti da processare (vuoto = tutti)
- `subject_filter`: Lista keyword oggetto (vuoto = tutti)

## ✅ Validazione

Il form valida automaticamente:

### Errori Comuni

**"JSON non valido"**
```
Causa: Sintassi JSON errata
Fix: Controlla virgole, parentesi, virgolette
Tip: Usa un validatore JSON online prima di incollare
```

**"L'intervallo minimo è 300 secondi"**
```
Causa: interval < 300
Fix: Usa almeno 300 (5 minuti)
Motivo: Previene rate limiting dei siti
```

**"Campo obbligatorio"**
```
Causa: Manca un campo richiesto
Fix: Aggiungi il campo mancante dal template
```

## 💡 Best Practices

### Intervalli Consigliati
- **News urgenti**: 300s (5 min) - ANSA, breaking news
- **News standard**: 600s (10 min) - siti locali
- **News periodiche**: 900-1800s (15-30 min) - YouTube, newsletter
- **News rare**: 3600s+ (1 ora) - eventi, pubblicazioni ufficiali

### Selectors CSS
```css
/* Preferisci selectors specifici */
✅ .article-list .article-item
❌ div div div

/* Usa classi semantiche */
✅ .news-entry, .post-item
❌ .col-md-6, .mb-3

/* Multipli selectors = fallback */
selectors: [
  ".news-list-item",  // Prova prima questo
  ".article",         // Poi questo
  "article"          // Infine questo generico
]
```

### Content Filter Keywords
```json
// Case insensitive, cerca in tutto il contenuto
"content_filter_keywords": [
  "Carpi",
  "Gregorio Paltrinieri",  // nomi specifici
  "Aimag",                 // organizzazioni locali
  "Terre d'Argine"         // area geografica
]
```

### API Keys Security
⚠️ **IMPORTANTE**: Le API keys sono salvate in chiaro nel database!

**Per produzione:**
1. Usa variabili d'ambiente quando possibile
2. Limita permessi chiavi API (read-only)
3. Monitora usage per rilevare abusi
4. Ruota chiavi periodicamente
5. Considera encryption campo `config_data`

## 🔧 Troubleshooting

### Il template non viene caricato
**Problema**: Il campo config_data è vuoto
**Soluzione**:
1. Clicca "Template Configurazioni"
2. Espandi il tipo di scraper desiderato
3. Clicca "📋 Copia Template"
4. Incolla nel campo config_data sotto

### Errore "Configurazione non valida"
**Problema**: Manca un campo richiesto per il tipo di scraper
**Soluzione**:
1. Verifica di aver copiato il template completo
2. Controlla che `interval` sia presente
3. Per HTML: assicurati ci sia `news_url` o `rss_url`
4. Per WordPress: assicurati ci sia `api_url`
5. Per YouTube: assicurati ci siano `api_key` e `playlist_id`

### Monitor non trova articoli
**Problema**: Selectors sbagliati
**Debugging**:
1. Apri il sito in browser
2. Usa DevTools (F12) → Inspector
3. Identifica i selectors CSS corretti
4. Testa con `document.querySelectorAll('.tuo-selector')`
5. Aggiorna `selectors` nel config_data

### JSON non si salva
**Problema**: Sintassi errata
**Fix**:
```json
// ❌ SBAGLIATO
{
  "interval": 600,  // no commenti in JSON!
  'selectors': []   // no virgolette singole!
  "test": undefined // no undefined!
}

// ✅ CORRETTO
{
  "interval": 600,
  "selectors": [],
  "test": null
}
```

## 📚 Risorse

- **CSS Selectors**: https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Selectors
- **JSON Validator**: https://jsonlint.com/
- **YouTube API**: https://developers.google.com/youtube/v3
- **WordPress REST API**: https://developer.wordpress.org/rest-api/

## 🆘 Support

In caso di problemi:
1. Controlla i log: Admin → Monitor → "📋 View Logs"
2. Usa "🧪 Test Monitor" prima di attivare
3. Verifica config_data con JSON validator
4. Consulta `MONITOR_DB_SYSTEM.md` per dettagli tecnici
