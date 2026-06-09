# Codex prompt — Fix pipeline Instagram Auto-DM

## Contesto

Progetto Django 5.2.5 `carpi_news` (ombradelportico.it). Esiste già una pipeline che invia automaticamente un DM Instagram con il link all'articolo quando un follower reagisce / risponde a una Story o commenta un Reel pubblicato dalla pagina. Il problema è che **il DM non parte sempre**: a volte arriva, a volte no, in modo apparentemente non deterministico. Bisogna individuare le cause e renderlo affidabile.

NON cambiare comportamenti diversi da quello descritto (publishing FB/IG, generazione reel/story, link tracking sono già in produzione: vanno preservati).

## File coinvolti nella pipeline

1. `home/views_webhooks.py` — endpoint `/webhooks/instagram/` (GET verify + POST eventi), estrazione eventi, matching media→articolo, invio DM via Graph API, logging.
2. `home/webhook_urls.py` — routing webhook.
3. `home/social_sharing.py` — pubblicazione Story/Reel IG, scrittura `SocialPublicationLog.instagram_media_id` tramite `_finalize_publication` (usa `update_or_create((articolo, platform))`).
4. `home/instagram_story.py` — publisher Graph API che restituisce `media_id` su successo.
5. `home/models.py` — `SocialPublicationLog`, `InstagramAutoDMLog`, `InstagramOptOut`, `ShortLink`.
6. `home/management/commands/test_instagram_dm.py` — comando di test (utilizzalo / estendilo per riprodurre).
7. `carpi_news/settings.py` — flag e secrets (`FACEBOOK_APP_SECRET`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_WEBHOOK_VERIFY_TOKEN`, `INSTAGRAM_PAGE_ACCESS_TOKEN`, `INSTAGRAM_ACCOUNT_ID`, `FACEBOOK_PAGE_ID`, `INSTAGRAM_AUTO_DM_*`).
8. `logs/instagram_webhook.log` — log dedicato del webhook (channel `home.instagram_webhook`).

## Obiettivo

Rendere l'invio del DM **idempotente, osservabile e ad alta probabilità di successo** per gli eventi che Meta invia realmente, mantenendo il rispetto della policy di messaging IG (finestra 24h, opt-out STOP, rate limit per utente).

## Cosa controllare in modo sistematico

Per ogni voce sotto, **misura prima sui log** (`logs/instagram_webhook.log` + `logs/social_sharing.log` se esistono) quanti casi cadono in ciascun ramo, poi correggi.

### 1. Verifica firma webhook (`_valid_signature`)
- Oggi accetta solo se la firma combacia con uno tra `FACEBOOK_APP_SECRET` o `INSTAGRAM_APP_SECRET`. Se entrambi sono vuoti, scarta tutto.
- Verifica nei log quanti eventi POST sono stati respinti con "signature non valida" o "nessun app secret configurato".
- Confermare che in `.env` il secret usato corrisponda all'app effettivamente collegata all'utente Instagram Business + Pagina Facebook (è quasi sempre il **Facebook App Secret**, non un secret separato IG).
- Aggiungere un log esplicito su `INSTAGRAM_APP_SECRET`/`FACEBOOK_APP_SECRET` "presenti/assenti" all'avvio.

### 2. Estrazione `media_id` (`_extract_events`)
È il punto più fragile. Le payload reali Meta che dobbiamo gestire sono:

a) **Reaction su Story** (`entry.messaging[].reaction`) — molto spesso **non contiene** `media_id` esplicito; arriva nei rami `message.reply_to.story.id` solo se è una reply, non una reaction pura. Verificare con payload reale catturato dai log e gestire i fallback (vedi punto 4).

b) **Reply testuale su Story** (`entry.messaging[].message` con `reply_to.story.id`) — di solito `media_id` è qui.

c) **Commento su Reel** (`entry.changes[]` con `field=comments`) — `value.media.id` di solito è presente. L'attuale fallback `value.message.attachments[0].payload.url` è un URL stringa, non un id: rimuoverlo o trasformarlo in lookup separato.

d) **DM diretto** (`messages` su `entry.messaging`) — può non avere alcun media. Decidere se trattarlo come trigger valido (oggi sì, se contiene trigger testuale/emoji).

Compiti:
- Loggare l'intero JSON del primo evento di ogni tipo a livello INFO una volta (campione), poi DEBUG.
- Coprire chiavi alternative documentate da Meta (es. `entry.messaging[].postback`, `value.from.id` vs `value.sender.id`, `entry.changes[].value.parent_id`).
- Quando `media_id` non si estrae, segnare l'evento come "no_media" nel log con motivazione chiara.

### 3. Mappatura media→articolo (`_find_publication_log`)
- Tabella `SocialPublicationLog` ha `unique` implicito di fatto perché `_finalize_publication` usa `update_or_create(articolo, platform)`. Conseguenza: **un solo record per (articolo, platform)**.
- `published_at` ha `auto_now_add=True`: **NON si aggiorna** quando `update_or_create` modifica un record esistente. Quindi il fallback `published_at__gte=since` può **non trovare** una Story appena ripubblicata se il record era stato creato giorni prima (es. articolo riproposto, retry social, In progress→success).
- Inoltre, ogni nuova pubblicazione **sovrascrive** `instagram_media_id` del record precedente: gli `media_id` storici vengono persi, e se un follower reagisce a una vecchia story il match non funziona.

Soluzione (decidere quale, motivare nel commit):

**Opzione A (consigliata)**: cambiare il modello in modo che ogni pubblicazione crei una nuova riga. Aggiungere un campo `attempt_id` o togliere l'uso di `update_or_create` su `(articolo, platform)` per Story/Reel IG e usare `create` puro, con `success=True` come marker definitivo e righe `In progress` separate. Aggiornare `_prepare_publication_slot` di conseguenza per non rompere la deduplica (deve guardare l'ultima riga successo, non l'unica).

**Opzione B (minimale)**: aggiungere `published_at_refresh = models.DateTimeField(auto_now=True)` e usarlo per i fallback temporali; mantenere `update_or_create` ma assicurarsi di non perdere `instagram_media_id` precedenti (es. campo `instagram_media_ids = JSONField(default=list)` accumulato).

In entrambi i casi, `_find_publication_log` deve essere riscritto per cercare il media_id **direttamente** e, in fallback, l'ultima pubblicazione `instagram_story` o `instagram_reel` di una qualsiasi (articolo, platform) entro una finestra ragionevole.

Inoltre: alzare i default `INSTAGRAM_AUTO_DM_STORY_FALLBACK_MINUTES` a `1440` (24h, durata reale di una Story) e `INSTAGRAM_AUTO_DM_REEL_FALLBACK_MINUTES` a `4320` (72h), entrambi configurabili da `.env`.

### 4. Reaction senza media_id
Reaction pure a Story non portano media. Implementare un fallback dedicato:
- se `trigger_type == "story_reaction"` e `media_id` è vuoto, cercare l'ultima `instagram_story` con `success=True` pubblicata negli ultimi N minuti (`INSTAGRAM_AUTO_DM_STORY_FALLBACK_MINUTES`), come già fa il ramo reel_comment.
- loggare WARNING quando si usa il fallback con quale articolo è stato associato, così è verificabile a posteriori.

### 5. Trigger testuali e emoji (`_text_trigger`, `_emoji_only`, `_contains_emoji`)
- Verificare che `INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True` sia il default attivo in produzione.
- `_configured_text_triggers` fa upper+strip ma `_text_trigger` controlla `trigger in upper`: significa che "LINKEDIN" matcha "LINK". Usare word-boundary o split su whitespace per evitare falsi positivi e falsi negativi simmetrici.
- Aggiungere log dell'esito (`is_trigger`, valore, regola che ha matchato) per ogni evento testuale.

### 6. Anti-loop e opt-out
- `own_ids` esclude eventi generati dalla pagina stessa: ok.
- `cache.add(f"igdm:{sender_id}", True, 60)` ratelimit 60s: ok ma se il DM **fallisce** la cache resta valorizzata e blocca i retry per 60s. Spostare il `cache.add` **dopo** un esito definitivo, oppure rilasciare la chiave su fallimento.
- `InstagramOptOut`: ok.

### 7. Chiamata Graph `/me/messages` (`_send_dm`)
- Endpoint v24.0 ok per IG Messaging via Page Access Token collegato all'IG Business Account.
- Aggiungere `messaging_type=RESPONSE` (richiesto Meta nel webhook flow per la finestra 24h post-interazione, evita errori 10/200).
- Loggare il `messaging_product=instagram` se necessario (Meta lo richiede in alcuni casi recenti per IG Direct).
- Sul fallimento, **loggare codice HTTP, `error.code`, `error.subcode`, `error.fbtrace_id`** dal JSON di risposta (oggi è troncato a 500 char ma non parsato). Questi codici dicono se è token, finestra 24h, utente non raggiungibile, etc.
- Aggiungere retry singolo con backoff su 5xx e su `error.code in (1, 2, 4, 17, 32, 613)` (rate / temporanei).

### 8. Token (`INSTAGRAM_PAGE_ACCESS_TOKEN` vs `FACEBOOK_ACCESS_TOKEN`)
- Oggi `INSTAGRAM_PAGE_ACCESS_TOKEN` ricade su `FACEBOOK_ACCESS_TOKEN` se non impostato. Verificare in produzione quale dei due ha realmente i permessi `instagram_manage_messages`, `pages_messaging`. Aggiungere un endpoint/management command `check_ig_dm_token` che fa una chiamata di debug a `GET /debug_token` e logga scadenza + scope.
- Se il token è user-token (non Page) le DM IG **non partono mai**: deve essere Page Access Token derivato (long-lived) della pagina FB collegata all'IG Business.

### 9. Sottoscrizioni webhook
- Confermare che la Pagina FB sia subscribed ai field `messages, message_reactions, messaging_postbacks, feed` con `POST /{page-id}/subscribed_apps` e che l'app sia in modalità Live (o l'utente che reagisce sia un Tester).
- Aggiungere un management command `check_ig_subscriptions` che chiama `GET /{page-id}/subscribed_apps` e stampa lo stato.

### 9-bis. App Review e accesso avanzato (CAUSA PROBABILE PRINCIPALE)
Dal Meta Developer dashboard dell'utente risulta che lo step **"5. Complete app review"** non è completato. Senza app review approvata:
- I permessi `instagram_manage_messages`, `instagram_manage_comments`, `pages_messaging` sono in **standard access** → l'app può inviare DM **solo agli utenti aggiunti come Tester/Instagram Tester nel ruolo dell'app** e ai ruoli admin/developer.
- Per **qualunque altro follower**, la chiamata `/me/messages` risponde 200 OPPURE fallisce con errori come `(#10) Application does not have permission for this action` / `(#200) requires extended permission` / `(#100) No matching user found`. In alcuni casi Meta restituisce 200 ma il messaggio non viene mai recapitato.
- Questo spiega perfettamente l'osservazione "il DM non parte sempre": parte per gli account in whitelist, fallisce silenziosamente per tutti gli altri.

Inoltre lo step **"4. Set up Instagram business login"** non è completato: verificare se la pipeline attuale sta usando il flusso "Instagram Business Login" o il legacy "Facebook Login + Pagina collegata". Le DM tramite `/me/messages` con Page Access Token richiedono il flusso legacy (Pagina FB collegata a IG Business). Se l'utente sta cercando di migrare al nuovo flusso, il token va riemesso.

Compiti per Codex su questo punto:
1. **Documenta** in `CLAUDE.md` (sezione "Instagram Webhook Setup") che senza app review approvata l'invio DM è limitato ai tester, con i passi per:
   - aggiungere utenti come Instagram Tester (Meta for Developers → App Roles → Roles → Instagram Testers → invita → l'utente accetta da `instagram.com/accounts/manage_access/`),
   - oppure sottomettere App Review per `instagram_manage_messages`, `instagram_manage_comments`, `pages_messaging`, `human_agent` (richiesto fuori dalla finestra 24h).
2. **Aggiungi un management command** `check_ig_app_status` che chiama `GET /{app-id}?fields=id,name,review_status,roles{role,user}` e `GET /me/permissions` con il token in uso, e stampa:
   - stato dell'app (live / development),
   - lista dei Tester,
   - permessi effettivamente concessi al token (con marcatura "standard" vs "advanced" se rilevabile).
3. **Migliora il logging** di `_send_dm`: quando Meta risponde con `error.code` 10, 200, 230, 551, logga esplicitamente `"DM non recapitato: probabile app non approvata o utente non Tester (sender=%s, code=%s)"` così l'utente vede subito la differenza tra "DM fallito per token" e "DM fallito per app review".
4. **Frontend admin**: nella vista admin di `InstagramAutoDMLog` aggiungi un filtro su `dm_sent=False` e una colonna che mostra l'error code parsato, così l'utente può monitorare quanti DM falliscono per app review vs altri motivi.

### 10. Idempotenza / dedup eventi
- Meta consegna lo stesso evento più volte se il webhook risponde lentamente o con 5xx. Aggiungere chiave di dedup basata su `(sender_id, media_id, trigger_type, trigger_value, minuto)` in cache 24h: se già visto, log INFO e skip.
- Garantire che il webhook risponda **200 in < 1 secondo**: spostare `_handle_event` in un thread/queue (django-q, celery se già presente, oppure `threading.Thread` con context-safe DB conn) e rispondere subito 200. Oggi tutto il flusso è sincrono nella richiesta HTTP: invio DM + retry può sfondare i timeout di Meta e generare retry → duplicati e/o blocco temporaneo della sottoscrizione.

## Output atteso

1. **Patch** ai file sopra che risolva, in ordine di impatto previsto:
   - risposta webhook < 1s (handling asincrono),
   - mappatura media→articolo robusta (no perdita di media_id storici, fallback Story 24h),
   - parsing eventi completo (no falsi negativi),
   - rate-limit cache rilasciata su fallimento,
   - logging strutturato di error.code Meta in `_send_dm`,
   - aggiunta `messaging_type=RESPONSE` (+ `messaging_product=instagram` se richiesto).

2. **Migrazioni** se cambia `SocialPublicationLog` o aggiungi modelli/campi.

3. **Test**:
   - aggiornare/estendere `home/management/commands/test_instagram_dm.py` per simulare i 4 tipi di evento (reaction story, reply story, comment reel, dm diretto) chiamando `_extract_events` + `_handle_event` su payload fixture salvati in `home/tests/fixtures/ig_webhook/`,
   - aggiungere unit test in `home/tests.py` (o `home/tests_webhooks.py`) che coprano: signature ok/ko, dedup, fallback story 24h, opt-out STOP, rate-limit liberato su fallimento, trigger LINK case-insensitive senza falso positivo "LINKEDIN".
   - test deve girare con `python manage.py test home.tests_webhooks` senza chiamate di rete reali (mocka `requests.post`).

4. **Documentazione**: aggiornare la sezione "Social sharing & link tracking" in `CLAUDE.md` con le nuove variabili `.env` introdotte e i nuovi default dei fallback temporali, e aggiungere una sezione "Diagnostica DM IG" con i management command introdotti.

## Vincoli

- Mantenere compatibilità con dati esistenti: non droppare `SocialPublicationLog` (contiene storico). Le migrazioni devono essere additive o `RunPython` con backfill.
- Non rompere la pubblicazione Story/Reel/Facebook esistente: il successo di `_share_to_instagram_*` deve continuare a popolare `instagram_media_id` come oggi (o nel nuovo campo, ma con compatibilità).
- Tutti i log in italiano (consistenti col resto del progetto).
- Nessuna dipendenza nuova oltre a quelle già in `requirements.txt`, salvo motivazione esplicita.

## Come iniziare

1. Leggi i file elencati sopra in ordine.
2. Cattura nei log un paio di payload reali di ciascun tipo di evento (chiedi all'utente di reagire / commentare). Salvali come fixture.
3. Fai una proposta breve di design per il punto 3 (Opzione A vs B) **prima** di scrivere migrazioni: l'utente conferma quale strada prendere.
4. Implementa nell'ordine indicato nell'Output atteso.
5. Esegui `python manage.py test` e mostra l'output.
