# Codex prompt SEO P3 — Pagine errore 404/500 custom

## Contesto

Progetto Django 5.2.5 in `carpi_news/`, sito news "Ombra del Portico"
(ombradelportico.it). L'impianto SEO è già completo (meta, JSON-LD, sitemap, canonical,
redirect 301). Mancano solo le pagine errore custom: oggi un 404 mostra la pagina
generica di Django — brutta per l'utente e occasione persa di trattenerlo.

**Nota di scope:** NON creare pagine istituzionali nuove (niente `/redazione/`,
`/politica-editoriale/`, `/correzioni/`): `/about/` resta l'unica pagina istituzionale,
per decisione esplicita. Solo 404 e 500.

## Azioni

### 1. Template `404.html`

In `carpi_news/home/templates/404.html`, estende `base.html`:
- Messaggio chiaro in italiano ("Pagina non trovata") con tono coerente col sito.
- Link alla homepage e barra/menu già forniti da `base.html`.
- Sezione "Articoli recenti": al massimo 4-6 card leggere (titolo + link, niente
  immagini con logica pesante). I dati arrivano da un handler custom:

```python
# home/views.py
def custom_404(request, exception):
    from django.core.cache import cache
    articoli = cache.get('error404_articoli')
    if articoli is None:
        articoli = list(
            get_published_articles_query()
            .order_by('-data_pubblicazione')
            .values('titolo', 'slug')[:6]
        )
        cache.set('error404_articoli', articoli, 3600)
    return render(request, '404.html', {'articoli_recenti': articoli}, status=404)
```

- Registrare in `carpi_news/urls.py`: `handler404 = 'home.views.custom_404'`.
- Il template deve funzionare anche se `articoli_recenti` è vuoto.
- Meta: `<meta name="robots" content="noindex">` sul blocco head della 404.

### 2. Template `500.html`

In `carpi_news/home/templates/500.html`:
- **Completamente statico e autonomo**: NON estendere `base.html` (i context processor
  toccano DB/cache e in un 500 potrebbero essere proprio loro a fallire). HTML standalone
  con stile inline minimo, logo via path statico hardcoded, messaggio di cortesia e
  link `<a href="/">` alla home.
- Django lo usa automaticamente con `DEBUG=False`; non serve handler custom.

### 3. Coerenza visiva

Riprendere palette e font del sito (vedi variabili in
`home/static/home/css/style.css` e `theme-color #966C42` in `base.html:14`) — per la
404 via classi CSS esistenti, per la 500 con un piccolo blocco `<style>` inline copiato.

## Vincoli

- Nessuna nuova route pubblica oltre agli handler di errore.
- La 404 non deve fare più di 1 query (e zero quando la cache è calda).
- La 500 deve renderizzare anche con DB e cache giù (test: `render_to_string('500.html')`
  senza context).
- Non toccare `robots.txt`, sitemap o altre pagine.

## Verifica

1. Test: GET su `/articolo/slug-inesistente/` → status 404, template custom (asserire
   un testo distintivo della pagina), max 1 query con cache fredda, 0 con cache calda.
2. Test: `render_to_string('500.html')` non solleva eccezioni e non tocca il DB
   (usare `assertNumQueries(0)`).
3. Manuale: `DEBUG=False` in locale (`python manage.py runserver --insecure`),
   visitare un URL inesistente e verificare resa grafica di 404; forzare un'eccezione
   in una view di test per vedere la 500.
4. `python manage.py test` — suite verde.
