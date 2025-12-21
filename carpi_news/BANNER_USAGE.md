# Sistema di Banner Pubblicitari

## Panoramica

Il sistema di banner pubblicitari permette agli utenti registrati di creare, gestire e pubblicare banner pubblicitari sul sito, scegliendo posizione, durata e completando il pagamento.

## Caratteristiche Principali

### Per gli Utenti

- ✅ **Registrazione e Login** - Sistema completo di autenticazione
- 📢 **Gestione Banner** - Crea, modifica ed elimina i tuoi banner
- 🎯 **Selezione Posizione** - 9 posizioni diverse disponibili
- ⏰ **Durata Personalizzata** - Da 1 a 365 giorni
- 💳 **Sistema di Pagamento** - Simulato (€5/giorno)
- 📊 **Statistiche** - Visualizzazioni, click e CTR in tempo reale

### Per gli Amministratori

- ✅ **Pannello Admin Django** - Gestione completa dei banner
- 🔍 **Filtri Avanzati** - Per stato, pagamento, posizione
- ⚡ **Azioni Batch** - Approva/Rifiuta/Attiva multipli banner
- 📈 **Analytics** - Statistiche dettagliate per ogni banner

## Come Usare il Sistema

### 1. Registrazione Utente

1. Vai su: `http://localhost:8000/panel/register/`
2. Compila il form con:
   - Username (obbligatorio)
   - Email (opzionale)
   - Nome e Cognome (opzionali)
   - Password (minimo 6 caratteri)
3. Registrati e verrai automaticamente loggato

### 2. Accesso alla Dashboard

1. Login: `http://localhost:8000/panel/login/`
2. Dashboard: `http://localhost:8000/panel/dashboard/`
3. Visualizza statistiche dei tuoi banner

### 3. Creare un Banner

1. Dalla dashboard, clicca su "I Miei Banner" o vai a `/panel/banners/`
2. Clicca "Crea Nuovo Banner"
3. Compila il form:
   - **Titolo**: Nome identificativo
   - **Immagine**: Upload del file (728x90 o 300x250px consigliati)
   - **URL Destinazione**: Dove reindirizzare i click
   - **Testo Alternativo**: Per accessibilità/SEO
   - **Posizione**: Scegli dove apparirà il banner
   - **Durata**: Numero di giorni (1-365)
   - **Priorità**: 1-10 (opzionale, default 1)
4. Clicca "Procedi al Pagamento"

### 4. Completare il Pagamento

1. Rivedi il riepilogo dell'ordine
2. Seleziona il metodo di pagamento:
   - Carta di Credito/Debito
   - PayPal
   - Bonifico Bancario
3. Clicca "Paga in Sicurezza"
4. Il banner viene attivato immediatamente (in demo)

### 5. Gestire i Banner

- **Visualizza**: Lista completa su `/panel/banners/`
- **Modifica**: Solo banner non ancora attivi/pagati
- **Elimina**: Qualsiasi banner
- **Statistiche**: Vedi impressioni e click in tempo reale

## Posizioni Disponibili

1. **Header** - Sopra il titolo della pagina
2. **Sidebar Alto** - Parte superiore della sidebar
3. **Sidebar Centro** - Centro della sidebar
4. **Sidebar Basso** - Parte inferiore della sidebar
5. **Tra gli Articoli** - Nella homepage tra gli articoli
6. **Inizio Articolo** - Prima del contenuto dell'articolo
7. **Centro Articolo** - Nel mezzo del contenuto
8. **Fine Articolo** - Dopo il contenuto
9. **Footer** - Nel footer del sito

## Visualizzare Banner nel Template

Per mostrare banner nelle tue pagine, usa il template tag:

```django
{% load banner_tags %}

<!-- Mostra banner header -->
{% show_banner 'header' %}

<!-- Mostra banner sidebar -->
{% show_banner 'sidebar_top' %}

<!-- Mostra banner fine articolo -->
{% show_banner 'article_bottom' %}
```

## Prezzi

- **Prezzo base**: €1.70/giorno
- **Moltiplicatore priorità**: La priorità (1-5) moltiplica il prezzo base
- **Calcolo automatico**: Giorni × Prezzo giornaliero (€1.70 × priorità)
- **Esempi con priorità 3** (€1.70 × 3 = €5.10/giorno):
  - 7 giorni = €35.70
  - 30 giorni = €153.00
  - 90 giorni = €459.00
- **Esempi con priorità 1** (€1.70 × 1 = €1.70/giorno):
  - 7 giorni = €11.90
  - 30 giorni = €51.00
  - 90 giorni = €153.00
- **Esempi con priorità 5** (€1.70 × 5 = €8.50/giorno):
  - 7 giorni = €59.50
  - 30 giorni = €255.00
  - 90 giorni = €765.00

## Stati del Banner

### Stati del Banner
- **draft** - Bozza (non visibile)
- **pending_payment** - In attesa di pagamento
- **active** - Attivo e visibile
- **paused** - In pausa
- **expired** - Scaduto
- **rejected** - Rifiutato dall'admin

### Stati del Pagamento
- **pending** - In attesa
- **completed** - Completato
- **failed** - Fallito
- **refunded** - Rimborsato

## Statistiche e Analytics

Per ogni banner puoi vedere:

- **Impressioni**: Quante volte è stato visualizzato
- **Click**: Quante volte è stato cliccato
- **CTR** (Click-Through Rate): Percentuale click/impressioni
- **Giorni Rimanenti**: Tempo prima della scadenza

## Amministrazione

Gli admin possono gestire tutti i banner da:

`http://localhost:8000/admin/admin_panel/banner/`

### Azioni Disponibili

1. **Approva Banner** - Attiva banner pagati
2. **Rifiuta Banner** - Rifiuta banner inappropriati
3. **Attiva Banner** - Attiva manualmente banner pagati

### Filtri

- Per stato (attivo, scaduto, ecc.)
- Per stato pagamento
- Per posizione
- Per data creazione

## Note di Sviluppo

### Sistema di Pagamento

Attualmente il pagamento è **simulato**. In produzione, integrare:

- **Stripe**: `pip install stripe`
- **PayPal**: `pip install paypalrestsdk`
- **Altri gateway**: Secondo necessità

### File Media

I banner vengono salvati in:
```
carpi_news/media/banners/
```

Assicurati che la directory sia scrivibile e configurata correttamente in `settings.py`:

```python
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
```

### Tracciamento Click

I click vengono tracciati tramite URL di redirect:
```
/panel/banner/<id>/click/
```

Questo permette di:
- Incrementare il contatore click
- Analizzare il traffico
- Prevenire frodi (future implementazioni)

## Sicurezza

- ✅ Login richiesto per gestione banner
- ✅ Gli utenti vedono solo i propri banner
- ✅ Validazione immagini (ImageField)
- ✅ CSRF protection su tutti i form
- ✅ Sanitizzazione URL
- ✅ Rate limiting (da implementare in produzione)

## Prossimi Sviluppi

- [ ] Integrazione gateway pagamento reale
- [ ] Sistema di moderazione automatica
- [ ] A/B testing per banner
- [ ] Report analytics avanzati
- [ ] API REST per gestione programmatica
- [ ] Sistema di crediti prepagati
- [ ] Notifiche email per scadenze
- [ ] Dashboard con grafici e statistiche
