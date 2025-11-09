# Admin Panel - Sistema di Gestione Banner

Sistema di gestione banner pubblicitari per Ombra del Portico.

## Caratteristiche Principali

### 🖼️ Ottimizzazione Automatica Immagini
- **Conversione WebP**: Tutte le immagini convertite automaticamente in WebP (risparmio ~60-70%)
- **Ridimensionamento**: Immagini adattate alle dimensioni consigliate per posizione
- **Validazione**: Controllo dimensioni con tolleranza ±10%
- **Alta qualità**: Qualità 85% per banner nitidi

### 📐 Dimensioni Standard IAB

| Posizione | Dimensioni | Tipo |
|-----------|-----------|------|
| Header, Footer, Leaderboard | 728×90px | Leaderboard |
| Sidebar, Article Middle | 300×250px | Medium Rectangle |

### 💰 Sistema di Pricing
- Prezzo base: €1/giorno
- Moltiplicatori priorità:
  - Priorità 1 (Massima): ×5
  - Priorità 2 (Alta): ×3
  - Priorità 3 (Media): ×2
  - Priorità 4 (Normale): ×1

### 💳 Integrazione PayPal
- Pagamenti sicuri tramite PayPal
- Supporto Sandbox per test
- Tracciamento transazioni

### 📊 Statistiche
- Impressions (visualizzazioni)
- Click tracking
- CTR (Click-Through Rate)

## Installazione e Setup

### 1. Esegui le migrazioni
```bash
python manage.py migrate admin_panel
```

### 2. Configura PayPal (.env)
```env
PAYPAL_CLIENT_ID=your_client_id
PAYPAL_CLIENT_SECRET=your_client_secret
PAYPAL_MODE=sandbox  # o 'live' per produzione
```

### 3. Crea utenti
Gli utenti possono registrarsi autonomamente via `/gestionale/register/`

## Utilizzo

### Per gli Utenti

1. **Registrazione**: `/gestionale/register/`
2. **Login**: `/gestionale/login/`
3. **Dashboard**: `/gestionale/`
4. **Crea Banner**: Seleziona posizione, carica immagine, configura date
5. **Acquisto**: PayPal checkout per attivare il banner
6. **Statistiche**: Monitora performance dei tuoi banner

### Per gli Admin

1. **Accesso**: `/admin/admin_panel/banner/`
2. **Approvazione**: Approva banner in attesa
3. **Gestione**: Modifica/elimina banner
4. **Note**: Aggiungi note amministrative

## Posizioni Banner

### Homepage
- **Header**: Sopra il titolo della pagina
- **Between Articles**: Tra gli articoli in griglia
- **Sidebar Top/Middle/Bottom**: Colonna laterale
- **Footer**: Fine pagina

### Pagina Articolo
- **Article Top**: Inizio articolo
- **Article Middle**: Centro articolo
- **Article Bottom**: Fine articolo

## File Principali

```
admin_panel/
├── models.py           # Modello Banner con dimensioni consigliate
├── views.py            # Viste per gestione banner
├── signals.py          # Ottimizzazione immagini automatica
├── admin.py            # Configurazione admin Django
├── urls.py             # URL routing
├── templates/
│   └── admin_panel/    # Template HTML
└── templatetags/
    └── banner_tags.py  # Template tag per visualizzazione banner
```

## Template Tag

### Visualizza Banner
```django
{% load banner_tags %}

<!-- Homepage -->
{% get_banner 'header' %}
{% get_banner 'between_articles' %}

<!-- Articolo -->
{% get_banner 'article_top' %}
{% get_banner 'article_middle' %}
```

## Workflow Banner

```
1. Utente crea banner → Status: 'pending_payment'
2. Utente acquista → Status: 'pending_approval', Payment: 'completed'
3. Admin approva → Status: 'active' (se acquistato)
4. Sistema mostra banner → Impression/Click tracking
5. Fine periodo → Status: 'expired'
```

**Note**:
- Il banner parte sempre da `pending_payment` (deve essere acquistato)
- Dopo l'acquisto passa automaticamente a `pending_approval`
- Solo dopo l'approvazione admin diventa `active` e visibile

## API e Endpoints

### Pubblici
- `/gestionale/login/` - Login utente
- `/gestionale/register/` - Registrazione
- `/gestionale/logout/` - Logout

### Autenticati
- `/gestionale/` - Lista banner dell'utente
- `/gestionale/banner/create/` - Crea nuovo banner
- `/gestionale/banner/<id>/edit/` - Modifica banner
- `/gestionale/banner/<id>/delete/` - Elimina banner
- `/gestionale/banner/<id>/payment/` - Pagina pagamento PayPal

### Callback PayPal
- `/gestionale/banner/<id>/payment/success/` - Pagamento riuscito
- `/gestionale/banner/<id>/payment/cancel/` - Pagamento annullato

### Tracking
- `/gestionale/banner/<id>/click/` - Redirect con tracking click

## Testing

### Test Ottimizzazione Immagini
```bash
python test_banner_conversion.py
```

### Test Completi
```bash
python manage.py test admin_panel
```

## Sicurezza

- ✅ Login richiesto per tutte le operazioni
- ✅ Utenti possono modificare solo i propri banner
- ✅ Validazione input lato server
- ✅ CSRF protection su tutti i form
- ✅ PayPal secure checkout
- ✅ Sanitizzazione immagini (conversione RGB)

## Performance

- ✅ Immagini WebP (~60-70% più leggere)
- ✅ Dimensioni ottimizzate per posizione
- ✅ Cache query banner attivi
- ✅ Lazy loading supportato

## Troubleshooting

### Banner non visibile
1. Verifica `status='active'`
2. Verifica `payment_status='completed'`
3. Verifica `approved=True`
4. Verifica date (start_date ≤ oggi ≤ end_date)

### Acquisto non funziona
1. Verifica credenziali PayPal in `.env`
2. Usa `PAYPAL_MODE=sandbox` per test
3. Controlla logs Django per errori

### Immagine non ottimizzata
1. Verifica formato supportato (PNG, JPG, JPEG)
2. Controlla logs: `logs/`
3. Verifica Pillow installato: `pip list | grep -i pillow`

## Logging

Tutti i processi sono loggati in `logs/`:

```python
import logging
logger = logging.getLogger('admin_panel')
```

Log disponibili:
- Conversione immagini
- Ridimensionamento
- Acquisti PayPal
- Errori e warning

## Documentazione Completa

Vedi [BANNER_IMAGE_OPTIMIZATION.md](../../BANNER_IMAGE_OPTIMIZATION.md) per dettagli tecnici sull'ottimizzazione immagini.

---

**Versione**: 1.0
**Ultima modifica**: 2025-11-09
