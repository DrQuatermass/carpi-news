# Setup Sistema di Indicizzazione

Questo documento spiega come configurare il sistema ibrido di notifica ai motori di ricerca per favorire l'indicizzazione rapida degli articoli pubblicati.

## Panoramica

Il sistema utilizza **due tecnologie complementari**:

1. **IndexNow** - Notifica multi-motore (Google, Bing, Yandex)
   - ✅ Semplice da configurare
   - ✅ Nessun limite di richieste
   - ⚠️ Indicizzazione non garantita (dipende dai motori)

2. **Google Indexing API** - Notifica diretta a Google
   - ✅ Indicizzazione molto rapida (minuti)
   - ✅ Priorità alta nei crawler Google
   - ⚠️ Richiede configurazione Google Cloud (200 req/giorno gratis)

---

## 1. Setup IndexNow

### Step 1: Genera configurazione

```bash
cd carpi_news
python manage.py setup_indexing
```

Questo comando:
- Genera una chiave casuale univoca
- Crea il file di verifica `{key}.txt` in `/static/`
- Mostra le istruzioni da seguire

### Step 2: Aggiungi chiave al `.env`

Copia la chiave generata nel file `.env`:

```bash
INDEXNOW_KEY=abc123def456...
```

### Step 3: Verifica file pubblico

Il file `{key}.txt` deve essere accessibile pubblicamente:

```
https://www.ombradelportico.it/abc123def456....txt
```

Assicurati che Apache/Nginx serva correttamente i file statici.

### Step 4: Test

```bash
curl -X POST "https://api.indexnow.org/indexnow" \
  -H "Content-Type: application/json" \
  -d '{
    "host": "www.ombradelportico.it",
    "key": "abc123def456...",
    "keyLocation": "https://www.ombradelportico.it/abc123def456....txt",
    "urlList": ["https://www.ombradelportico.it/articolo/test/"]
  }'
```

Risposta attesa: `HTTP 200` o `HTTP 202`

---

## 2. Setup Google Indexing API

### Step 1: Crea progetto Google Cloud

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea nuovo progetto: "Ombra del Portico Indexing"

### Step 2: Abilita API

