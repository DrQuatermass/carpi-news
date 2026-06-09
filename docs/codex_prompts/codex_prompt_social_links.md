# Prompt per Codex — Link cliccabili su Reel/Story + Smart Link in Bio

## Contesto
Progetto Django 5.2.5 `carpi_news/` (news aggregator "Ombra del Portico", Carpi). App unica `home`. Modello principale `Articolo`. Esiste già `SocialPublicationLog` per tracciare pubblicazioni social. La pipeline social è in `home/social_sharing.py` e orchestra Telegram, Facebook post, Facebook Reel/Story, Instagram post/Story/Reel, Twitter (via RSS+IFTTT).

Generatori video già esistenti:
- `home/facebook_reels.py` — MP4 1080x1920, musica royalty-free, CTA testuale "Leggi su ombradelportico.it", pubblicato via Graph API `/video_stories`
- `home/instagram_story.py` — riusa lo stesso generatore, pubblica STORIES o REELS via Graph API
- `home/instagram_templates.py` — card 1080x1080 con CTA "Leggi nel link in bio"

View esistente: `home.views.link_in_bio` su `/instagram/` mostra gli ultimi 25 articoli (template `link_in_bio.html` + `link_in_bio_cards.html`).

## Limiti piattaforma (rispettare)
- **Instagram Story**: il Link Sticker NON è esposto dalla Graph API (solo app nativa). Workaround obbligatori: QR code stampato nel video + smart Link in Bio + (opzionale) auto-DM via webhook.
- **Instagram Reel**: caption non cliccabile. Workaround: commento auto-pubblicato con link UTM (già esistente — preservarlo) + QR code nel video + CTA verso link in bio.
- **Facebook Reel**: la descrizione PUÒ contenere link cliccabile. Da implementare.
- **Facebook Story**: link cliccabile non supportato via API — usare QR code + link in bio.

## Obiettivo
Aggiungere link cliccabili (o navigabili tramite QR/link in bio) a tutti i Reel e alle Story, e rendere la view link-in-bio "smart" con tracking. NON rompere le pubblicazioni esistenti. Mantenere il codice Django-idiomatico, retro-compatibile con migrazioni.

## Task da implementare (in ordine)

### 1. Helper centralizzato per URL condivisi
Crea `home/share_links.py` con:
- `build_share_url(articolo, platform, medium)` → restituisce URL completo con UTM (`utm_source=<platform>&utm_medium=<medium>&utm_campaign=share`). Usa `Site.objects.get_current()` o `settings.SITE_URL`.
- `build_short_share_url(articolo, platform, medium)` → genera/legge uno short slug (es. `/s/<token>`) collegato all'articolo. Token random 6 char salvato su nuovo modello `ShortLink` (FK a Articolo + platform + medium + token unique + clicks_count).

### 2. Migrazioni
- Nuovo modello `ShortLink` come sopra.
- Estendi `SocialPublicationLog` con:
  - `shared_url` (URLField, blank=True) — URL pubblicato effettivamente
  - `short_link` (ForeignKey a ShortLink, null=True, blank=True)
- Crea migrazione coerente.

### 3. View short link + tracking
- URL pattern `/s/<str:token>/` → `short_link_redirect` view che incrementa `clicks_count`, salva referer e fa `HttpResponseRedirect` all'URL completo con UTM dell'articolo.
- Aggiungi rate limiting basico (cache-based) per non gonfiare contatori da bot.

### 4. Facebook Reel — descrizione con link
In `home/facebook_reels.py`, quando si chiama `/video_stories`:
- Costruisci `description` = titolo + "\n\nLeggi tutto: <short_share_url>" (preferendo short link).
- Passa `description` nei parametri POST. Verifica che la Graph API v24.0 accetti il campo per video stories; in alternativa usa il parametro `text` o pubblica un post collegato. Se Graph rifiuta, fallback su commento al post associato.
- Salva `shared_url` in `SocialPublicationLog`.

### 5. Instagram Reel — caption ottimizzata
In `home/social_sharing.py` (sezione IG Reel):
- Caption = titolo + "\n\n👉 Link nel primo commento e in bio\n\n#carpi #news ..." (hashtag dinamici da categoria articolo).
- Mantieni il commento auto-pubblicato esistente, ma usa lo short link (con UTM `instagram_reel`).
- Salva `shared_url`.

