# Codex prompt CLEANUP P0 — Dead code e igiene del repository

## Contesto

Progetto Django 5.2.5: repo root `C:\news` (git), progetto Django in `carpi_news/`.
Cresciuto in vibe coding: ci sono moduli morti mai importati, script di
test/esperimenti sparsi nella root, file temporanei e un `.gitignore` con una riga
malformata. Audit già fatto: l'elenco sotto è verificato, ma **prima di ogni delete
riconferma con grep che il file non sia importato/richiamato da nessuna parte**
(inclusi cron esterni: se un file sembra uno script operativo, spostalo in archivio
invece di cancellarlo).

## Azioni

### 1. Moduli Python morti (verificati: zero import)

Eliminare:
- `carpi_news/home/carpi_calcio_monitor.py` — sostituito dal sistema universale
- `carpi_news/home/youtube_transcript.py` — sostituito da `universal_news_monitor.py`
- `carpi_news/home/social_sharing_backup.py` — backup pre-refactor di `social_sharing.py`
- `carpi_news/home/management/commands/monitor_playlist.py` — si auto-dichiara obsoleto
  nel docstring

Prima di ciascuno: `grep -rn "<nome_modulo>" --include="*.py"` su tutto il repo
(senza estensione, es. `carpi_calcio_monitor`) e verifica zero risultati fuori dal
file stesso.

### 2. Script sparsi nella root `C:\news`

Creare `archive/` nella root (gitignorata, vedi punto 5) e spostarci dentro:
- `test_ariston_image.py`, `test_banner_conversion.py`, `test_chatbot.py`,
  `test_chatbot_extended.py`, `test_cinema_final.py`, `test_cinema_scraping.py`,
  `test_enzo_biagi_prompt.py`, `test_spacecity.py`, `test_spacecity_oraris.py`,
  `test_threading.py`, `test_tracking_system.py`, `test_url_normalization.py`
- `debug_search.py`, `extract_eco_simple.py`, `extract_eco_video.py`
- `archive_test_scripts.py`, `generate_email_logo.py`
- `articolo_2699.txt`, `SEO_Report_OmbraDelPortico_2026.docx`
- `reel_preview.mp4`, `reel_preview_v2.mp4`

**Attenzione:** `convert_existing_images_to_webp.py` e `cleanup_old_logs.py` potrebbero
essere richiamati da cron in produzione (`cleanup_old_logs.py` è citato in CLAUDE.md
come comando operativo) → NON spostarli; lasciali in root.

Eliminare del tutto:
- `venv.broken-20260429000911/` (vecchio venv rotto)

Spostare i prompt Codex esistenti dalla root a `docs/codex_prompts/` (la cartella
esiste già): `codex_prompt_google_news_seo.md`, `codex_prompt_google_news_seo_v2.md`,
`codex_prompt_instagram_dm_pipeline.md`, `codex_prompt_seo_p0_fix_validatore.md`,
`codex_prompt_seo_p0_slug.md`, `codex_prompt_seo_p0_slug_addendum.md`,
`codex_prompt_seo_p1_author_eeat.md`, `codex_prompt_seo_p2_quality_pipeline.md`,
`codex_prompt_social_links.md`.

### 3. File temporanei in `carpi_news/`

Eliminare:
- `carpi_news/.fuse_hidden*` (artefatti filesystem Linux)
- `carpi_news/nul` (artefatto Windows)
- `carpi_news/temp_transcript.txt`, `carpi_news/transcript_RMei2kRiqWE.txt`
- `carpi_news/runserver.err.log`, `carpi_news/runserver.out.log`,
  `carpi_news/test_output.txt` (se presenti)

### 4. `.gitignore` root

- **Correggere la riga 72 malformata**: due pattern fusi senza newline —
  `get_facebook_*.pycarpi_news/home/management/commands/send_emails_ses.py`
  deve diventare due righe:
  ```
  get_facebook_*.py
  carpi_news/home/management/commands/send_emails_ses.py
  ```
- Aggiungere pattern:
  ```
  archive/
  venv.broken-*/
  .fuse_hidden*
  nul
  transcript_*.txt
  temp_transcript.txt
  runserver.*.log
  test_output.txt
  reel_preview*.mp4
  ```

### 5. `requirements.txt` (`carpi_news/requirements.txt`)

- Rimuovere `bs4==0.0.2` (è solo un alias-stub di `beautifulsoup4`, già presente).
- Verificare `openai==1.58.1`: grep `import openai` / `from openai` — se compare solo
  in `home/api_usage_tracker.py`, controlla se quel code path è raggiungibile (config
  o env che lo attiva). Se è davvero un fallback mai attivato, rimuovi import e
  dipendenza; se è usato, lascialo e annota nel riepilogo.

## Vincoli — NON toccare

- **Le migration**: in particolare le due `0052_*` duplicate nel numero NON sono un
  errore (`0053_social_link_tracking` dipende esplicitamente da entrambe, il grafo è
  valido). Nessun rename, nessuna merge migration.
- `home/monitor_configs.py` e `home/monitor_manager.py`: legacy ma **ancora importati**
  da `import_monitors.py`, `fix_broken_images.py`, `manage_monitors.py`. Restano.
- `universal_news_monitor.py` (3817 righe): non splittare, non rifattorizzare.
- Nessuna modifica funzionale al codice applicativo: questo prompt è solo
  delete/move/gitignore/requirements.

## Verifica

1. `python manage.py check` e `python manage.py test` dalla cartella `carpi_news/` —
   verdi.
2. Avvio `python manage.py runserver` senza errori di import (con
   `AUTO_START_MONITORS=False`).
3. `git status`: nessun file utile cancellato per errore; i file spostati risultano
   come rename/delete coerenti; i temporanei non compaiono più grazie al `.gitignore`.
4. `grep -rn "social_sharing_backup\|carpi_calcio_monitor\|youtube_transcript\b\|monitor_playlist"`
   → zero risultati nel codice attivo.
