# Codex prompt — Pulizia SEO Google News & fix segnali E-E-A-T

## Contesto

Progetto Django 5.2.5 in `carpi_news/` ("Ombra del Portico", news Carpi).
Il sito è quasi invisibile su Google: `site:ombradelportico.it` restituisce
1 solo articolo del 2025 e la pagina `/cinema/`. Zero articoli del 2026.

L'infrastruttura SEO tecnica è solida (sitemap-news.xml con tag <news:news>,
schema NewsArticle, canonical, Open Graph, robots.txt, IndexNow via Yandex,
Search Console e Bing Webmaster verificati). Il problema è di **segnali di
qualità/trust**, non di crawling.

Devi pulire codice deprecato e aggiungere segnali E-E-A-T che Google News usa
per giudicare l'affidabilità editoriale. NON toccare la sitemap_news.xml,
sitemap_index.xml, robots.txt, schema NewsArticle base — sono corretti.

## Azioni richieste (in ordine)

### 1. Rimuovere WebSub deprecato (no-op che spreca chiamate HTTP)

`home/websub.py` chiama `pubsubhubbub.appspot.com`. Google ha deprecato
PubSubHubbub per news. Il file è chiamato a OGNI `post_save` di un articolo
approvato dal signal `notify_websub_on_approval` in `home/models.py:850-872`,
quindi parte un POST inutile in background ogni volta.

- Elimina il signal `notify_websub_on_approval` da `home/models.py`
  (decorator @receiver + funzione, righe ~849-872).
- Elimina il file `home/websub.py`.
- Cerca altri import di `home.websub` (`grep -rn "from home.websub\|import websub\|home/websub" .`)
  e rimuovili.

### 2. Rimuovere sitemap_ping.py deprecato

`home/sitemap_ping.py` usa `google.com/ping?sitemap=` (deprecato giugno 2023)
e `bing.com/ping?sitemap=` (deprecato metà 2022). Non è chiamato dal codice
principale ma può essere chiamato manualmente. Eliminalo.

- Elimina `home/sitemap_ping.py`.
- Cerca tutti i riferimenti (`grep -rn "sitemap_ping\|notify_search_engines\|ping_google_sitemap\|ping_bing_sitemap" .`)
  e rimuovili (sono già 0 nel codice attivo ma verifica scripts esterni e management commands).

### 3. Fix autore Schema NewsArticle — segnale anti-spam critico

In `home/templates/dettaglio_articolo.html` lo schema NewsArticle ha
`"author": {"@type": "Person", "name": "Sven Rinaldi"}` hardcoded su TUTTI
gli articoli. In `base.html` il meta tag dichiara invece
`author = "Redazione Ombra del Portico"`. Incoerenza + Google penalizza
"single author churning content" su volumi alti.

Modifica:

a) Aggiungi al modello `Articolo` in `home/models.py` un campo opzionale:

```python
autore = models.CharField(
    max_length=120,
    default="Redazione Ombra del Portico",
    help_text="Autore dell'articolo (firma redazionale o personale)"
)
```

Genera la migration. Default backfill = "Redazione Ombra del Portico".

b) In `home/templates/dettaglio_articolo.html`, sostituisci:

```json
"author": {
  "@type": "Person",
  "name": "Sven Rinaldi",
  "url": "https://ombradelportico.it"
}
```

con:

```json
"author": {
  "@type": "Organization",
  "name": "{{ articolo.autore|default:'Redazione Ombra del Portico'|escapejs }}",
  "url": "https://ombradelportico.it/redazione/"
}
```

Quando un articolo avrà un autore fisico (es. "Giulia Bianchi"), il default
verrà sovrascritto manualmente.

c) In `base.html`, allinea il meta tag author al valore organizzazione:
`<meta name="author" content="Redazione Ombra del Portico">` è già OK.
Verifica che combaci con lo schema.

d) Mostra l'autore nel template visibile (sotto al titolo, prima del
contenuto): aggiungi `<p class="article-byline">di {{ articolo.autore }}</p>`
con stile inline o nel CSS.

### 4. Creare le pagine E-E-A-T mancanti

Crea 3 pagine HTML (estendono `base.html`) e relative view/url:

#### a) `/redazione/` — `templates/redazione.html`