### 6. CTA "Link in bio o ❤️ per riceverlo nei DM" nei template
**Punto centrale**: l'emoji CTA va **stampata direttamente nei template grafici**, non solo nella caption.

In `home/instagram_templates.py`:
- Sostituire l'attuale CTA "Leggi nel link in bio" con un blocco CTA a due righe:
  - Riga 1 (più grande, bold): **"📲 Link in bio"**
  - Riga 2 (stessa grandezza, bold): **"o ❤️ per riceverlo nei DM"**
- Sfondo semi-trasparente (rettangolo arrotondato scuro con opacity ~0.85) per garantire leggibilità su qualsiasi foto sottostante. Padding interno generoso.
- Posizione: terzo inferiore dell'immagine, centrato orizzontalmente, sopra il logo/badge esistenti.
- Font: stesso font system già in uso nel template (mantenere coerenza visiva).
- Esporre parametri per personalizzare il testo (così è facile fare A/B test futuri).

In `home/facebook_reels.py` e `home/instagram_story.py` (overlay video):
- Stamparei la stessa CTA come overlay nei frame finali del video (ultimi 3 secondi) — sostituisce l'attuale "Leggi su ombradelportico.it" / "Leggi nel link in bio".
- Per Facebook Reel, dove il link in descrizione È cliccabile, la CTA può essere ridotta a "👇 Link in descrizione" (vedi sezione 4).
- Per Instagram Story/Reel, CTA piena "📲 Link in bio o ❤️ per riceverlo nei DM".
- Salvare `shared_url` in `SocialPublicationLog`.

**Niente QR code** — viene esplicitamente escluso. La CTA testuale + emoji è sufficiente.

### 8. Webhook Instagram + auto-DM su reazione ❤️
La promessa "❤️ per riceverlo nei DM" sui Reel/Story implica un webhook che riceve le reazioni IG e risponde con un DM contenente il link cliccabile.

**Modello**
- Crea `InstagramAutoDMLog` con: `articolo` (FK), `ig_user_id` (CharField), `trigger_type` (choices: `story_reaction`, `story_reply`, `reel_comment`), `trigger_value` (CharField — emoji o testo che ha fatto match), `media_id` (CharField — IG media id), `short_link` (FK ShortLink, null), `dm_sent` (Bool), `dm_error` (TextField blank), `created_at`.

**Settings**
- Aggiungi a `settings.py`:
  - `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` (per il challenge GET)
  - `INSTAGRAM_PAGE_ACCESS_TOKEN` (Page Access Token long-lived)
  - `INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI = True` — accetta **qualsiasi emoji** come trigger di reazione
  - `INSTAGRAM_AUTO_DM_TEXT_TRIGGERS = ['LINK', 'INFO', 'LEGGI']` — parole chiave nei messaggi/risposte testuali (case-insensitive, configurabile da env)
- Reuse credenziali Graph API già esistenti dove possibile.
- Aggiungere `emoji>=2.10.0` a `requirements.txt` per il rilevamento emoji in messaggi testuali.

**View webhook — binding media_id → articolo specifico**

L'obiettivo è che la ❤️ su una Story specifica scateni un DM con il link **di quell'articolo, non di un altro**. Il binding è garantito dal `media_id` Instagram salvato in `SocialPublicationLog.instagram_media_id`.

