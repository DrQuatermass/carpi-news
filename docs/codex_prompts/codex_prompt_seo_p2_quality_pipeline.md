# Codex prompt P2 — Validatore titolo_seo, sitemap-news fix, audit noindex/404

## Contesto

Tre fix indipendenti che alzano la qualita' del segnale a Google senza
toccare contenuto esistente.

**Punto chiave**: il sito ha gia' un campo `titolo_seo` generato dall'AI
in `home/universal_news_monitor.py` (vedi line 3220 e prompt AI line
58-60). E' usato per `<title>`, `og:title`, `twitter:title` e schema
`headline`. Quello che la gente vede su Google e' il `titolo_seo`.

Il validatore va applicato al `titolo_seo` (e in seconda istanza al
`titolo` se serve), perche':
- e' quello che appare nei risultati di ricerca
- e' la fonte dello slug (vedi prompt P0)
- e' generato dall'AI con prompt esplicito "MAX 60 caratteri,
  SOGGETTO + LUOGO + AZIONE"

Da applicare DOPO P0 (slug) e P1 (autore). Le tre azioni qui sotto sono
indipendenti tra loro.

## Azioni

### 1. Estendi sitemap-news da 48h a 72h

`home/views.py:471-480` (calcolo `news_lastmod` in `sitemap_index`) e
`home/views.py:536-559` (vista `news_sitemap`): cambia il filtro da 48h
a 72h.

Rimuovi `Editoriale` dall'`exclude` — gli editoriali su cronaca locale
sono pertinenti per Google News e devono entrare nella sitemap. Mantieni
solo l'esclusione di `Cosa fare oggi` che e' un'agenda eventi, non news.

```python
def news_sitemap(request):
    """Vista per la sitemap Google News (ultime 72 ore)"""
    now = timezone.now()
    cutoff_date = now - timedelta(hours=72)
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_date,
        data_pubblicazione__lte=now,
        is_pubbliredazionale=False
    ).exclude(
        titolo__istartswith='test'
    ).exclude(
        categoria='Cosa fare oggi'
    ).order_by('-data_pubblicazione')

    for article in articles:
        article.keywords = article.meta_keywords

    logger.info(f"Generata sitemap news con {len(articles)} articoli")

    template = loader.get_template('sitemap_news.xml')
    context = {'articles': articles}
    return HttpResponse(template.render(context, request), content_type='application/xml')
```

Allinea anche il calcolo `news_lastmod` in `sitemap_index`: 72h e
rimuovi `Editoriale` da `exclude` (lascia solo `Cosa fare oggi`).

### 2. Validatore titolo_seo nel polisher

Lo scopo e' due cose:
1. **A runtime**: quando `universal_news_monitor.py` genera articoli,
   validare il `titolo_seo` ricevuto dall'AI. Se fallisce, fare retry
   con prompt rinforzato. Dopo 3 tentativi, fallback al `titolo`
   troncato.
2. **In coda di polishing**: integrare con `home/content_polisher.py`
   per non dover modificare ogni chiamata AI esistente.

In `home/content_polisher.py` aggiungi una funzione pubblica:

