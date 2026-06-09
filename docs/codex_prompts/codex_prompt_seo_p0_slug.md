# Codex prompt P0 — Fix slug malformati + modello ArticoloRedirect

## Contesto

Progetto Django 5.2.5 in `carpi_news/`. Search Console ha 1.889 pagine
"Scansionate ma non indicizzate" da Google a causa di slug malformati.

**Causa esatta identificata** (`home/models.py:193-234`):
- Lo slug viene generato da `self.titolo` (titolo lungo della redazione, max 200 char)
- `slugify(titolo)[:80]` tronca byte-a-byte, spesso in mezzo a una parola
- Esempi reali rilevati: `tortellini-rock-quando-pasta-diventa-rivoluzione-silenziosa`,
  `camminare-insieme-non-sentirsi-soli-modena-apre-porte-caregiver-familiari-tre-gi`
  (`tre-gi` = troncatura di `tre-giorni`)

**Ma c'e' gia' `titolo_seo`**, generato dall'AI con prompt esplicito:
"MAX 60 caratteri, SOGGETTO + LUOGO + AZIONE, parole chiave Google".
Esempio reale: `"AIMAG Carpi: Morelli chiede trasparenza sulle nomine"` (51 char).

Lo slug deve nascere da `titolo_seo` se presente (e' gia' SEO-ready),
con fallback al `titolo` solo se `titolo_seo` e' vuoto.

Convalida richiesta a Google l'11 mag, fallita il 12 mag. Strategia:
generare slug puliti per gli articoli problematici esistenti e fare
redirect 301 dai vecchi URL ai nuovi.

## Azioni

### 1. Nuovo modello `ArticoloRedirect`

In `home/models.py`, dopo `Articolo`:

```python
class ArticoloRedirect(models.Model):
    """Redirect 301 da vecchio slug articolo a nuovo slug."""
    old_slug = models.SlugField(max_length=100, unique=True, db_index=True)
    new_slug = models.SlugField(max_length=100, db_index=True)
    articolo = models.ForeignKey(
        'Articolo', on_delete=models.CASCADE, related_name='redirects'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(
        max_length=120, default='slug-malformato',
        help_text='Motivo del rename'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.old_slug} -> {self.new_slug}"
```

Genera la migration.

### 2. View redirect

In `home/views.py`, all'inizio di `dettaglio_articolo(request, slug)`:

```python
from django.http import HttpResponsePermanentRedirect
from .models import Articolo, ArticoloRedirect

def dettaglio_articolo(request, slug):
    # Prima cerca un redirect 301
    try:
        redirect_obj = ArticoloRedirect.objects.select_related('articolo').get(
            old_slug=slug
        )
        return HttpResponsePermanentRedirect(
            f"/articolo/{redirect_obj.new_slug}/"
        )
    except ArticoloRedirect.DoesNotExist:
        pass

    # Logica esistente
    articolo = get_object_or_404(Articolo, slug=slug, approvato=True)
    ...
```

### 3. Utility per slug puliti

In `home/utils.py` aggiungi:

