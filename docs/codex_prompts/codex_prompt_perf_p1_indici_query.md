# Codex prompt PERF P1 — Indici DB mancanti e query inefficienti

## Contesto

Progetto Django 5.2.5 in `carpi_news/`, DB SQLite (PostgreSQL opzionale via
`DATABASE_URL`). Audit performance: mancano alcuni indici su filtri usati in ogni
richiesta, alcune aggregazioni sono fatte in Python invece che in DB, e la pagina
cinema fa 4 fetch HTTP sequenziali nella view.

**Stato attuale verificato:**

- `Articolo.Meta.indexes` (`home/models.py:639-644`) ha già:
  `(approvato, -data_pubblicazione)`, `(categoria, approvato, -data_pubblicazione)`, `(slug)`.
- `get_published_articles_query()` filtra anche su `is_pubbliredazionale` e
  `payment_status` → nessun indice li copre.
- `link_in_bio` (`home/views.py:1693-1697`) filtra `SocialPublicationLog` su
  `platform__in=..., success=True, published_at__gte=...` — gli indici esistenti del
  modello (`home/models.py:674-715`) coprono `(platform, success, -updated_at)` ma non
  `published_at`.
- CTR massimo banner calcolato in loop Python (`home/views.py:736-740`).
- `programmazione_cinema()` (`home/views.py:919-1307`, cache 1800s): 4
  `requests.get(timeout=10)` **sequenziali** verso i siti dei cinema (righe ~975, 1050,
  1144, 1216) → su cache miss il visitatore aspetta fino a 40s nel caso peggiore.
- `articoli_correlati` (`home/views.py:383-387`): carica oggetti `Articolo` completi
  per renderizzare solo card (titolo, slug, foto, categoria, data).

## Azioni

### 1. Indici nuovi

In `home/models.py`:

- `Articolo.Meta.indexes` — aggiungere:
  ```python
  models.Index(fields=['is_pubbliredazionale', 'approvato', 'payment_status'],
               name='idx_articolo_publi_pub'),
  ```
  e, visto che la homepage filtra `spotlight=True` a ogni hit:
  ```python
  models.Index(fields=['spotlight', '-data_pubblicazione'],
               name='idx_articolo_spotlight',
               condition=Q(spotlight=True)),
  ```
  (indice parziale: supportato sia da SQLite che da PostgreSQL).
- `SocialPublicationLog.Meta.indexes` — aggiungere:
  ```python
  models.Index(fields=['platform', 'success', 'published_at'],
               name='idx_socialpub_published'),
  ```

Genera le migration con `makemigrations`. **Non toccare le migration esistenti**
(in particolare le due `0052_*`: il grafo è corretto, `0053` dipende da entrambe).

### 2. CTR banner in DB

Sostituire il loop in `home/views.py:736-740` con un'aggregazione:

```python
from django.db.models import F, FloatField, ExpressionWrapper, Max

ctr_max = Banner.objects.filter(impressions__gt=0, clicks__gt=0).aggregate(
    m=Max(ExpressionWrapper(F('clicks') * 100.0 / F('impressions'),
                            output_field=FloatField()))
)['m'] or 0
ctr_max = round(ctr_max, 1)
```

### 3. Scraping cinema: parallelo + stale-on-error

In `programmazione_cinema()` (`home/views.py:919-1307`):

1. Estrarre le 4 routine di scraping (Eden, Ariston, Corso, Space City) in funzioni
   separate `_scrape_<nome>() -> dict` (se non già separate).
2. Eseguirle in parallelo con `concurrent.futures.ThreadPoolExecutor(max_workers=4)`;
   ogni future con il suo try/except — il fallimento di un cinema non blocca gli altri.
3. Cache a due livelli, pattern stale-on-error:
   - chiave "fresh" con TTL 21600 (6h): se presente, servire subito
   - chiave "stale" con TTL 7 giorni, scritta insieme alla fresh
   - su cache miss: scraping parallelo; se un cinema fallisce, riusare i suoi dati
     dalla copia stale invece di mostrarlo vuoto
4. Mantenere il decoratore `@cache_page` esistente se presente (la cache interna è
   un secondo livello che protegge dal cold start).

### 4. Query correlati più leggere

In `home/views.py:383-387` (`articoli_correlati`) aggiungere
`.only('id', 'titolo', 'slug', 'foto', 'foto_upload', 'categoria', 'data_pubblicazione', 'sommario')`
— verificare nel template `dettaglio_articolo.html` (sezione related, ~righe 789-801)
quali campi sono effettivamente usati e includerli tutti per evitare query di deferred
loading. Applicare lo stesso pattern alle altre liste di card se ne trovi senza `.only()`
(es. query in `chatbot_results`, `calendario_eventi`).

## Vincoli

- Output HTML identico: solo le query cambiano, non i dati renderizzati.
- Nessuna modifica al comportamento della pagina cinema lato utente, a parte tempi
  di risposta migliori e maggiore resilienza ai siti dei cinema irraggiungibili.
- Le migration nuove devono essere additive (solo `AddIndex`).

## Verifica

1. `python manage.py makemigrations --check --dry-run` non deve segnalare altro dopo le
   nuove migration; `python manage.py migrate` pulito su un DB di sviluppo.
2. `python manage.py test` — suite verde.
3. Test per il CTR: fixture con 2-3 banner, il valore aggregato deve coincidere col
   vecchio calcolo Python.
4. Test cinema: mock delle 4 fetch, una che solleva `requests.Timeout` → la pagina
   renderizza comunque con i dati stale per quel cinema; tempo totale dominato dalla
   fetch più lenta, non dalla somma.
5. `assertNumQueries` su dettaglio articolo: il numero non deve aumentare.
