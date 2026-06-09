# Codex prompt P0-FIX — Bug nel validatore is_slug_malformed

## Contesto

Il management command `fix_malformed_slugs --dry-run` ha rilevato 333 slug
malformati. Pero' alcuni NEW slug proposti sono ANCORA troncati a meta'
parola:

```
OLD: la-posta-di-babbo-natale-fa-tappa-a-carpi-lufficio-piu-magico-dellanno-apre-in-piazza-martiri
NEW: la-posta-di-babbo-natale-fa-tappa-a-carpi-lufficio-piu-mag  ← termina con "mag"

OLD: cinque-coppie-in-cerca-di-guai-al-troisi-arriva-la-commedia-che-vi-fara-ridere-fino-alle-lacrime
NEW: cinque-coppie-in-cerca-di-guai-al-troisi-arriva-la-comme  ← termina con "comme"

OLD: il-teatro-che-scuote-le-coscienze-lo-sapevano-tutti-sbarca-a-carpi-per-parlare-di-violenza-con-...
NEW: il-teatro-che-scuote-le-coscienze-lo-sapevano-tutti-sbarc  ← termina con "sbarc"
```

**Due bug distinti**:

### Bug A — `is_slug_malformed` troppo permissivo

In `home/utils.py:69-71` il check sull'ultima parola e':

```python
if len(last) < 3 and not last.isdigit():
    return True, f'ultima-parola-troncata:{last}'
```

`<3` lascia passare parole di esattamente 3 caratteri come "mag", "com",
"vol", "psi", "sbr" — che in italiano sono sillabe troncate, non parole.

Inoltre parole come "comme" (5 char) o "sbarc" (5 char) terminano con
consonante senza essere parole italiane complete.

### Bug B — Titolo gia' corrotto nel DB

Per alcuni articoli vecchi (28 nel run 1), il titolo nel DB e' gia'
troncato (probabilmente da un import passato). Esempio:
`art.titolo = "La posta di Babbo Natale fa tappa a Carpi: l'ufficio piu mag"`.
`safe_slugify` non puo' recuperare un input gia' rotto.

## Azioni richieste

### 1. Indurire `is_slug_malformed`

In `home/utils.py`, sostituisci la funzione `is_slug_malformed` con:

```python
# Parole italiane comuni di 3 caratteri (whitelist per evitare falsi positivi)
_VALID_3CHAR_WORDS = {
    'tre', 'via', 'mio', 'mia', 'tuo', 'tua', 'sua', 'sui', 'lui', 'lei',
    'noi', 'voi', 'con', 'per', 'tra', 'fra', 'gia', 'piu', 'ben', 'mai',
    'qui', 'qua', 'pro', 'eta', 'oro', 'usa', 'art', 'web', 'app', 'tax',
    'job', 'top', 'big', 'pop', 'rap', 'mix', 'box', 'gas', 'sms', 'gps',
    'dvd', 'cd', 'pc', 'tv', 'iva', 'don', 'san', 'oss', 'fbi', 'ceo',
    'cfo', 'cto', 'srl', 'spa', 'eur', 'usd', 'gbp', 'min', 'max', 'sub',
    'set', 'red', 'rai', 'gym', 'pub', 'led',
}

# Parole italiane comuni di 4 caratteri (whitelist supplementare)
_VALID_4CHAR_WORDS = {
    'casa', 'anno', 'cosa', 'vita', 'mano', 'parte', 'modo', 'fine',
    'caso', 'capo', 'mese', 'paese', 'mondo', 'punto', 'fatto', 'gente',
    'soli', 'soli', 'oggi', 'ieri', 'sera', 'sole', 'mare', 'cielo',
    'idea', 'gioia', 'dono', 'foto', 'auto', 'moto', 'film', 'show',
    'gara', 'pace', 'volo', 'rosa', 'fior', 'rosso', 'verde', 'oltre',
    'fino', 'sopra', 'sotto', 'forse', 'mezzo', 'sempre', 'mille', 'cento',
    'venti', 'altre', 'altro', 'altri', 'altra', 'molto', 'molti', 'molte',
    'tanto', 'tanti', 'tutte', 'tutto', 'tutti', 'tutta', 'parte', 'dopo',
    'prima', 'verso', 'circa', 'meno', 'piu', 'meglio', 'peggio', 'ecco',
    'come', 'dove', 'quando', 'perche', 'chi', 'cosa', 'sopra',
    # Numeri/date comuni
    '2023', '2024', '2025', '2026', '2027',
}


def is_slug_malformed(slug: str) -> tuple[bool, str]:
    """
    Ritorna (is_malformed, reason) per uno slug esistente.

    Regole:
    - vuoto o > 90 char = malformato
    - ultima parola < 3 char (non numero) = malformato
    - ultima parola di 3 char NON in whitelist = malformato (sillaba troncata)
    - ultima parola di 4 char NON in whitelist E che termina con consonante
      = malformato (probabile sillaba)
    - qualsiasi parola con cluster consonantici improbabili = malformato
    """
    if not slug:
        return True, 'vuoto'
    if len(slug) > 90:
        return True, f'troppo-lungo-{len(slug)}'

    parts = [p for p in slug.split('-') if p]
    if not parts:
        return True, 'no-parole'

    last = parts[-1].lower()

    # Ultima parola troppo corta
    if len(last) < 3 and not last.isdigit():
        return True, f'ultima-parola-troncata:{last}'

    # Numero/data: sempre OK
    if re.match(r'^\d+$', last):
        pass
    # 3 char: deve essere whitelist
    elif len(last) == 3 and last not in _VALID_3CHAR_WORDS:
        return True, f'ultima-sillaba-3-char:{last}'
    # 4 char: se termina con consonante e non in whitelist, sospetto
    elif len(last) == 4 and last not in _VALID_4CHAR_WORDS:
        if last[-1] not in 'aeiouy':
            return True, f'ultima-sillaba-4-char:{last}'
    # 5 char: se termina con doppia consonante e non e' parola riconoscibile
    elif len(last) == 5 and last[-1] not in 'aeiouy' and last[-2] not in 'aeiouy':
        # Es. "comme", "sbarc"
        return True, f'ultima-sillaba-5-char:{last}'

    # Check cluster consonantici su ogni parola
    for word in parts:
        if re.search(r'\d', word):
            continue
        if len(word) >= 4 and _has_bad_consonant_cluster(word):
            return True, f'cluster-consonanti:{word}'

    return False, ''
```

