# Codex prompt PERF P0 — Riparare la cache della homepage e le impression banner

## Contesto

Progetto Django 5.2.5 in `carpi_news/`. La homepage ha `@cache_page(300)` ma la cache è
**di fatto rotta**, e il conteggio impression dei banner è sbagliato.

**Causa esatta identificata** (`home/views.py:53-166`):

1. La view `home()` è decorata con `@cache_page(300)` + `@vary_on_headers('X-Requested-With')`
   (righe 53-54), ma dentro la view si **scrive `request.session`** per deduplicare le
   impression banner (righe 159-163: `request.session[session_key] = True`).
   Quando la sessione viene toccata, `SessionMiddleware` aggiunge `Vary: Cookie` alla
   risposta → la cache diventa frammentata per combinazione di cookie (sessionid, csrftoken,
   cookie GA…) → di fatto ogni visitatore ha la sua copia → cache quasi inutile.
2. Le impression vengono incrementate **solo su cache miss**: se la pagina è servita dalla
   cache la view non gira e i banner mostrati non contano l'impression → **conteggi
   sottostimati** (e i banner sono fatturati a visibilità!).
3. 4× `banner.save(update_fields=['impressions'])` in loop per ogni richiesta non cacheata
   (riga 162) — write non atomici (race condition con richieste concorrenti).
4. I banner vengono filtrati per aspect ratio **in Python** dopo aver caricato tutta la
   queryset in memoria (righe 132-144).
5. La query delle categorie per il menu è ripetuta identica e mai cacheata in **10+ view**:
   `get_published_articles_query().values_list('categoria', flat=True).distinct()`
   alle righe 175, 370, 434, 578, 640, 668, 753, 874, 1309, 1456 di `home/views.py`.

**Pattern già esistente da riusare:** `short_link_redirect` (`home/views.py:1634-1658`)
fa già conteggio click corretto: `update(clicks_count=F('clicks_count') + 1)` atomico +
dedup via cache con chiave `pk:ip:hash(user_agent)` TTL 60s. Replicare questo pattern.

## Azioni

### 1. Endpoint beacon per le impression

Nuova view in `home/views.py` (o `admin_panel/views.py`, dove vive il modello `Banner`):

```python
@require_POST
def banner_impression(request, banner_id):
    """Beacon JS: conta un'impression banner, dedup via cache, atomico."""
    from django.core.cache import cache
    from django.db.models import F
    from admin_panel.models import Banner

    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'wget', 'python-requests']
    if any(k in user_agent for k in bot_keywords):
        return HttpResponse(status=204)

    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
    cache_key = f"banner_impr:{banner_id}:{ip}:{hash(user_agent[:80])}"
    if not cache.get(cache_key):
        updated = Banner.objects.filter(pk=banner_id, status='active').update(
            impressions=F('impressions') + 1
        )
        if updated:
            cache.set(cache_key, True, 600)
    return HttpResponse(status=204)
```

- URL: `path('banner/impression/<int:banner_id>/', ...)` in `carpi_news/urls.py`.
- Esente da CSRF (`@csrf_exempt`) perché chiamato via `navigator.sendBeacon`/fetch senza
  form; non restituisce dati, solo 204.
- Nel template della griglia homepage: dopo il load, un piccolo script raccoglie gli id
  dei banner renderizzati (es. `data-banner-id` sui div banner) e fa
  `navigator.sendBeacon('/banner/impression/<id>/')` per ciascuno (con fallback
  `fetch(..., {method:'POST', keepalive:true})`).

### 2. Pulire la view `home()`

In `home/views.py:146-166`:
- rimuovere il blocco bot-check + incremento impression + scritture sessione
  (righe 146-166): ora lo fa il beacon
- la view non deve più toccare `request.session` in alcun percorso → verificare che
  nessun'altra riga della view (o dei template tag chiamati, vedi
  `admin_panel/templatetags/banner_tags.py`) acceda alla sessione

### 3. Filtrare i banner in DB

Sostituire il blocco righe 132-144:
- spostare il filtro aspect ratio in queryset: i campi `image_vertical_width` e
  `image_vertical_height` sono sul modello, quindi
  `.exclude(image_vertical_height=0).annotate(...)` con `ExpressionWrapper` /
  confronto `image_vertical_width__lte=F('image_vertical_height') * 2`
- niente `list()` anticipato: lasciare la queryset lazy e materializzarla una volta sola

### 4. Categorie del menu: context processor cacheato

In `home/context_processors.py` aggiungere:

```python
def categorie_menu(request):
    from django.core.cache import cache
    categorie = cache.get('categorie_menu')
    if categorie is None:
        from .views import get_published_articles_query
        raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
        categorie = []
        has_rubriche = False
        for cat in sorted(raw):
            if cat in ['Editoriale', "L'Eco del Consiglio"]:
                if not has_rubriche:
                    categorie.append('Rubriche')
                    has_rubriche = True
            else:
                categorie.append(cat)
        cache.set('categorie_menu', categorie, 3600)
    return {'categorie_disponibili': categorie}
```

- Registrarlo in `settings.py` → `TEMPLATES.OPTIONS.context_processors`.
- Invalidazione: in `home/signals.py`, su `post_save`/`post_delete` di `Articolo`,
  `cache.delete('categorie_menu')`.
- Rimuovere il calcolo duplicato dalle 10 view (`home/views.py` righe 175, 370, 434,
  578, 640, 668, 753, 874, 1309, 1456) e dai relativi context — i template continuano
  a usare la variabile `categorie_disponibili`, che ora arriva dal context processor.
- Attenzione: alcune view raggruppano già 'Rubriche' con la stessa logica — verificare
  che tutte le 10 occorrenze producano la stessa lista; se una view ha logica diversa
  (es. non raggruppa), segnalarlo nel riepilogo invece di forzare l'uniformità.

## Vincoli

- Il layout della griglia (8 articoli + 4 banner, posizioni mai adiacenti, mai 0 o 11)
  **non cambia**. È accettato che le posizioni "random" restino congelate per i 300s di
  cache della pagina.
- Le impression contate dal beacon sostituiscono il vecchio conteggio: nessuna doppia
  contabilizzazione.
- Il filtro bot resta equivalente (stessa lista di keyword).
- Non cambiare TTL o decoratori di cache di altre view.

## Verifica

1. Test: la risposta di `/` **non deve contenere `Vary: Cookie`** e non deve creare
   sessioni (asserire `request.session.modified is False` o assenza di `Set-Cookie`
   per un client anonimo).
2. Test beacon: POST incrementa `impressions` di 1 (atomico), secondo POST entro il TTL
   non incrementa (dedup), user-agent bot non incrementa, banner inesistente → 204 senza
   errori.
3. Test context processor: una sola query per popolare la cache, zero query al secondo
   render; dopo `post_save` di un Articolo la cache si invalida.
4. `assertNumQueries` sulla home: fissare il numero atteso di query (deve scendere
   rispetto a prima).
5. `python manage.py test` — tutta la suite passa.
