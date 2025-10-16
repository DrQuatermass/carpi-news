# Guida alla Configurazione dei Monitor - Ombra del Portico

Guida completa per configurare nuovi monitor di notizie senza scrivere codice, utilizzando l'interfaccia admin di Django.

---

## Indice
1. [Introduzione](#introduzione)
2. [Accesso all'Admin](#accesso-alladmin)
3. [Tipi di Monitor Supportati](#tipi-di-monitor-supportati)
4. [Come Trovare i Selettori CSS](#come-trovare-i-selettori-css)
5. [Configurazione Passo-Passo](#configurazione-passo-passo)
6. [Parametri di Configurazione](#parametri-di-configurazione)
7. [Esempi Pratici](#esempi-pratici)
8. [Risoluzione Problemi](#risoluzione-problemi)

---

## Introduzione

I monitor sono processi automatici che controllano periodicamente un sito web per nuovi articoli. Ogni monitor è configurabile tramite l'interfaccia admin web, senza bisogno di scrivere codice.

### Cosa può fare un monitor:
- ✅ Scaricare articoli da siti HTML
- ✅ Leggere feed RSS
- ✅ Connettersi a API WordPress
- ✅ Estrarre video da YouTube
- ✅ Leggere email da caselle IMAP
- ✅ Estrarre immagini dagli articoli
- ✅ Generare contenuti con AI (opzionale)
- ✅ Auto-approvare articoli (opzionale)

---

## Accesso all'Admin

1. Vai su: `https://ombradelportico.it/admin/`
2. Login con credenziali admin
3. Clicca su **"Configurazioni Monitor"** sotto la sezione "HOME"
4. Clicca **"Aggiungi Configurazione Monitor"** in alto a destra

---

## Tipi di Monitor Supportati

### 1. HTML Scraping (Più comune)
**Quando usarlo**: La maggior parte dei siti web normali

**Pro**:
- Funziona con quasi tutti i siti
- Massima flessibilità
- Supporta immagini e contenuti complessi

**Contro**:
- Richiede configurazione dei selettori CSS
- Può rompersi se il sito cambia layout

---

### 2. WordPress API
**Quando usarlo**: Siti che espongono l'API REST di WordPress

**Come verificare**:
Visita: `https://SITO.it/wp-json/wp/v2/posts`

Se vedi un JSON, il sito supporta WordPress API!

**Pro**:
- Configurazione minima
- Molto affidabile
- Fornisce tutti i dati strutturati

**Contro**:
- Solo per siti WordPress
- Alcuni siti disabilitano l'API

---

### 3. RSS Feed
**Quando usarlo**: Siti che offrono feed RSS/Atom

**Come trovare il feed**:
- Cerca link con icona RSS 📡
- Prova: `https://SITO.it/feed/`
- Guarda il codice sorgente per `<link type="application/rss+xml">`

**Pro**:
- Semplice e affidabile
- Standard universale

**Contro**:
- Spesso contenuti parziali
- Alcuni siti non hanno feed

---

### 4. GraphQL API
**Quando usarlo**: Siti moderni con API GraphQL (es. Comune di Carpi)

**Pro**:
- Dati strutturati perfetti
- Molto veloce

**Contro**:
- Richiede conoscenza della query GraphQL
- Raro da trovare

---

### 5. YouTube API
**Quando usarlo**: Per canali YouTube

**Pro**:
- Estrae transcript dei video
- Genera articoli dal contenuto video

**Contro**:
- Richiede API Key Google

---

### 6. Email IMAP
**Quando usarlo**: Per comunicati stampa via email

**Pro**:
- Automatizza ricezione comunicati
- Estrae allegati PDF

**Contro**:
- Richiede credenziali email

---

## Come Trovare i Selettori CSS

### Metodo 1: Ispeziona Elemento (Browser)

**Passo 1**: Apri il sito di notizie nel browser

**Passo 2**: Clicca destro su un titolo di articolo → **"Ispeziona"** (o F12)

**Passo 3**: Nel pannello che si apre, vedrai l'HTML evidenziato

**Passo 4**: Cerca il tag che racchiude l'articolo completo. Esempi comuni:
```html
<article class="news-item">...</article>
<div class="post">...</div>
<div class="article-card">...</div>
```

**Passo 5**: Annota i selettori:

#### Per l'articolo completo:
- Tag: `article` → Selettore: `"article"`
- Classe: `class="news-item"` → Selettore: `".news-item"`
- ID: `id="post-123"` → Selettore: `"#post-123"` (raro, evitare)

#### Per il link:
Dentro l'articolo, trova il link (`<a href="...">`)
- Se ha classe: `<a class="title-link">` → `".title-link a"` o `".title a"`
- Se dentro un div: `<div class="title"><a>` → `".title a"`

#### Per l'immagine:
- Tag `<img src="...">` → `"img"`
- Con classe: `<img class="featured">` → `"img.featured"` o `".featured img"`

---

### Metodo 2: Test con Browser Console

**Passo 1**: Apri la console (F12 → Tab "Console")

**Passo 2**: Testa il selettore:
```javascript
document.querySelectorAll('article')
```

**Passo 3**: Controlla quanti elementi trova:
```javascript
document.querySelectorAll('article').length
// Output: 10 (significa 10 articoli trovati!)
```

**Passo 4**: Ispeziona il primo elemento:
```javascript
document.querySelectorAll('article')[0]
```

---

### Esempi di Selettori Comuni

| Elemento | HTML Esempio | Selettore CSS |
|----------|-------------|---------------|
| Tag diretto | `<article>` | `"article"` |
| Classe | `<div class="news">` | `".news"` |
| Più classi | `<div class="post card">` | `".post.card"` o `".post"` |
| Tag + classe | `<article class="item">` | `"article.item"` |
| Figlio diretto | `<div class="list"><article>` | `".list > article"` |
| Discendente | `<div class="posts"><div><article>` | `".posts article"` |
| Titolo dentro | `<article><h2 class="title">` | `".title"` o `"h2.title"` |
| Link dentro titolo | `<div class="title"><a>` | `".title a"` |
| Immagine | `<img class="thumb">` | `"img.thumb"` o `".thumb"` |

---

## Configurazione Passo-Passo

### Esempio: Configurare un monitor per un sito di notizie locale

**Sito esempio**: `https://www.esempio-notizie.it/categoria/cronaca/`

#### STEP 1: Campi Base

| Campo | Valore | Note |
|-------|--------|------|
| **Nome** | `Notizie Esempio - Cronaca` | Nome descrittivo |
| **Base URL** | `https://www.esempio-notizie.it/categoria/cronaca/` | URL della sezione notizie |
| **Tipo scraper** | `HTML Scraping` | Dalla dropdown |
| **Categoria** | `Cronaca` | Categoria articoli Django |
| **Attivo** | ✅ | Checkbox attivato |
| **Auto-approva** | ❌ | Se vuoi revisione manuale |

---

#### STEP 2: Config Data (JSON)

Clicca su **"Config data"** e inserisci:

```json
{
  "interval": 600,
  "disable_rss": true,
  "selectors": ["article"],
  "link_selector": ".title a",
  "image_selectors": ["img"],
  "content_selectors": [".body", ".content", "p"],
  "news_url": "https://www.esempio-notizie.it/categoria/cronaca/"
}
```

**Spiegazione**:
- `interval`: 600 secondi (10 minuti) tra un controllo e l'altro
- `disable_rss`: `true` = non provare RSS, solo HTML
- `selectors`: `["article"]` = cerca tutti gli elementi `<article>`
- `link_selector`: `".title a"` = il link è dentro `.title`
- `image_selectors`: `["img"]` = cerca il primo `<img>` nell'articolo
- `content_selectors`: array di selettori per il contenuto testuale
- `news_url`: URL da cui scaricare la lista articoli

---

#### STEP 3: Test

1. Salva il monitor (pulsante "Salva" in basso)
2. Nella lista monitor, trova il tuo monitor
3. Clicca il pulsante **"Test"** a destra
4. Aspetta qualche secondo
5. Controlla l'output:
   - ✅ "Articoli trovati: 15" → Tutto ok!
   - ❌ "Articoli trovati: 0" → Controlla i selettori

---

#### STEP 4: Attivazione

Se il test funziona:

1. Assicurati che **"Attivo"** sia ✅
2. Clicca **"Salva e continua a modificare"**
3. In alto vedrai eventuali errori o conferme
4. Il monitor partirà automaticamente al prossimo ciclo

Per forzare l'avvio immediato (da server):
```bash
python manage.py manage_db_monitors restart --monitor "Notizie Esempio - Cronaca"
```

---

## Parametri di Configurazione

### Parametri Obbligatori

```json
{
  "selectors": ["article"],
  "news_url": "https://..."
}
```

---

### Parametri Comuni

```json
{
  "interval": 600,
  "disable_rss": false,
  "selectors": ["article", ".post"],
  "link_selector": ".title a",
  "image_selectors": ["img", ".featured-image img"],
  "content_selectors": [".content", ".body", "p"],
  "news_url": "https://...",
  "auto_approve": false,
  "use_ai_generation": false
}
```

**Descrizione**:

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `interval` | numero | 900 | Secondi tra controlli (600 = 10min) |
| `disable_rss` | boolean | false | `true` = non provare RSS discovery |
| `selectors` | array | - | **OBBLIGATORIO**: selettori per trovare articoli |
| `link_selector` | string | - | Selettore specifico per il link dell'articolo |
| `image_selectors` | array | `["img"]` | Selettori per trovare immagini |
| `content_selectors` | array | - | Selettori per estrarre contenuto testo |
| `news_url` | string | - | **OBBLIGATORIO**: URL pagina con lista articoli |
| `auto_approve` | boolean | false | `true` = pubblica automaticamente |
| `use_ai_generation` | boolean | false | `true` = riscrive con AI |

---

### Parametri Avanzati

```json
{
  "additional_urls": [
    "https://sito.it/categoria2/",
    "https://sito.it/categoria3/"
  ],
  "exclude_patterns": ["/category/", "/tag/"],
  "content_filter_keywords": ["Carpi", "Modena"],
  "strip_image_params": false,
  "request_timeout": 15,
  "enable_web_search": false,
  "ai_system_prompt": "Riscrivi questa notizia in modo professionale..."
}
```

**Descrizione**:

| Parametro | Tipo | Descrizione |
|-----------|------|-------------|
| `additional_urls` | array | Altri URL da monitorare oltre a `news_url` |
| `exclude_patterns` | array | Pattern URL da escludere (es. `/tag/`) |
| `content_filter_keywords` | array | Solo articoli contenenti queste parole |
| `strip_image_params` | boolean | Rimuove `?param=value` dagli URL immagini |
| `request_timeout` | numero | Timeout richieste HTTP (secondi) |
| `enable_web_search` | boolean | Ricerca web durante generazione AI |
| `ai_system_prompt` | string | Prompt personalizzato per AI |

---

### Parametri WordPress API

```json
{
  "scraper_type": "wordpress_api",
  "per_page": 10,
  "categories": [5, 12],
  "tags": [8]
}
```

---

### Parametri YouTube

```json
{
  "scraper_type": "youtube_api",
  "api_key": "YOUR_YOUTUBE_API_KEY",
  "channel_id": "UCxxxxxx",
  "max_results": 5
}
```

---

### Parametri Email

```json
{
  "scraper_type": "email",
  "imap_server": "imap.gmail.com",
  "imap_port": 993,
  "email": "comunicati@esempio.it",
  "password": "xxx",
  "search_criteria": "UNSEEN"
}
```

---

## Esempi Pratici

### Esempio 1: Sito WordPress con RSS Disabilitato

**Sito**: Blog WordPress locale

**Configurazione**:
```json
{
  "interval": 1800,
  "disable_rss": false,
  "selectors": ["article.post"],
  "link_selector": ".entry-title a",
  "image_selectors": [".post-thumbnail img", "img.wp-post-image"],
  "content_selectors": [".entry-content"],
  "news_url": "https://blog.comune.esempio.it/news/"
}
```

**Note**: WordPress genera automaticamente tag `<article class="post">`, facilissimo!

---

### Esempio 2: Sito con Lazy Loading Immagini

**Sito**: Notizie con immagini base64 placeholder

**Problema**: Le immagini hanno `src="data:image/...base64..."` invece dell'URL

**Soluzione**: Il sistema controlla automaticamente `ta-srcset`, `srcset`, `data-src`

**Configurazione**:
```json
{
  "selectors": ["article"],
  "link_selector": ".title a",
  "image_selectors": ["img"],
  "news_url": "https://www.notiziecarpi.it/category/territorio/carpi/"
}
```

✅ **Il sistema trova automaticamente le immagini in `ta-srcset`!**

---

### Esempio 3: Sito con Layout Complesso

**Sito**: Portale con più link per articolo

**Problema**: Ogni articolo ha più `<a>`: categoria, autore, titolo

**Soluzione**: Usa `link_selector` per specificare quale link prendere

**Configurazione**:
```json
{
  "selectors": ["article"],
  "link_selector": "h2.title a",
  "image_selectors": [".featured-image img", "img"],
  "content_selectors": [".excerpt", ".summary"],
  "news_url": "https://www.giornale.it/notizie/"
}
```

**Spiegazione**: `link_selector: "h2.title a"` dice al monitor di usare solo il link dentro `<h2 class="title">`, ignorando gli altri.

---

### Esempio 4: Filtro per Keywords

**Obiettivo**: Prendere solo notizie che parlano di "Carpi"

**Configurazione**:
```json
{
  "selectors": ["article"],
  "content_filter_keywords": ["Carpi", "carpi"],
  "news_url": "https://www.gazzettadimodena.it/emilia/"
}
```

✅ **Solo articoli che contengono "Carpi" o "carpi" vengono salvati**

---

### Esempio 5: WordPress API

**Sito**: `https://www.comune.carpi.mo.it`

**Verifica API**: Vai su `https://www.comune.carpi.mo.it/wp-json/wp/v2/posts`

Se funziona, configura:

```json
{
  "scraper_type": "wordpress_api",
  "per_page": 20,
  "news_url": "https://www.comune.carpi.mo.it/wp-json/wp/v2/posts"
}
```

✅ **Configurazione minima, massima affidabilità!**

---

## Risoluzione Problemi

### Problema: "Articoli trovati: 0"

**Possibili cause**:

#### 1. Selettore sbagliato
**Soluzione**:
- Ispeziona il sito con F12
- Testa in console: `document.querySelectorAll('TUO_SELETTORE').length`
- Prova selettori alternativi: `[".news", ".post", "article", ".article-item"]`

#### 2. RSS discovery interferisce
**Soluzione**:
```json
{
  "disable_rss": true
}
```

#### 3. Sito richiede JavaScript
**Soluzione**: Alcuni siti moderni caricano contenuti con JS. Il monitor non può gestirli. Alternative:
- Usa WordPress API se disponibile
- Usa RSS feed se disponibile
- Contatta il gestore del sito

#### 4. Blocco anti-bot
**Soluzione**: Raro dopo la rimozione di `Accept-Encoding`, ma può succedere
- Aumenta `interval` (es. 3600 = 1 ora)
- Il monitor usa User-Agent realistico, dovrebbe bastare

---

### Problema: "Articoli senza immagini"

**Possibili cause**:

#### 1. Immagini in lazy loading
**Soluzione**: ✅ **Già gestito automaticamente!**
Il sistema cerca automaticamente in:
- `ta-srcset`
- `srcset`
- `data-srcset`
- `data-src`
- `data-lazy-src`
- `src`

#### 2. Immagini piccole filtrate
**Soluzione**: Il sistema filtra icone/loghi < 80x60px automaticamente

#### 3. Selettore immagine troppo specifico
**Soluzione**:
```json
{
  "image_selectors": ["img"]
}
```
Usa il selettore più generico possibile, poi il sistema trova la migliore

---

### Problema: "Articoli duplicati"

**Possibili cause**:

#### 1. URL con parametri variabili
**Esempio**:
- `https://sito.it/articolo?utm_source=facebook`
- `https://sito.it/articolo?utm_source=twitter`

**Soluzione**: Il sistema rimuove duplicati per URL, ma parametri diversi = URL diversi. Nessuna soluzione automatica al momento.

---

### Problema: "Link sbagliato estratto"

**Causa**: Articolo ha più link, il sistema prende il primo

**Esempio HTML**:
```html
<article>
  <a href="/categoria/">Cronaca</a>  <!-- Link categoria -->
  <h2><a href="/articolo-123/">Titolo</a></h2>  <!-- Link articolo -->
</article>
```

**Soluzione**: Usa `link_selector`
```json
{
  "link_selector": "h2 a"
}
```

---

### Problema: "Contenuto troppo corto"

**Causa**: Il sistema scarta articoli con preview < 30 caratteri

**Soluzione**: Specifica `content_selectors` migliori
```json
{
  "content_selectors": [".article-body", ".content", ".entry-content", "p"]
}
```

---

## Checklist Configurazione Monitor

Usa questa checklist prima di attivare un monitor:

### ✅ Pre-configurazione
- [ ] Ho verificato che il sito non ha già un monitor attivo
- [ ] Ho controllato se esiste WordPress API (`/wp-json/wp/v2/posts`)
- [ ] Ho controllato se esiste RSS feed (`/feed/`)
- [ ] Ho scelto il tipo di scraper appropriato

### ✅ Configurazione base
- [ ] Nome descrittivo inserito
- [ ] Base URL corretto (con https://)
- [ ] Categoria appropriata selezionata
- [ ] `news_url` inserito nel JSON

### ✅ Selettori (HTML Scraping)
- [ ] `selectors` testato con console browser
- [ ] `selectors` trova almeno 5-10 articoli
- [ ] `link_selector` configurato se necessario
- [ ] `image_selectors` configurato

### ✅ Test
- [ ] Pulsante "Test" cliccato
- [ ] Output mostra > 0 articoli
- [ ] Articoli hanno titoli sensati
- [ ] La maggior parte ha immagini (se il sito le fornisce)

### ✅ Attivazione
- [ ] Checkbox "Attivo" selezionato
- [ ] `interval` configurato (consigliato: 600-1800 secondi)
- [ ] `auto_approve` configurato secondo necessità
- [ ] Monitor salvato

### ✅ Verifica post-attivazione (dopo 1-2 cicli)
- [ ] Articoli appaiono nel database
- [ ] Immagini estratte correttamente
- [ ] Nessun duplicato
- [ ] Categoria corretta

---

## Suggerimenti Avanzati

### 1. Intervallo Ottimale

| Tipo Sito | Frequenza Aggiornamento | Intervallo Consigliato |
|-----------|------------------------|------------------------|
| Quotidiano nazionale | Ogni ora | 1800s (30min) |
| Blog comunale | 2-3 volte/settimana | 3600s (1h) |
| Comunicati stampa | Sporadico | 7200s (2h) |
| YouTube channel | Sporadico | 10800s (3h) |
| Email | Continuo | 600s (10min) |

**Regola**: Più il sito si aggiorna, più frequente l'intervallo. Ma **mai < 300s (5 min)** per evitare sovraccarico.

---

### 2. Test Rapido Selettori

Crea un file HTML di test:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Test Selettori</title>
</head>
<body>
    <!-- Incolla qui l'HTML copiato dal sito -->

    <script>
        // Testa selettori
        console.log('Articoli:', document.querySelectorAll('article').length);
        console.log('Links:', document.querySelectorAll('.title a').length);
        console.log('Immagini:', document.querySelectorAll('img').length);
    </script>
</body>
</html>
```

1. Salva come `test.html`
2. Apri in browser
3. Apri console (F12)
4. Vedi quanti elementi trova

---

### 3. Debug Mode

Per vedere log dettagliati, aggiungi al JSON:

```json
{
  "debug": true
}
```

Poi controlla: `/var/www/carpi-news/carpi_news/logs/monitors.log`

---

## Prossimi Passi

Dopo aver configurato il monitor:

1. **Monitora i log** per i primi giorni
   ```bash
   tail -f logs/monitors.log | grep "Nome Monitor"
   ```

2. **Controlla articoli generati** nell'admin Django

3. **Affina la configurazione** se necessario:
   - Aggiungi `exclude_patterns` per URL indesiderati
   - Aggiungi `content_filter_keywords` per filtrare argomenti
   - Modifica `interval` se troppo/poco frequente

4. **Attiva auto-approve** quando sei sicuro che funzioni bene

---

## Risorse Utili

### Selettori CSS
- [MDN CSS Selectors](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Selectors)
- [CSS Selector Tester](https://try.jsoup.org/) - Testa selettori online

### WordPress
- Documentazione API: [WordPress REST API](https://developer.wordpress.org/rest-api/)

### Strumenti Browser
- Chrome DevTools: F12 → Elements → Console
- Firefox Developer Tools: F12
- Extension: "SelectorGadget" per Chrome

---

## Supporto

Per problemi o domande:

1. Controlla prima questa guida
2. Controlla `/var/www/carpi-news/carpi_news/logs/monitors.log`
3. Testa con pulsante "Test" nell'admin
4. Se il problema persiste, contatta lo sviluppatore con:
   - Nome monitor
   - URL sito
   - Output del test
   - Screenshot errori

---

**Ultima revisione**: 16 Ottobre 2025
**Versione**: 2.0
**Autore**: Sistema Ombra del Portico