- URL `/webhooks/instagram/` (`home/views_webhooks.py`, nuovo file)
- `GET`: gestisce il challenge Meta confrontando `hub.verify_token` con `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` e restituendo `hub.challenge` come plain text.
- `POST`: valida la signature `X-Hub-Signature-256` con HMAC-SHA256 del payload usando `app_secret` (rifiuta con 403 se invalida). Parsing JSON:
  - Per ogni `entry.changes` con `field == 'messages'` o `field == 'message_reactions'`:
    - estrai `sender.id` (utente IG che ha reagito/risposto)
    - estrai `media.id` (la Story/Reel specifica che ha ricevuto la reazione)
    - estrai `reaction.emoji` (se reazione) **oppure** `message.text` (se risposta/commento)
  - **Logica trigger (accetta qualsiasi emoji)**:
    - Se è una **reaction** (`reaction.emoji` presente): trigger SEMPRE valido, indipendentemente da quale emoji. Instagram garantisce che il campo contenga un emoji unicode.
    - Se è un **messaggio/risposta testuale** (`message.text` presente):
      - Strip + uppercase del testo
      - Se contiene una parola di `INSTAGRAM_AUTO_DM_TEXT_TRIGGERS` → trigger valido
      - OPPURE se il testo, normalizzato (rimossi spazi/punteggiatura), è composto **solo da emoji** (usa `emoji.purely_emoji(text)` o controllo via libreria `emoji`) → trigger valido (l'utente ha risposto alla story con un'emoji singola/multipla)
      - Altrimenti ignora
  - **Niente blocklist**: l'utente ha esplicitamente richiesto di accettare qualunque emoji (anche 🤮, 💩, 😡). Non filtrare per "positività". Eventuale moderazione futura via campo `dry_run` su `InstagramAutoDMLog`.
- **Lookup articolo via media_id** (questo è il cuore):
  ```python
  log = SocialPublicationLog.objects.filter(
      instagram_media_id=media_id,
      platform__in=['instagram_story', 'instagram_reel'],
      success=True,
  ).order_by('-published_at').first()
  articolo = log.articolo if log else None
  ```
- Se articolo trovato:
  - Genera/recupera short link **per quell'articolo specifico** con UTM `medium=instagram_dm`
  - Chiama Graph API `POST https://graph.facebook.com/v24.0/me/messages?access_token=<page_token>` con body:
    ```json
    {
      "recipient": {"id": "<sender_id>"},
      "message": {"text": "Ciao! 👋 Ecco l'articolo che ti interessava:\n\n{titolo_articolo}\n{short_url}\n\nGrazie per seguirci su Ombra del Portico! 🙏\n\n(Per non ricevere più questi messaggi rispondi STOP)"}
    }
    ```
  - Salva `InstagramAutoDMLog` con `articolo` e `short_link` riferiti a quell'articolo specifico.
- Se articolo NON trovato (media_id non mappato): logga warning ma NON inviare DM generici. Rispondi 200 OK comunque.
- Rispondi sempre `200 OK` rapidamente (Meta richiede risposta <5s); usa Django Celery/async se disponibile, altrimenti thread con timeout. In assenza di Celery, processa sincronamente ma con max 3s di budget e logga il resto.

**Salvataggio media_id**
- In `social_sharing.py` quando pubblichi su IG Story/Reel, salva l'`id` del media restituito dalla Graph API nel nuovo campo `SocialPublicationLog.instagram_media_id` (migrazione).
- Senza questo campo l'auto-DM non sa quale articolo mappare.

**Gestione opt-out**
- Se il testo del messaggio == "STOP" (case-insensitive), salva `ig_user_id` in nuovo modello `InstagramOptOut` e NON inviare DM a quell'utente in futuro.

**Sicurezza**
- Usa `@csrf_exempt` sulla view
- Loop di sicurezza: max 1 DM ogni 60 secondi per `ig_user_id` (cache key `igdm:<sender_id>`)
- Logga tutto in `logs/instagram_webhook.log`