```python
import re
from .utils import _has_bad_consonant_cluster

# Pattern AI-clickbait italiani da rifiutare
_REJECT_PATTERNS = [
    re.compile(r'\brivoluzione\s+silenziosa\b', re.IGNORECASE),
    re.compile(r'^\s*quando\s+(la|il|lo|le|gli|i|una|un)\b', re.IGNORECASE),
    re.compile(r'\bspira\s+mirabilis\b', re.IGNORECASE),
    re.compile(r'\b(svela|svelano|svelato|svelano)\s+(il|la|lo|i|le|gli)\b', re.IGNORECASE),
    re.compile(r'\bnon\s+crederai\b', re.IGNORECASE),
    re.compile(r'\becco\s+(il|la|lo|i|le|gli)\s+motivo\b', re.IGNORECASE),
    re.compile(r'^(?!.*musica)(?!.*concerto)\w+\s+rock\b', re.IGNORECASE),
    re.compile(r'\bin\s+pochi\s+(minuti|secondi)\b', re.IGNORECASE),
    re.compile(r'\bgarantite?\s+(risate|emozioni|sorrisi)\b', re.IGNORECASE),
    re.compile(r'\bemozioni\s+a\s+fior\s+di\s+pelle\b', re.IGNORECASE),
]


def is_natural_italian_title(title: str) -> tuple[bool, str]:
    """
    Ritorna (is_ok, reason). False = titolo problematico.

    Cerca:
    - pattern clickbait noti
    - parole con consonanti improbabili (es. 'metat', 'vesta')
    - lunghezza fuori range (10-130 char per titoli normali, 10-70 per titolo_seo)
    """
    if not title or len(title) < 10:
        return False, 'troppo-corto'
    if len(title) > 130:
        return False, f'troppo-lungo-{len(title)}'

    for pat in _REJECT_PATTERNS:
        m = pat.search(title)
        if m:
            return False, f'pattern-clickbait:{m.group()[:40]}'

    for word in re.findall(r"\b[a-zA-Zàèéìòùç']+\b", title):
        if len(word) >= 5 and _has_bad_consonant_cluster(word):
            return False, f'consonanti-improbabili:{word}'

    return True, ''


def is_natural_seo_title(title: str) -> tuple[bool, str]:
    """
    Validatore specifico per titolo_seo: piu' stretto sulla lunghezza
    (max 70 char per non essere troncato nei risultati Google).
    """
    if not title:
        return False, 'vuoto'  # titolo_seo puo' essere vuoto, ma se c'e' deve essere ok
    if len(title) > 70:
        return False, f'troppo-lungo-per-seo-{len(title)}'
    return is_natural_italian_title(title)
```

### 3. Integra il validatore nel monitor

In `home/universal_news_monitor.py` cerca la riga 3220:

```python
titolo_seo = content_polisher.clean_title_plain(parsed_article.get('titolo_seo', ''))[:70]
```

Sostituisci con un blocco che valida e logga, ma NON blocca il
salvataggio (l'articolo si salva comunque, ma con titolo_seo vuoto se
e' rotto — cosi' il template usa il `titolo` come fallback):

```python
raw_titolo_seo = content_polisher.clean_title_plain(parsed_article.get('titolo_seo', ''))[:70]
if raw_titolo_seo:
    ok, reason = content_polisher.is_natural_seo_title(raw_titolo_seo)
    if ok:
        titolo_seo = raw_titolo_seo
    else:
        self.logger.warning(
            f"[TITOLO_SEO REJECTED] '{raw_titolo_seo}' - {reason} "
            f"- uso titolo regular come fallback"
        )
        titolo_seo = ''  # template fallback su titolo
else:
    titolo_seo = ''
```

Stessa cosa per il `titolo` (riga 3219), ma con validatore meno stretto:

```python
raw_titolo = content_polisher.clean_title_plain(parsed_article.get('titolo', ''))[:200]
ok, reason = content_polisher.is_natural_italian_title(raw_titolo)
if not ok:
    self.logger.warning(
        f"[TITOLO REJECTED] '{raw_titolo}' - {reason}"
    )
    # NON impostare a vuoto - il titolo e' obbligatorio. Logga e continua.
titolo = raw_titolo
```

### 4. Rinforza il prompt AI per evitare clickbait

In `home/universal_news_monitor.py` cerca la stringa del prompt AI
(probabile riga 50-80, contiene `"titolo_seo"` come istruzione). Aggiungi
alla parte del prompt che descrive `titolo_seo`:

```
- "titolo_seo": title tag per Google, MAX 60 caratteri, struttura
  SOGGETTO + LUOGO + AZIONE, deve contenere le parole chiave esatte
  che qualcuno cercherebbe su Google per questa notizia. Includi
  sempre "Carpi" o il nome specifico della persona/luogo.
  STILE: cronaca giornalistica italiana naturale come voce.it,
  sulpanaro.net, modenatoday.it.
  VIETATI: titoli clickbait ("rivoluzione silenziosa", "non crederai",
  "svela il segreto"), frasi che iniziano con "Quando la/il", metafore
  astratte, "X rock" fuori contesto musica, parole inventate o storpiate.
  Esempio buono: "AIMAG Carpi: Morelli chiede trasparenza sulle nomine".
  Esempio CATTIVO: "Tortellini rock quando pasta diventa rivoluzione silenziosa".
  Se non riesci a creare un titolo_seo migliore del titolo, usa "".
```