1. Vai su [API Library](https://console.cloud.google.com/apis/library)
2. Cerca "Indexing API"
3. Clicca "Abilita"

### Step 3: Crea Service Account

1. Vai su [IAM & Admin → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Clicca "Create Service Account"
3. Nome: `indexing-api-service`
4. Ruolo: **Owner** (o almeno Editor)
5. Clicca "Done"

### Step 4: Genera chiave JSON

1. Clicca sul Service Account appena creato
2. Tab "Keys" → "Add Key" → "Create new key"
3. Tipo: **JSON**
4. Clicca "Create"
5. Salva il file JSON scaricato (es. `indexing-service-account.json`)

### Step 5: Aggiungi Service Account a Search Console

⚠️ **Passaggio critico!**

1. Vai su [Google Search Console](https://search.google.com/search-console)
2. Seleziona la proprietà `www.ombradelportico.it`
3. Vai su **Impostazioni** → **Utenti e autorizzazioni**
4. Clicca "Aggiungi utente"
5. Inserisci l'email del Service Account (formato: `indexing-api-service@project-id.iam.gserviceaccount.com`)
6. Permesso: **Proprietario**
7. Clicca "Aggiungi"

**Senza questo passaggio l'API non funzionerà!**

### Step 6: Carica credenziali sul server

```bash
# Copia file JSON sul server
scp indexing-service-account.json user@server:/var/www/carpi-news/

# Imposta permessi sicuri
chmod 600 /var/www/carpi-news/indexing-service-account.json
```

### Step 7: Configura Django

Aggiungi al file `.env`:

```bash
GOOGLE_INDEXING_CREDENTIALS=/var/www/carpi-news/indexing-service-account.json
```

### Step 8: Installa dipendenza Google

```bash
pip install google-auth google-auth-httplib2
```

Aggiungi anche a `requirements.txt`:
```
google-auth>=2.23.0
google-auth-httplib2>=0.1.1
```

### Step 9: Test

```python
from home.indexing_notifier import notifier

result = notifier._notify_google_indexing_api(
    'https://www.ombradelportico.it/articolo/test-articolo/'
)

print(result)
# Expected: {'success': True, 'message': 'Notificato a Google Indexing API'}
```

---

## 3. Funzionamento Automatico

Una volta configurato, il sistema funziona **automaticamente**:

1. **Articolo approvato** → Signal `post_save` in `signals.py`
2. **Notifica IndexNow** → Google, Bing, Yandex (multi-motore)
3. **Notifica Google API** → Indicizzazione rapida su Google

Tutto viene eseguito in **background thread** per non bloccare la richiesta HTTP.

### Log

Controlla i log per verificare il funzionamento:

```bash
tail -f logs/django.log | grep -i "index"
```

Log di successo:
```
✓ IndexNow notificato per: Titolo Articolo
✓ Google Indexing API notificato per: Titolo Articolo
```

Log di errore:
```
✗ IndexNow fallito per Titolo: HTTP 400: Invalid key
✗ Google Indexing API fallito: HTTP 403: Permission denied
```

---

## 4. Verifica Indicizzazione

### IndexNow

Non c'è modo diretto di verificare, ma puoi monitorare:

```bash
# Bing Webmaster Tools
https://www.bing.com/webmasters

# Yandex Webmaster
https://webmaster.yandex.com/
```

### Google Indexing API

Controlla lo stato delle richieste:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://indexing.googleapis.com/v3/urlNotifications/metadata?url=https://www.ombradelportico.it/articolo/test/"
```

O usa Google Search Console:
1. Vai su **Controllo URL**
2. Inserisci URL articolo
3. Verifica data ultima scansione

---

## 5. Quote e Limiti

| Servizio | Quota | Costo |
|----------|-------|-------|
| **IndexNow** | Illimitato | Gratuito |
| **Google Indexing API** | 200/giorno | Gratuito |

Per aumentare quota Google:
1. Vai su [Google Cloud Console](https://console.cloud.google.com/apis/api/indexing.googleapis.com/quotas)
2. Richiedi aumento quota (solitamente approvato automaticamente)

---

## 6. Troubleshooting

### IndexNow errore 400

```
✗ IndexNow fallito: HTTP 400: Invalid key
```

**Soluzione:**
- Verifica che il file `{key}.txt` sia pubblicamente accessibile
- Controlla che la chiave in `.env` corrisponda al nome del file
- Verifica che `SITE_URL` sia corretto in `.env`

### Google API errore 403

```
✗ Google Indexing API fallito: HTTP 403: Permission denied
```

**Soluzione:**
- Verifica che il Service Account sia stato aggiunto a Search Console come **Proprietario**
- Controlla che l'email del Service Account sia corretta
- Attendi 5-10 minuti dopo aver aggiunto l'utente in Search Console

### Google API errore 401

```
✗ Google Indexing API fallito: HTTP 401: Unauthorized
```

**Soluzione:**
- Verifica che il path in `GOOGLE_INDEXING_CREDENTIALS` sia corretto
- Controlla permessi file JSON: `chmod 600 file.json`
- Verifica che l'API Indexing sia abilitata nel progetto Google Cloud

---

## 7. Documentazione Ufficiale

- **IndexNow**: https://www.indexnow.org/documentation
- **Google Indexing API**: https://developers.google.com/search/apis/indexing-api/v3/quickstart
- **Google Service Accounts**: https://cloud.google.com/iam/docs/service-accounts

---

## 8. Note di Sicurezza

⚠️ **File JSON contiene credenziali sensibili!**

```bash
# Permessi sicuri
chmod 600 /path/to/service-account.json

# NON committare in git
echo "*.json" >> .gitignore
echo "indexing-service-account.json" >> .gitignore
```

✅ Le credenziali sono utilizzate solo server-side, mai esposte al client.
