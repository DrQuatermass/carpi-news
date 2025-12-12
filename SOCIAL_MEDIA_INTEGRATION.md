# Integrazione Social Media - Ombra del Portico

## Panoramica

Sistema di condivisione automatica degli articoli su 4 piattaforme social quando vengono approvati.

**Piattaforme Attive:**
- ✅ **Telegram** - Bot API
- ✅ **Facebook** - Graph API v24.0 (link preview)
- ✅ **Instagram** - Instagram Graph API (foto + "Link in bio")
- ✅ **Twitter/X** - RSS feed (IFTTT)

---

## Configurazione

### 1. Telegram

```env
TELEGRAM_BOT_TOKEN=7880734938:AAFMf_n-4i_oN_kXH5M9b9eBP-pBjGHoMV4
TELEGRAM_CHAT_ID=-1002385644330
TELEGRAM_AUTO_SHARE=True
```

**Formato Post:**
```
📰 {titolo}

{sommario}

🔗 Leggi l'articolo completo: {url}

📷 [Immagine allegata se presente]
```

### 2. Facebook

```env
FACEBOOK_AUTO_SHARE=True
FACEBOOK_PAGE_ID=777837308746450
FACEBOOK_ACCESS_TOKEN=EAAhJGqidMfMBQI... (Long-Lived User Token)
FACEBOOK_APP_ID=25165056809781052
FACEBOOK_APP_SECRET=aee0b12dc6a6b0a47c9e5280177b6baf
```

**Formato Post:**
- Usa endpoint `/feed` per generare link preview automatico
- Facebook preleva l'immagine dall'articolo
- Cliccando immagine/card, utente va direttamente sul sito

**Token:** Long-Lived User Access Token (non scade mai, expires_at: 0)

### 3. Instagram

```env
INSTAGRAM_AUTO_SHARE=True
INSTAGRAM_ACCOUNT_ID=17841476799989726
# Usa stesso FACEBOOK_ACCESS_TOKEN
```

**Formato Post:**
```
{titolo}

{sommario[:450]}...

🔗 Link in bio per leggere l'articolo completo

#{hashtags_categoria}
```

**Caratteristiche:**
- Processo 2 fasi: Create Container → Publish (delay 5 secondi)
- Richiede sempre immagine (articoli senza foto vengono saltati)
- Link non cliccabili in caption (usa strategia "Link in bio")
- Hashtag automatici per categoria
- Limite: 25 post/24h

**Bio Instagram (configurazione manuale):**
```
📰 Notizie di Carpi
🔗 Leggi gli articoli completi:
https://ombradelportico.it
```

### 4. Twitter/X

Gestito tramite IFTTT:
- **RSS Feed**: https://ombradelportico.it/feed/
- **Applet IFTTT**: Monitora RSS e pubblica automaticamente

---

## Funzionamento

### Workflow Automatico

1. **Articolo creato** (dai monitor o manualmente)
   - Campo `approvato=False` → Non ancora pubblicato

2. **Admin approva articolo**
   - Vai su `/admin/home/articolo/`
   - Spunta checkbox "Approvato"
   - Salva

3. **Django Signal trigger**
   - `post_save` signal rileva cambio campo `approvato`
   - Chiama `social_manager.share_article(articolo)`

4. **Condivisione multi-piattaforma**
   - Telegram: Invia foto + caption con link
   - Facebook: Pubblica link (preview automatico)
   - Instagram: Create container → Publish (con delay)

5. **Logging**
   ```
   [INFO] Condivisione articolo "Titolo" su 3 piattaforme...
   [INFO] ✓ Telegram: condiviso con successo
   [INFO] ✓ Facebook: condiviso con successo
   [INFO] ✓ Instagram: condiviso con successo
   ```

---

## File del Sistema

```
carpi_news/
├── .env                          # Token e configurazione
├── carpi_news/settings.py        # Config Django social
├── home/
│   ├── social_sharing.py         # ⭐ CORE - Logica pubblicazione
│   ├── signals.py                # Auto-trigger su approvazione
│   └── models.py                 # Modello Articolo
└── get_facebook_token_oauth.py   # Script rigenera token (se necessario)
```

### SocialMediaManager

**File:** [home/social_sharing.py](carpi_news/home/social_sharing.py)

**Metodi principali:**
```python
class SocialMediaManager:
    def share_article(articolo)
        # Condivide su tutte le piattaforme abilitate

    def _share_to_telegram(articolo, article_url)
        # Pubblica su Telegram

    def _share_to_facebook(articolo, article_url)
        # Pubblica su Facebook (genera Page Token automaticamente)

    def _share_to_instagram(articolo, article_url)
        # Pubblica su Instagram (2 fasi con delay)

    def get_platform_status()
        # Ritorna stato configurazione piattaforme
```

---

## Rigenerazione Token Facebook

**Quando necessario:**
- Token diventa invalido (password cambiata, permessi revocati, ecc.)

**Procedura:**
```bash
cd carpi_news
python get_facebook_token_oauth.py
```

1. Script genera URL OAuth
2. Apri URL nel browser e autorizza app
3. Copia codice dall'URL di redirect
4. Incollalo nello script
5. Script mostra nuovo Long-Lived User Token
6. Copia token in `.env`:
   ```env
   FACEBOOK_ACCESS_TOKEN=nuovo_token_qui
   ```
7. Riavvia Django

**IMPORTANTE:** Usa il **Long-Lived USER Token** (non Page Token)

---

## Troubleshooting

### Facebook: Permission Error
**Causa:** Token tipo sbagliato

**Soluzione:** Il sistema genera automaticamente Page Token da User Token. Assicurati di usare Long-Lived User Token in `.env`

### Instagram: Post saltato
**Causa:** Articolo senza immagine

**Soluzione:** Instagram richiede sempre immagine. Aggiungi foto all'articolo.

### Instagram: "Media not ready"
**Causa:** Pubblicazione troppo veloce

**Soluzione:** Già implementato delay 5 secondi. Se persiste, aumenta delay in [social_sharing.py:359](carpi_news/home/social_sharing.py#L359)

---

## Testing

```bash
cd carpi_news
python manage.py shell
```

```python
from home.models import Articolo
from home.social_sharing import social_manager

# Test condivisione
articolo = Articolo.objects.filter(approvato=True).first()
results = social_manager.share_article(articolo)

# Verifica risultati
for platform, success in results.items():
    print(f"{platform}: {'✓' if success else '✗'}")

# Stato piattaforme
status = social_manager.get_platform_status()
for platform, info in status.items():
    print(f"{platform}: {info}")
```

---

## Limiti API

- **Facebook:** ~200 chiamate/ora, post illimitati
- **Instagram:** ~200 chiamate/ora, max 25 post/24h, solo foto (no solo testo)
- **Telegram:** 30 messaggi/sec, immagini max 10MB

---

**Ultimo aggiornamento:** 2025-12-12
**Status:** ✅ Sistema operativo su 4 piattaforme
**Token Facebook:** Never-expiring (expires_at: 0)
