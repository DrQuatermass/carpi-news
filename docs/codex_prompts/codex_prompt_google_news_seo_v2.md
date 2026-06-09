# Codex prompt — Recupero indicizzazione & qualità per Helpful Content System

## Contesto verificato (dati Search Console 24 mag 2026)

Progetto Django 5.2.5 in `carpi_news/` ("Ombra del Portico", news Carpi).

**Cosa funziona già** (NON toccare):
- Publisher Center registrato, dominio verificato
- Sitemap index/archive/news inviate e LETTE (24/05/26)
- 1.950 pagine indicizzate (su 4.900 totali)
- Core Web Vitals verde su tutto (mobile + desktop)
- HTTPS, breadcrumb, schema NewsArticle, OG, robots.txt: ok
- IndexNow via Yandex attivo, Google Indexing API correttamente disabilitato

**Problemi confermati da Search Console**:
- **1.889 pagine "Scansionate ma non indicizzate"** = Google le legge e scarta
- **434 pagine "Rilevate ma non indicizzate"** = sa che esistono, non le crawla
- **467 noindex** = da audit
- **71 404** = link rotti
- **Convalida richiesta 11 mag fallita 12 mag** = Google ha confermato il rifiuto
- **Sitemap-news contiene solo 17 URL** = filtro troppo stretto
- **Google News: 1 clic in 3 mesi**
- Pattern degli URL respinti: slug troncati (`tre-gi/`, `allariston/`), parole
  inventate (`metat-vesta`, `spira-mirabilis`), titoli AI-clickbait ("Tortellini
  rock quando pasta diventa rivoluzione silenziosa"), articoli su altri comuni
  che diluiscono il focus Carpi.

**Conclusione**: il sito non è bloccato, è penalizzato dall'Helpful Content
System per pattern AI riconoscibili. Serve intervento sui contenuti + segnali
E-E-A-T, non sull'infrastruttura SEO (che è ok).

## Azioni richieste (in ordine di priorità)

### P0 — FIX SLUG MALFORMATI (impatto massimo)

In `home/models.py` la funzione di generazione slug sta producendo slug troncati
e con parole rotte. Trova dove viene generato lo slug (probabilmente `save()`
dell'Articolo o un signal pre_save). Verifica:

a) Lo slug viene troncato a un limite di caratteri? Se sì, deve troncare a
**parola intera**, non a metà. Usa `django.utils.text.slugify` + truncate
in posizione di spazio prima dello slugify.

b) Lo slug viene generato dal `titolo` o dal `titolo_seo`? Se da AI-generated
titolo SEO, può contenere parole italiane storpiate o nomi propri inventati.
Aggiungi una validazione: lo slug NON deve contenere sequenze di consonanti
improbabili in italiano (es. >3 consonanti consecutive, eccetto coppie note
come "scr", "spl", "str"). Se rileva uno slug malformato, fallback a
slug = slugify(titolo)[:80] troncato a parola.

c) Lo slug deve essere **rigenerato per gli articoli esistenti con problemi**:
crea un management command `python manage.py fix_malformed_slugs --dry-run`
che identifica articoli con slug:
- terminanti su singola lettera o sillaba sospetta (es. `...gi/`, `...vesta/`)
- contenenti parole non in un dizionario base italiano
- più lunghi di 80 caratteri

Per ogni articolo problematico, genera NUOVO slug e crea un redirect 301
permanente dal vecchio slug al nuovo. NON spostare semplicemente: i 1.889
URL respinti hanno il vecchio slug come "memoria" su Google. Servono 301
per ricominciare con URL nuovi.

Crea modello `ArticoloRedirect(old_slug, new_slug, created_at)` per gestire
i redirect. Aggiungi middleware o view che intercetti i vecchi slug e
redirigi 301.

### P1 — PULIZIA NOINDEX E 404

a) Identifica le **467 pagine con noindex**:
```
grep -rn "noindex" home/templates/ carpi_news/
```
Probabilmente sono pagine admin/test/paginazione legacy. Verifica che siano
intenzionali. Se trovi noindex su pagine articolo, è un bug critico.

