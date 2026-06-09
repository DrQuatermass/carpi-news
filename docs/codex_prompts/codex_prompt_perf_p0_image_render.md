# Codex prompt PERF P0 — Eliminare I/O di rete e disco dal render delle immagini

## Contesto

Progetto Django 5.2.5 in `carpi_news/`. Il problema di performance più grave del sito:
i metodi del modello `Articolo` che restituiscono gli URL delle immagini fanno
**I/O sincrono durante il rendering dei template**.

**Causa esatta identificata:**

1. `Articolo.get_image_url()` (`home/models.py:353-448`):
   - `Path(...).exists()` su disco per `foto_upload` (riga 364) e per `foto` locale (riga 393)
   - **`requests.head(validated_url, timeout=1, allow_redirects=True)` verso URL esterni**
     (riga 436), con cache 24h per URL ma comunque rete nel ciclo richiesta al primo hit
2. `Articolo.get_social_image_url()` (`home/models.py:449-577`): duplica la stessa logica,
   incluso un altro `requests.head` (~riga 570)
3. `Articolo.get_newsarticle_image_urls()` (`home/models.py:322-340`): chiama
   `ensure_article_image_variants(self, force=True)` (da `home/image_variants.py`) se
   mancano varianti → **resize/conversione WebP con Pillow durante la richiesta**

**Impatto:** la homepage renderizza 8+ articoli e per ciascuno i template chiamano
`get_image_url` più volte nello stesso tag (filtri `proxy_url` e `image_srcset` di
`home/templatetags/webp_images.py:74,165` — vedi `home/templates/homepage.html` righe
~491, 522, 592, 603). Risultato: fino a 16+ chiamate al metodo per pageview, ciascuna
con stat su disco e potenziale richiesta HTTP. Anche il feed RSS (`home/feeds.py`) e la
condivisione social usano questi metodi.

## Obiettivo

`get_image_url()` e `get_social_image_url()` devono diventare **funzioni pure**: solo
costruzione di stringhe URL a partire dai campi del modello. Zero `requests`, zero
`Path.exists()`, zero generazione varianti. La validazione si sposta al momento
dell'ingest (quando il monitor/salvataggio scrive l'articolo).

## Azioni

### 1. Nuovo campo `foto_valida` su `Articolo`

In `home/models.py`:

```python
foto_valida = models.BooleanField(
    default=True,
    help_text='False se la verifica dell\'URL esterno in foto è fallita (validata all\'ingest, non al render)'
)
```

Genera la migration.

### 2. Spostare la validazione all'ingest

Crea `home/image_validation.py` con una funzione `validate_articolo_images(articolo) -> bool`
che contiene la logica oggi dentro `get_image_url`:
- normalizzazione URL (doppi slash, spazi → quote) — questa parte resta anche nel metodo
  di render perché è pura manipolazione di stringhe
- `requests.head(timeout=3)` per URL esterni non nei `trusted_domains`
- `Path.exists()` per `foto_upload` e `foto` locali
- aggiorna `articolo.foto_valida` (e se il file locale non esiste, azzera il campo rotto
  facendo fallback su quello valido) con `save(update_fields=[...])`

Chiamala da `home/signals.py` in un handler `post_save` di `Articolo`, **in un thread
in background** (stesso pattern già usato in `signals.py` da
`_notify_search_engines_background`), solo quando `foto` o `foto_upload` cambiano
(usa `update_fields` o confronto con cache per evitare loop di save).

### 3. Rendere puri i metodi di render

In `get_image_url()` (`home/models.py:353-448`):
- rimuovere gli import di `os`/`Path` e tutti i `Path(...).exists()`
- rimuovere il blocco `requests.head` + cache (righe 422-447): al suo posto,
  `return validated_url if self.foto_valida else fallback_image`
- mantenere identica la normalizzazione stringhe (doppi slash, spazi, prefisso
  `SITE_URL` per path locali) e il fallback `static('home/images/portico_logo_nopayoff.webp')`

Stessa cosa in `get_social_image_url()` (rimuovere il `requests.head` ~riga 570;
mantenere la logica PNG/JPG vs WebP che è pura manipolazione di path).

Memoizza il risultato per istanza, così `proxy_url` + `image_srcset` nello stesso tag
non ricalcolano:

```python
def get_image_url(self):
    if not hasattr(self, '_image_url_cache'):
        self._image_url_cache = self._build_image_url()
    return self._image_url_cache
```

### 4. Generazione varianti fuori dal render

In `get_newsarticle_image_urls()` (`home/models.py:322-340`): rimuovere la chiamata a
`ensure_article_image_variants(self, force=True)`. Se le varianti mancano, restituire
l'immagine principale come unica voce (comportamento degradato accettabile).

Spostare la generazione varianti nell'handler `post_save` del punto 2 (dopo la
validazione, in background) — oppure nell'evento di approvazione se esiste un signal
dedicato. Le varianti devono esistere prima che l'articolo venga condiviso/indicizzato,
non essere create dal primo visitatore.

### 5. Management command una-tantum

Crea `home/management/commands/validate_article_images.py`:
- itera tutti gli `Articolo` con `foto` o `foto_upload` valorizzati
- chiama `validate_articolo_images()` (sincrono, con rate limit ~2 req/sec verso
  lo stesso dominio)
- genera anche le varianti mancanti per gli articoli approvati
- opzioni: `--dry-run` (solo report), `--only-broken` (riconvalida solo `foto_valida=False`)
- stampa un riepilogo: quanti validati, quanti rotti, quanti corretti

## Vincoli

- Gli URL prodotti da `get_image_url`/`get_social_image_url` per articoli con immagini
  valide devono restare **byte-identici** a prima (la normalizzazione stringhe non cambia).
- Il fallback resta `portico_logo_nopayoff.webp` (e `.png` per il social).
- Non toccare `home/templatetags/webp_images.py` né i template: l'interfaccia dei metodi
  non cambia.
- `trusted_domains` (`voce.it`, `ombradelportico.it`) continuano a saltare la validazione
  anche all'ingest.

## Verifica

1. `python manage.py test` — tutta la suite passa (`home/tests.py` ha test sulle immagini).
2. Nuovo test in `home/tests.py`: con `unittest.mock.patch('requests.head')`, renderizza
   la homepage e il dettaglio articolo e asserisci che **`requests.head` NON venga mai
   chiamato** e che nessun metodo immagine tocchi il filesystem (patch anche
   `pathlib.Path.exists` e asserisci zero chiamate dai metodi del modello).
3. Test snapshot: per 3-4 articoli fixture (foto esterna valida, foto esterna rotta con
   `foto_valida=False`, foto_upload locale, nessuna foto) confronta l'output dei metodi
   prima/dopo il refactor.
4. `python manage.py validate_article_images --dry-run` su un dump del DB di produzione:
   il report deve essere plausibile (pochi % di immagini rotte).