Pagina con:
- Titolo "La nostra redazione"
- Mission editoriale (2-3 paragrafi)
- Lista autori/firme con bio breve (3-5 righe ognuno). Inizialmente
  contiene solo "Redazione Ombra del Portico" con bio dell'organizzazione.
  Lascia un commento HTML `<!-- TODO: aggiungere autori reali con foto e bio -->`
- Schema JSON-LD `Organization` con `name`, `url`, `logo`, `sameAs`
  (link a Facebook/Instagram), `email` di contatto, `address` Carpi.
- Schema JSON-LD `Person` per ciascun autore (per ora solo la redazione).

#### b) `/politica-editoriale/` — `templates/politica_editoriale.html`

Pagina che spiega:
- Come vengono selezionate le notizie (fonti monitorate, criteri di
  rilevanza locale per Carpi)
- Trasparenza sull'uso di AI: dichiara apertamente che alcuni articoli sono
  redatti con assistenza di sistemi di intelligenza artificiale a partire da
  fonti citate, sotto supervisione editoriale. (Questo è il modo corretto di
  dichiararlo per non essere penalizzati — il problema è l'omissione, non
  l'uso.)
- Distinzione tra news, editoriali, pubbliredazionali
- Indipendenza editoriale e fonti di finanziamento

#### c) `/correzioni/` — `templates/correzioni.html`

Pagina con:
- Spiegazione di come segnalare errori (email redazione@ombradelportico.it)
- Politica di correzione (errori corretti vengono segnalati a fine articolo
  con data e tipo di correzione)
- Sezione "Storico correzioni" inizialmente vuota (placeholder
  `<!-- TODO: log correzioni quando arrivano -->`)

#### d) Aggiungi le 3 URL in `carpi_news/urls.py` o `home/urls.py`:

```python
path('redazione/', views.redazione, name='redazione'),
path('politica-editoriale/', views.politica_editoriale, name='politica_editoriale'),
path('correzioni/', views.correzioni, name='correzioni'),
```

E le view in `home/views.py` come render template semplici.

#### e) Aggiungi link a queste 3 pagine nel **footer** di `base.html`
(o nel template del footer se separato), nella sezione "Informazioni" o
simile.

### 5. Normalizzazione canonical (no-www)

In `home/views.py` cerca dove viene calcolato `canonical_url` per
`dettaglio_articolo`. Assicurati che usi sempre **`https://ombradelportico.it`**
senza `www`, con trailing slash, e senza query string.

Se non c'è già, aggiungi una utility in `home/utils.py` (creala se non esiste):

```python
def canonical_article_url(article):
    from django.urls import reverse
    return f"https://ombradelportico.it{reverse('dettaglio_articolo', args=[article.slug])}"
```

E usala nella view dell'articolo passando `canonical_url` al context.

Verifica anche che Apache o Django redirigano permanentemente
`www.ombradelportico.it` → `ombradelportico.it` con 301.
(Se non lo fa, modifica `apache_https_redirect.conf.example` o il middleware.)

### 6. Aggiungi `<meta name="news_keywords">` legacy

Nel template `dettaglio_articolo.html`, dentro `{% block extra_css %}` o
subito sotto, aggiungi:

```html
<meta name="news_keywords" content="{{ articolo.meta_keywords }}">
```

Alcuni crawler news (incluso Bing News) lo usano ancora. Costo zero.

### 7. Test e commit

- Esegui `python manage.py makemigrations && python manage.py migrate`
- Verifica con `python manage.py check`
- Lancia il dev server e visita le 3 nuove pagine + un articolo per
  controllare che il rendering sia OK.
- Valida il JSON-LD di un articolo con
  https://search.google.com/test/rich-results (passa il render HTML).
- Crea un commit unico con messaggio:
  `seo: rimuove WebSub/sitemap-ping deprecati, fix author schema, aggiunge pagine E-E-A-T (redazione/politica/correzioni)`

## Cosa NON toccare

- `home/sitemap_index.xml`, `sitemap.xml`, `sitemap_news.xml`, `sitemap_archive.xml`, `robots.txt` (sono corretti)
- `home/indexing_notifier.py` — IndexNow funziona, Google API disabilitata correttamente
- Lo schema `NewsArticle` esistente eccetto il blocco `author`
- I signal di condivisione social
- Le viste sitemap in `views.py`

## Output atteso

Diff completo + lista delle migration generate + screenshot/output di
`python manage.py check` + comando di test usato per validare il JSON-LD.
