# Codex prompt CLEANUP P1 — Deduplicare la logica pagamenti PayPal

## Contesto

Progetto Django 5.2.5 in `carpi_news/`. `admin_panel/views.py` (~1544 righe) gestisce
due flussi di pagamento PayPal quasi identici: banner pubblicitari e pubbliredazionali.

**Duplicazione verificata:**
- L'autenticazione PayPal (`base64.b64encode(f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}")`
  + richiesta token) è copiata **4 volte**: ~righe 486, 601, 1270, 1365.
- `banner_payment` (~336-601) e `pubbliredazionale_payment` (~1100-1370): creazione
  ordine PayPal quasi identica.
- `banner_payment_success` (~583-700) e `pubbliredazionale_payment_success` (~1341-1434):
  capture dell'ordine quasi identico.
- La logica dei codici promozionali (~40 righe) è duplicata nei due flussi.

`admin_panel/tests.py` è vuoto (3 righe): il refactor va accompagnato da test minimi.

## Obiettivo

Refactor **puro**, zero cambi di comportamento: stessi endpoint, stessi redirect,
stessi messaggi di errore, stessi log. Solo estrazione del codice comune.

## Azioni

### 1. Nuovo modulo `admin_panel/payments.py`

Estrarre dalle 4 copie esistenti (usa la versione più completa come riferimento e
segnala nel riepilogo eventuali differenze trovate tra le copie — potrebbero essere
bug latenti):

```python
def get_paypal_access_token() -> str:
    """Auth client-credentials verso PayPal. Solleva PayPalError su fallimento."""

def create_paypal_order(*, amount, currency, description, return_url, cancel_url) -> dict:
    """Crea l'ordine e restituisce il JSON PayPal (id + approval link)."""

def capture_paypal_order(order_id: str) -> dict:
    """Cattura l'ordine approvato e restituisce il JSON PayPal."""

def validate_promo_code(code: str, *, context: str) -> dict | None:
    """Valida un codice promo e restituisce sconto/metadati, None se invalido.
    context distingue banner vs pubbliredazionale se le regole differiscono."""
```

- Base URL PayPal (sandbox vs live) letta da settings in un punto solo.
- Un'eccezione dedicata `PayPalError` con messaggio loggabile; le view la catturano e
  riproducono **esattamente** i messaggi utente attuali.

### 2. Sostituire le copie nelle view

In `admin_panel/views.py`: le 4 occorrenze dell'auth, le due creazioni ordine, le due
capture e le due validazioni promo chiamano le nuove funzioni. Le view mantengono solo:
parsing della request, calcolo importi specifici del prodotto, aggiornamento dei
modelli (`Banner` / `Articolo` pubbliredazionale), redirect e messaggi.

### 3. Test in `admin_panel/tests.py`

Con `unittest.mock.patch('admin_panel.payments.requests.post')` (o equivalente):
- `get_paypal_access_token`: successo, errore HTTP, risposta senza token
- `create_paypal_order` / `capture_paypal_order`: payload corretto, gestione errore
- `validate_promo_code`: codice valido, scaduto, inesistente, context sbagliato
- Smoke test sulle view: il flusso banner e quello pubbliredazionale arrivano a
  chiamare le funzioni estratte con gli argomenti giusti (mock) e fanno il redirect
  atteso

## Vincoli

- Nessun cambiamento a URL, template, parametri delle richieste PayPal, importi,
  valuta, messaggi all'utente.
- Non toccare la configurazione PayPal in settings (solo leggerla dal nuovo modulo).
- Se durante l'estrazione trovi differenze reali tra le copie (es. una gestisce un
  errore che l'altra ignora), NON uniformare silenziosamente: mantieni il comportamento
  per-flusso con un parametro e segnala la differenza nel riepilogo finale.

## Verifica

1. `python manage.py test admin_panel` — i nuovi test passano.
2. `python manage.py test` — l'intera suite resta verde.
3. Diff review: in `admin_panel/views.py` non deve restare nessuna occorrenza di
   `b64encode` né di URL PayPal hardcoded (`grep -n "b64encode\|paypal.com" admin_panel/views.py`
   → zero risultati; tutto vive in `payments.py`).
4. Test manuale in sandbox PayPal (se configurata): un pagamento banner e uno
   pubbliredazionale end-to-end.