b) **71 pagine 404**: probabilmente articoli cancellati o slug cambiati senza
redirect. Crea management command `python manage.py find_broken_links` che
legge la sitemap_archive.xml e cerca articoli con `approvato=False` o
eliminati. Per ogni 404, decidi: ripristina o crea redirect 301 alla
categoria pertinente.

### P2 — RIMUOVERE WebSub/sitemap-ping deprecati (codice morto)

- Elimina `home/websub.py`
- Elimina signal `notify_websub_on_approval` in `home/models.py` (righe ~849-872)
- Elimina `home/sitemap_ping.py`
- Cerca e rimuovi tutti gli import di questi due moduli

### P3 — SITEMAP-NEWS TROPPO RESTRITTIVA

`home/views.py:536-559` filtra ultimi 48h + esclude Editoriale, Cosa fare oggi,
pubbliredazionali, articoli con titolo "test". Risultato: solo 17 URL in
sitemap.

Modifica il filtro:
- Estendi finestra a **72h** (Google News accetta fino a 2 giorni; 72h dà margine)
- Mantieni esclusione pubbliredazionali e articoli test
- Riconsidera l'esclusione "Editoriale" — molti editoriali su cronaca locale
  sono pertinenti per Google News. Escludi solo `categoria='Cosa fare oggi'`.

### P4 — ATTRIBUZIONE AUTORE E E-E-A-T

a) Aggiungi al modello `Articolo` in `home/models.py`:

```python
autore = models.CharField(
    max_length=120,
    default="Redazione Ombra del Portico"
)
```

b) In `dettaglio_articolo.html` sostituisci nello schema NewsArticle:

```json
"author": {
  "@type": "Organization",
  "name": "{{ articolo.autore|default:'Redazione Ombra del Portico'|escapejs }}",
  "url": "https://ombradelportico.it/redazione/"
}
```

c) Crea 3 nuove pagine + view + url:

- `/redazione/` — bio organizzazione + schema Organization
- `/politica-editoriale/` — **dichiara apertamente l'uso di AI** sotto
  supervisione editoriale (trasparenza vince sulla scoperta)
- `/correzioni/` — policy per segnalazione errori

d) Linka le 3 pagine dal footer del sito.

e) Mostra l'autore nel template visibile sotto al titolo
(`<p class="article-byline">di {{ articolo.autore }}</p>`).

### P5 — VALIDATORE TITOLI AI / CLICKBAIT

In `home/content_polisher.py` aggiungi una funzione post-generazione:

```python
def is_natural_italian_title(title: str) -> bool:
    """
    Rigetta titoli clickbait o innaturali:
    - parole rare/inventate (metafore: 'rivoluzione silenziosa',
      'spira mirabilis')
    - frasi che iniziano con 'Quando...'
    - sequenze di consonanti improbabili in italiano
    """
    ...
```

Se titolo fallisce validazione, rifallo (max 3 tentativi) con prompt all'AI
che includa esempi di titoli giornalistici naturali da sulpanaro.net,
voce.it, modenatoday.it.

### P6 — POST-FIX: RICHIESTA RIVALIDAZIONE SEARCH CONSOLE

Dopo aver applicato P0-P4 e pubblicato 20-30 articoli con i nuovi standard,
il proprietario deve:

1. Search Console → Pagine → "Scansionata, ma non indicizzata"
2. "VEDI DETTAGLI" → "CONVALIDA CORREZIONE"

NON farlo prima dei fix. Google ha già fallito la convalida del 12 maggio:
una seconda richiesta senza cambiamenti reali peggiora la fiducia
algoritmica.

## Cosa NON toccare (è ok)

- Sitemap index/archive (eccetto filtro time-window di news)
- `home/indexing_notifier.py`
- robots.txt
- schema NewsArticle base, OG, breadcrumb, meta canonical
- Core Web Vitals
- Publisher Center

## Output atteso

- Diff completo
- Migration generate
- Output di `python manage.py fix_malformed_slugs --dry-run` (preview)
- Numero esatto di articoli con slug malformati identificati
- Numero esatto di pagine con noindex trovate e relativa motivazione
- Numero esatto di 404 trovati e azione raccomandata per ognuno
