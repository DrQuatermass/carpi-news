# Addendum P0 — Protezione articoli indicizzati/popolari

Da applicare ASSIEME a `codex_prompt_seo_p0_slug.md`.

## Contesto

Per evitare di rinominare articoli che potrebbero essere indicizzati
attivamente e ricevere traffico organico, il management command
`fix_malformed_slugs` deve avere una protezione default: skippa articoli
con un certo numero di views (proxy per "è probabile che sia indicizzato
e generi traffico").

## Modifica al management command

In `home/management/commands/fix_malformed_slugs.py`, applica queste
modifiche rispetto al prompt P0 base:

### 1. Docstring del modulo

Sostituisci la docstring iniziale con:

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
```

### 2. Aggiungi argomenti al parser

In `add_arguments(self, parser)` aggiungi DOPO `--limit`:

```python
parser.add_argument(
    '--views-threshold', type=int, default=50,
    help='Skippa articoli con piu di N views (proxy per indicizzati). Default 50.'
)
parser.add_argument(
    '--include-popular', action='store_true', default=False,
    help='Forza rename anche degli articoli sopra views-threshold.'
)
```

### 3. Logica di skip nel ciclo principale

Nel ciclo `for art in qs.iterator(...)`, SUBITO dopo il check
`if not bad: continue`, aggiungi:

```python
# PROTEZIONE: skip articoli popolari (probabile indicizzazione attiva)
if not opts['include_popular'] and art.views > opts['views_threshold']:
    skippati_popolari += 1
    continue
```

E prima del ciclo inizializza:

```python
skippati_popolari = 0
```

### 4. Output finale

Alla fine, prima di `if opts['dry_run']:`, aggiungi:

```python
if skippati_popolari > 0:
    self.stdout.write(self.style.WARNING(
        f'\nProtezione attiva: {skippati_popolari} articoli con slug malformato '
        f'ma views > {opts["views_threshold"]} sono stati skippati '
        f'(usa --include-popular per forzare il rename).'
    ))
```

## Razionale

Il campo `views` esiste gia' nel modello `Articolo` (default 0,
incrementato ad ogni visualizzazione). Articoli con views basse sono
con altissima probabilita' NON indicizzati o comunque non ricevono
traffico — quindi il rename con redirect 301 e' a rischio zero.

Articoli con views alte sono potenzialmente in classifica e ricevono
traffico: meglio analizzarli caso per caso prima di rinominarli (anche
se il 301 protegge in teoria, la transizione comporta sempre un breve
periodo di volatilita').

## Comportamento finale atteso

Su 4.900 articoli totali:
- ~3.000-4.000 con slug OK → ignorati dal command
- ~500-800 con slug malformato e views basse → rinominati con 301 (sicuro)
- ~50-100 con slug malformato ma views alte → skippati per protezione
  (puoi vedere quali sono e decidere a mano con `--include-popular`)

## Cosa NON cambia

Tutta la logica del prompt P0 base resta valida. Questa e' solo una
salvaguardia in piu'.