### 5. Audit noindex e 404

Crea `home/management/commands/audit_indexing.py`:

```python
"""
Audit pagine con noindex e 404 sul sito.

Uso:
  python manage.py audit_indexing
"""
import re
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Audit noindex nei template e 404 negli articoli'

    def handle(self, *args, **opts):
        # 1. Cerca noindex in tutti i template
        self.stdout.write(self.style.NOTICE('\n=== noindex trovati nei template ==='))
        templates_dir = Path(settings.BASE_DIR) / 'home' / 'templates'
        noindex_pattern = re.compile(r'noindex', re.IGNORECASE)
        found_any = False
        for tpl in templates_dir.rglob('*.html'):
            text = tpl.read_text(encoding='utf-8', errors='ignore')
            if noindex_pattern.search(text):
                found_any = True
                lines = [(i+1, l) for i, l in enumerate(text.split('\n'))
                         if noindex_pattern.search(l)]
                self.stdout.write(f'\n{tpl.relative_to(settings.BASE_DIR)}:')
                for ln, l in lines:
                    self.stdout.write(f'  L{ln}: {l.strip()[:120]}')
        if not found_any:
            self.stdout.write('  Nessun noindex trovato nei template.')

        # 2. noindex via header HTTP
        self.stdout.write(self.style.NOTICE('\n=== noindex via header HTTP ==='))
        found_header = False
        for src_dir in [Path(settings.BASE_DIR) / 'home', Path(settings.BASE_DIR) / 'carpi_news']:
            for py in src_dir.rglob('*.py'):
                try:
                    text = py.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue
                if 'X-Robots-Tag' in text or "'noindex'" in text or '"noindex"' in text:
                    found_header = True
                    self.stdout.write(f'  {py.relative_to(settings.BASE_DIR)}')
        if not found_header:
            self.stdout.write('  Nessun header noindex trovato nel codice Python.')

        # 3. Articoli non approvati (404 referenziati da sitemap-archive se erano in archive)
        from home.models import Articolo
        self.stdout.write(self.style.NOTICE('\n=== Articoli problematici ==='))
        non_approvati = Articolo.objects.filter(approvato=False).count()
        self.stdout.write(f'  Articoli non approvati: {non_approvati}')

        non_pagati = Articolo.objects.filter(
            is_pubbliredazionale=True
        ).exclude(payment_status='completed').count()
        self.stdout.write(f'  Pubbliredazionali non pagati: {non_pagati}')

        # 4. Slug duplicati (cause comune di 404 indiretti)
        from django.db.models import Count
        dups = (Articolo.objects.values('slug')
                .annotate(c=Count('slug')).filter(c__gt=1))
        if dups.exists():
            self.stdout.write(self.style.WARNING(
                f'  ATTENZIONE: {dups.count()} slug duplicati'
            ))
            for d in dups[:10]:
                self.stdout.write(f'    {d["slug"]} x{d["c"]}')
        else:
            self.stdout.write('  Slug duplicati: 0')
```

### 6. Test

```
python manage.py check
python manage.py audit_indexing
python manage.py fix_malformed_slugs --dry-run --limit 30  # solo se P0 e' applicato
```

Riporta output completo dei tre comandi.

## Cosa NON toccare

- Schema NewsArticle (gestito in P1)
- Slug logic (gestito in P0)
- Robots.txt
- Indexing notifier (IndexNow funziona)

## Output atteso

- Diff completo
- Output di `audit_indexing` (lista noindex, contatori, slug duplicati)
- Esempi di titoli che il validatore rifiuta (test rapido nel REPL Django)
- Conferma sitemap-news ora a 72h e include Editoriale
