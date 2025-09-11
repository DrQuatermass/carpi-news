# Guida Integrazione IFTTT per Social Sharing

## Overview

Questa guida spiega come configurare IFTTT (If This Then That) per automatizzare la condivisione degli articoli di Ombra del Portico sui social media utilizzando i feed RSS.

## Feed RSS Disponibili

Il sito offre tre feed RSS ottimizzati per diversi utilizzi:

### 1. Feed Principale
- **URL**: `https://ombradelportico.it/feed/rss/`
- **Contenuto**: Ultimi 10 articoli approvati
- **Aggiornamento**: Ogni 60 minuti
- **Utilizzo**: Condivisione generale di tutti gli articoli

### 2. Feed Recenti (Consigliato per IFTTT)
- **URL**: `https://ombradelportico.it/feed/recenti/`
- **Contenuto**: Articoli delle ultime 24 ore
- **Caratteristiche**: 
  - Emoji automatiche per categoria (📰 Generale, ⚽ Sport, 🎭 Cultura, etc.)
  - Hashtag ottimizzati per social (#CarpiNews #OmbraDelPortico)
  - Descrizioni ottimizzate (250 caratteri + hashtag)
- **Utilizzo**: Condivisione immediata su social media

### 3. Feed Atom
- **URL**: `https://ombradelportico.it/feed/atom/`
- **Contenuto**: Ultimi 10 articoli in formato Atom
- **Utilizzo**: Alternative per servizi che preferiscono Atom a RSS

## Configurazione IFTTT

### Prerequisiti
1. Account IFTTT (gratuito o Pro)
2. Account sui social media target (Facebook, Twitter, Instagram, etc.)

### Passo 1: Creare un Applet IFTTT

#### Per Facebook:
1. Vai su [IFTTT](https://ifttt.com) e accedi
2. Clicca "Create" per creare un nuovo Applet
3. **IF (Trigger)**:
   - Cerca e seleziona "RSS Feed"
   - Scegli "New feed item"
   - Inserisci URL: `https://ombradelportico.it/feed/recenti/`
4. **THEN (Action)**:
   - Cerca e seleziona "Facebook Pages"
   - Scegli "Create a link post"
   - Configura il messaggio:
     ```
     {{EntryTitle}}
     
     {{EntryContent}}
     
     Leggi tutto: {{EntryUrl}}
     ```

#### Per Twitter/X:
1. **IF**: RSS Feed → `https://ombradelportico.it/feed/recenti/`
2. **THEN**: Twitter → "Post a tweet"
   - Tweet text (max 280 caratteri):
     ```
     {{EntryTitle}}
     
     {{EntryUrl}}
     
     {{EntryContent}}
     ```

#### Per Telegram:
1. **IF**: RSS Feed → `https://ombradelportico.it/feed/recenti/`
2. **THEN**: Telegram → "Send message"
   - Configura il canale/chat
   - Messaggio:
     ```
     {{EntryTitle}}
     
     {{EntryContent}}
     
     🔗 {{EntryUrl}}
     ```

#### Per LinkedIn:
1. **IF**: RSS Feed → `https://ombradelportico.it/feed/recenti/`
2. **THEN**: LinkedIn → "Share an update"
   - Content:
     ```
     {{EntryTitle}}
     
     {{EntryContent}}
     
     #CarpiNews #OmbraDelPortico
     
     {{EntryUrl}}
     ```

### Passo 2: Configurazione Avanzata

#### Filtri (IFTTT Pro)
- **Per categoria**: Filtra per parole chiave nel titolo o contenuto
- **Per orario**: Limita le pubblicazioni a orari specifici
- **Per frequenza**: Evita spam limitando le pubblicazioni

#### Esempi di filtri:
```
Trigger: RSS Feed → New feed item matches "⚽"
Action: Twitter → Post tweet con emoji sport
```

```
Trigger: RSS Feed → New feed item matches "📰"
Action: Facebook → Post generale
```

### Passo 3: Test e Monitoraggio

1. **Test manuale**: Crea un articolo di test e verifica che IFTTT lo rilevi
2. **Monitoraggio**: Controlla l'activity log di IFTTT per errori
3. **Debug**: Usa `https://ombradelportico.it/feed/recenti/` in un lettore RSS per verificare il contenuto

## Vantaggi del Sistema RSS + IFTTT

### ✅ Vantaggi
- **Nessuna API complessa**: Non serve gestire API key di Facebook/Twitter
- **Affidabilità**: IFTTT gestisce retry e errori
- **Flessibilità**: Facile aggiungere nuove piattaforme
- **Controllo**: Filtri e personalizzazione avanzata
- **Gratuito**: Funziona con account IFTTT gratuiti

### ⚠️ Limitazioni
- **Ritardo**: IFTTT controlla i feed ogni 15-60 minuti
- **Personalizzazione**: Meno controllo sul formato rispetto alle API dirette
- **Dipendenza**: Dipende dal servizio IFTTT

## Risoluzione Problemi

### Feed Non Aggiornato
- Controlla che gli articoli siano approvati (`approvato=True`)
- Verifica che `data_pubblicazione` sia corretta
- Il feed "recenti" mostra solo articoli delle ultime 24 ore

### IFTTT Non Rileva Nuovi Articoli
- Verifica l'URL del feed: `https://ombradelportico.it/feed/recenti/`
- Controlla il formato XML del feed in un browser
- IFTTT può impiegare fino a 60 minuti per rilevare nuovi elementi

### Immagini Non Visualizzate
- Le immagini sono incluse come `<enclosure>` nel feed
- Facebook e alcuni social le rilevano automaticamente
- Per immagini locali, vengono convertite in URL assoluti

### Formattazione Social
Il feed "recenti" include:
- Emoji automatiche per categoria
- Hashtag ottimizzati
- Descrizioni di lunghezza appropriata per ogni social

## Monitoraggio e Analytics

### Log del Sistema
I feed RSS sono registrati nei log Django:
```bash
tail -f logs/carpi_news.log | grep -i "feed\|rss"
```

### Statistiche IFTTT
- Accedi al dashboard IFTTT
- Controlla "Activity" per vedere le esecuzioni
- Monitora errori e retry

### Test Feed
```bash
# Test locale del feed
curl "https://ombradelportico.it/feed/recenti/" | head -20

# Verifica articoli recenti
curl -s "https://ombradelportico.it/feed/recenti/" | grep -o '<title>[^<]*' | head -5
```

## Esempi di Applet IFTTT Pronti

### 1. Condivisione Completa
```
IF: RSS Feed (https://ombradelportico.it/feed/recenti/)
THEN: Multiple actions (Facebook + Twitter + Telegram)
```

### 2. Solo Sport
```
IF: RSS Feed contains "⚽" OR "Sport"  
THEN: Twitter with sports-specific hashtags
```

### 3. Solo Breaking News
```
IF: RSS Feed contains "URGENTE" OR "BREAKING"
THEN: Immediate multi-platform sharing
```

## Manutenzione

### Aggiornamenti del Feed
- I feed sono automaticamente aggiornati ad ogni nuovo articolo approvato
- Non richiedono manutenzione manuale
- Backup automatico tramite Django

### Monitoraggio Periodico
- Controlla settimanalmente l'attività IFTTT
- Verifica che tutti i social siano ancora connessi
- Testa periodicamente con articoli di prova

---

**Nota**: Questa soluzione sostituisce il sistema di API dirette, eliminando la complessità della gestione delle credenziali social e migliorando l'affidabilità della condivisione automatica.