### 2. Gestione Bug B — fallback alla fonte

In `home/management/commands/fix_malformed_slugs.py`, modifica la logica
di generazione del NEW slug per fare un ulteriore fallback. Sostituisci
il blocco da `source = (art.titolo_seo or '').strip() or art.titolo` fino
a `if bad_new: skipped_unfixable += 1; continue` con:

```python
# Strategia: prova titolo_seo, poi titolo, poi titolo della fonte
candidates = []
if art.titolo_seo and art.titolo_seo.strip():
    candidates.append(('titolo_seo', art.titolo_seo.strip()))
if art.titolo and art.titolo.strip():
    candidates.append(('titolo', art.titolo.strip()))

new_slug = None
new_source = None
for source_name, text in candidates:
    candidate_slug = safe_slugify(text, max_length=75)
    bad_cand, _ = is_slug_malformed(candidate_slug)
    if not bad_cand and candidate_slug != art.slug:
        new_slug = candidate_slug
        new_source = source_name
        break

if not new_slug:
    skipped_unfixable += 1
    continue

new_slug = _unique_slug_for_article(art, new_slug)
if new_slug == art.slug:
    skipped_unfixable += 1
    continue

if opts['limit'] is None or len(problematici) < opts['limit']:
    problematici.append((art, reason, new_slug, new_source))
```

E aggiorna il print loop per mostrare la sorgente:

```python
for art, reason, new_slug, new_source in problematici[:30]:
    self.stdout.write(f'  ID {art.pk}: {reason} (views={art.views or 0}, from={new_source})')
    self.stdout.write(f'    OLD: {art.slug}')
    self.stdout.write(f'    NEW: {new_slug}\n')
```

E in `--apply`:

```python
for art, reason, new_slug, new_source in problematici:
    ...
```

### 3. Test

```
python manage.py fix_malformed_slugs --dry-run --limit 30
python manage.py fix_malformed_slugs --dry-run --limit 30 --include-popular
```

L'aspettativa:
- Run di default (views ≤ 50): probabilmente la maggior parte dei 28
  vecchi candidati viene ora skippata come "ancora malformato" (perche'
  il titolo nel DB e' gia' rotto e il NEW slug risulterebbe pure rotto).
  Resta una manciata di articoli rinominabili in modo pulito.
- Run con `--include-popular`: i 297 popolari restano candidati validi
  con NEW slug perfetti (sono articoli recenti con `titolo_seo`).

### 4. Output atteso

- Diff completo
- Output del dry-run di default → conteggio "skipped_unfixable" salira'
  significativamente (idealmente i 28 di prima diventano skippati)
- Output del dry-run con `--include-popular` → 297 candidati con slug
  perfetti
- Verifica REPL Django che `is_slug_malformed("la-posta-di-babbo-natale-fa-tappa-a-carpi-lufficio-piu-mag")`
  ritorna `(True, 'ultima-sillaba-3-char:mag')`

## Cosa NON toccare

- `safe_slugify` (funziona correttamente, il problema era il validatore)
- `ArticoloRedirect` (modello OK)
- Logica `_unique_slug_for_article` (OK)
- Argomenti del command (gia' OK con `--views-threshold`, `--include-popular`)