**Documentazione setup webhook**
- Aggiungi a `CLAUDE.md` sezione "Instagram Webhook Setup" con step:
  1. App già configurata su **flusso Instagram API + Facebook Login** (use case "Manage Pages" + Instagram Graph). Verificato che `instagram_manage_messages` e `pages_messaging` sono già "Ready for testing".
  2. In Meta Developer dashboard → app → **Webhooks → Instagram** → subscribe ai campi `messages`, `message_reactions`, `comments` (per Reel)
  3. Callback URL = `https://ombradelportico.it/webhooks/instagram/`
  4. Verify token = valore di `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` in `.env`
  5. Sottoscrivi anche la **Pagina Facebook** collegata all'account IG agli stessi campi (passaggio richiesto dal flusso legacy): `POST /{page-id}/subscribed_apps?subscribed_fields=messages,message_reactions,messaging_postbacks&access_token=<page_token>`
  6. Permission da richiedere in App Review (già presenti come "Ready for testing"):
     - `instagram_manage_messages` (invio DM)
     - `instagram_manage_comments` (lettura commenti Reel)
     - `pages_messaging` (necessaria perché l'IG account è dietro a una Pagina FB)
     - `pages_show_list`, `pages_read_engagement` (già attive)
  7. Durante sviluppo aggiungere utenti come **Tester / Instagram Tester** in App Roles per poter scatenare il webhook con account reali senza App Review approvata.
  8. Token usato per inviare DM: **Page Access Token** (NON User token) dell'IG Business Account → `INSTAGRAM_PAGE_ACCESS_TOKEN` in `.env`.

**Test**
- `tests/test_instagram_webhook.py`: GET challenge OK e KO, POST signature invalida → 403, POST valido con emoji trigger → DM inviato (mock requests), opt-out STOP, rate limit per utente.

### 9. Smart Link in Bio
Refattorizza `home.views.link_in_bio`:
- Mostra solo articoli con `SocialPublicationLog` su Instagram (post/story/reel) negli **ultimi 7 giorni**, ordinati per `data_pubblicazione` desc.
- Sezione "🔥 Appena pubblicato su Story" — articoli con SocialPublicationLog `instagram_story` nelle ultime 24h, evidenziati in cima.
- Ricerca: campo input + view AJAX `link_in_bio_search` che filtra per titolo/categoria.
- Ogni card linka allo short link, NON direttamente all'articolo, per il tracking.
- Aggiorna `link_in_bio.html` e `link_in_bio_cards.html` per la nuova UI (mobile-first, layout a card grandi, font system, no dipendenze extra).

### 10. Admin
- Registra `ShortLink` in `home/admin.py` con list_display (token, articolo, platform, clicks_count, created_at) e filtro per platform.
- Registra `InstagramAutoDMLog` con list_display (articolo, ig_user_id, trigger_type, trigger_value, dm_sent, created_at) e filtro per trigger_type/dm_sent.
- Registra `InstagramOptOut`.
- Aggiungi `shared_url`, `short_link`, `instagram_media_id` come readonly in `SocialPublicationLogAdmin`.

### 11. Management command
Crea `home/management/commands/generate_short_links.py` che genera retroattivamente uno `ShortLink` per ogni `SocialPublicationLog` esistente senza short_link associato.

### 12. Test
- `tests/test_share_links.py`: build_share_url, build_short_share_url, QR generation, redirect view (incremento contatore, UTM nell'URL finale).
- `tests/test_link_in_bio.py`: filtro 7 giorni, sezione story 24h, ricerca.
- `tests/test_instagram_webhook.py`: vedi sezione 8.

### 13. Documentazione
Aggiungi sezione "Social sharing & link tracking" a `CLAUDE.md` con:
- Schema dei nuovi modelli
- Endpoint `/s/<token>/`
- UTM convention
- Limiti Meta documentati (Link Sticker non disponibile via API)
- Variabili ambiente nuove (`SITE_URL` per costruire link assoluti)

## Vincoli operativi
- Python 3.12.3, virtualenv in `C:\news\venv`
- Non rompere migrazioni esistenti; partire dall'ultima presente in `home/migrations/`
- Non toccare `monitor_configs.py` e il sistema monitor
- Mantenere lingua italiana in template e log utente-facing
- Tutti i nuovi URL devono usare `reverse()` o `{% url %}` nei template
- Niente librerie pesanti: solo `qrcode[pil]` da aggiungere, oltre a quelle già in `requirements.txt`
- Tutti i nuovi import devono essere lazy dove rischiano import circolari (social_sharing.py importa molto)

## Output atteso
Diff completo, in commit logici separati:
1. `feat(share): aggiungi modello ShortLink, helper share_links e view redirect`
2. `feat(social): descrizione con link in FB Reel e caption ottimizzata IG Reel`
3. `feat(social): CTA "Link in bio o ❤️ per DM" stampata nei template IG/FB`
4. `feat(dm): webhook IG + auto-DM su reazione/parola chiave + opt-out`
5. `feat(bio): smart link in bio con filtro temporale e tracking click`
6. `feat(admin): admin ShortLink, InstagramAutoDMLog, campi tracking in SocialPublicationLog`
7. `chore: management command backfill short link + test + docs`

Esegui `python manage.py makemigrations` e `python manage.py test home` prima di chiudere e includi l'output nel report finale.