```python
import re
from django.utils.text import slugify

# Cluster consonantici leciti in italiano
_VALID_CLUSTERS = {
    'sc', 'sp', 'st', 'sb', 'sd', 'sf', 'sg', 'sl', 'sm', 'sn', 'sr', 'sv',
    'pr', 'br', 'tr', 'dr', 'cr', 'gr', 'fr', 'pl', 'bl', 'fl', 'gl', 'cl',
    'gn', 'gli', 'ch', 'gh', 'qu', 'mb', 'mp', 'nt', 'nd', 'nc', 'ng',
    'rc', 'rd', 'rg', 'rl', 'rm', 'rn', 'rp', 'rs', 'rt', 'rv',
    'ld', 'lg', 'lt', 'lz', 'lv',
    'tt', 'pp', 'ss', 'rr', 'll', 'nn', 'mm', 'ff', 'cc', 'gg', 'bb', 'dd',
    'zz', 'vv',
    'scr', 'spl', 'spr', 'str', 'sbr', 'sdr', 'sgr',
}


def _has_bad_consonant_cluster(word: str) -> bool:
    word = word.lower()
    i = 0
    while i < len(word):
        j = i
        while j < len(word) and word[j] not in 'aeiouyhàèéìòù':
            j += 1
        cluster = word[i:j]
        if len(cluster) >= 3:
            if cluster[:3] not in _VALID_CLUSTERS and cluster[:2] not in _VALID_CLUSTERS:
                return True
        i = j + 1
    return False


def safe_slugify(text: str, max_length: int = 75) -> str:
    """
    Genera slug pulito troncato a PAROLA INTERA, max max_length char.
    """
    slug = slugify(text or '', allow_unicode=False)
    if len(slug) <= max_length:
        return slug
    truncated = slug[:max_length]
    last_dash = truncated.rfind('-')
    if last_dash > 10:  # almeno 10 caratteri di slug residuo
        truncated = truncated[:last_dash]
    return truncated


def is_slug_malformed(slug: str) -> tuple[bool, str]:
    """
    Ritorna (is_malformed, reason) per uno slug esistente.
    """
    if not slug:
        return True, 'vuoto'
    if len(slug) > 90:
        return True, f'troppo-lungo-{len(slug)}'

    parts = [p for p in slug.split('-') if p]
    if not parts:
        return True, 'no-parole'

    # Ultima parola: deve essere >= 3 char (eccetto numeri/date)
    last = parts[-1]
    if len(last) < 3 and not last.isdigit():
        return True, f'ultima-parola-troncata:{last}'

    # Controlla cluster consonantici improbabili
    for word in parts:
        if len(word) >= 4 and _has_bad_consonant_cluster(word):
            return True, f'cluster-consonanti:{word}'

    return False, ''
```

### 4. Modifica `Articolo.save()` per usare `titolo_seo` come fonte

In `home/models.py:193-234`, sostituisci il blocco `if not self.slug:`:

```python
if not self.slug:
    from .utils import safe_slugify, is_slug_malformed

    # Priorita': titolo_seo (gia' ottimizzato max 70 char) -> titolo
    source = (self.titolo_seo or '').strip() or self.titolo
    base_slug = safe_slugify(source, max_length=75)

    # Verifica che lo slug sia ben formato; altrimenti retry con titolo grezzo
    bad, _reason = is_slug_malformed(base_slug)
    if bad and self.titolo_seo:
        # titolo_seo ha prodotto slug rotto -> riprova col titolo
        base_slug = safe_slugify(self.titolo, max_length=75)

    slug = base_slug

    # Garantisci univocita' con suffisso parola, non data troncata
    n = 1
    while Articolo.objects.filter(slug=slug).exclude(pk=self.pk).exists():
        n += 1
        suffix = f"-{n}"
        slug = base_slug[:75-len(suffix)] + suffix
        # Tronca a parola se necessario
        last_dash_before_suffix = slug[:-len(suffix)].rfind('-')
        if last_dash_before_suffix > 10:
            slug = slug[:last_dash_before_suffix] + suffix

    self.slug = slug[:100]
```

NON cambiare slug di articoli esistenti automaticamente. Solo da
management command (vedi sotto).

### 5. Management command `fix_malformed_slugs`

Crea `home/management/commands/fix_malformed_slugs.py`:

```python
"""
Identifica articoli con slug malformati e propone/applica il rename
con redirect 301 dal vecchio al nuovo.

PROTEZIONE: di default skippa articoli con piu' di N views (sopra una
soglia, indicano traffico organico e probabile indicizzazione attiva).
Usa --include-popular per forzare il rename anche dei popolari.

Uso:
  python manage.py fix_malformed_slugs --dry-run
  python manage.py fix_malformed_slugs --apply
  python manage.py fix_malformed_slugs --apply --limit 50
  python manage.py fix_malformed_slugs --dry-run --views-threshold 100
  python manage.py fix_malformed_slugs --dry-run --include-popular
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from home.models import Articolo, ArticoloRedirect
from home.utils import is_slug_malformed, safe_slugify


class Command(BaseCommand):
    help = 'Identifica articoli con slug malformati e rinomina con redirect 301'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False)
        parser.add_argument('--apply', action='store_true', default=False)
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument(
            '--include-approved-only', action='store_true', default=True,
            help='Limita ad articoli approvati (default True)'
        )
        parser.add_argument(
            '--views-threshold', type=int, default=50,
            help='Skippa articoli con piu' di N views (proxy per indicizzati). Default 50.'
        )
        parser.add_argument(
            '--include-popular', action='store_true', default=False,
            help='Forza rename anche degli articoli sopra views-threshold.'
        )

    def handle(self, *args, **opts):
        if not opts['dry_run'] and not opts['apply']:
            self.stderr.write('Devi specificare --dry-run o --apply')
            return

        qs = Articolo.objects.all()
        if opts['include_approved_only']:
            qs = qs.filter(approvato=True)
        qs = qs.order_by('-data_pubblicazione')

        problematici = []
        for art in qs.iterator(chunk_size=200):
            bad, reason = is_slug_malformed(art.slug)
            if not bad:
                continue

            # Genera nuovo slug da titolo_seo (priorita') o titolo
            source = (art.titolo_seo or '').strip() or art.titolo
            new_slug = safe_slugify(source, max_length=75)
            bad_new, _ = is_slug_malformed(new_slug)
            if bad_new and art.titolo_seo:
                new_slug = safe_slugify(art.titolo, max_length=75)
                bad_new, _ = is_slug_malformed(new_slug)
            if bad_new:
                continue  # entrambe le fonti sono problematiche, skip

            # Garantisci univocita'
            base = new_slug
            n = 1
            while (Articolo.objects.exclude(pk=art.pk).filter(slug=new_slug).exists()
                   or ArticoloRedirect.objects.filter(old_slug=new_slug).exists()):
                n += 1
                suffix = f"-{n}"
                new_slug = base[:75-len(suffix)] + suffix

            if new_slug == art.slug:
                continue  # nessun miglioramento

            problematici.append((art, reason, new_slug))
            if opts['limit'] and len(problematici) >= opts['limit']:
                break

        self.stdout.write(self.style.NOTICE(
            f'\nTrovati {len(problematici)} articoli con slug malformato:\n'
        ))

        for art, reason, new_slug in problematici[:30]:
            self.stdout.write(f'  ID {art.pk}: {reason}')
            self.stdout.write(f'    OLD: {art.slug}')
            self.stdout.write(f'    NEW: {new_slug}\n')

        if len(problematici) > 30:
            self.stdout.write(f'\n... e altri {len(problematici) - 30} articoli.')

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'\nDRY RUN - nessuna modifica applicata.'
            ))
            return

        if opts['apply']:
            with transaction.atomic():
                for art, reason, new_slug in problematici:
                    old_slug = art.slug
                    ArticoloRedirect.objects.get_or_create(
                        old_slug=old_slug,
                        defaults={
                            'new_slug': new_slug,
                            'articolo': art,
                            'motivo': reason,
                        }
                    )
                    art.slug = new_slug
                    art.save(update_fields=['slug'])
            self.stdout.write(self.style.SUCCESS(
                f'\nApplicate {len(problematici)} rinominate.'
            ))
```

### 6. Test

```
python manage.py makemigrations
python manage.py migrate
python manage.py fix_malformed_slugs --dry-run --limit 30
```

NON eseguire `--apply` automaticamente. Riporta il dry-run completo per
review.

## Cosa NON toccare

- `titolo_seo` field: usalo come SOURCE, non modificare la sua generazione
- Logica di polishing AI esistente
- Template articoli (gia' usa titolo_seo per og/twitter/schema)

## Output atteso

- Diff completo
- Migration generata
- Output di `--dry-run` con almeno i primi 30 esempi (old slug -> new slug)
- Numero totale di articoli identificati come malformati
