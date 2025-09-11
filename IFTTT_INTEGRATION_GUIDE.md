# Guida Integrazione IFTTT per Social Sharing

## Overview

Questa guida spiega come configurare IFTTT (If This Then That) per automatizzare la condivisione degli articoli di Ombra del Portico sui social media utilizzando i feed RSS.

## Feed RSS Disponibili

Il sito offre tre feed RSS ottimizzati per diversi utilizzi con **aggiornamento immediato** quando gli articoli vengono approvati:

### 1. Feed Principale
- **URL**: `https://ombradelportico.it/feed/rss/`
- **Contenuto**: Ultimi 10 articoli approvati
- **TTL**: 1 minuto (aggiornamento immediato)
- **Caratteristiche**: Feed completo con immagini assolute e metadati
- **Utilizzo**: Condivisione generale di tutti gli articoli

### 2. Feed Recenti (⭐ Consigliato per IFTTT)
- **URL**: `https://ombradelportico.it/feed/recenti/`
- **Contenuto**: Articoli delle ultime 24 ore
- **TTL**: 1 minuto (aggiornamento immediato)
- **Caratteristiche**: 
  - ⚡ **Aggiornamento istantaneo** quando articoli vengono approvati
  - 📰 Emoji automatiche per categoria (⚽ Sport, 🎭 Cultura, 🏛️ Politica, 💼 Economia)
  - 🏷️ Hashtag ottimizzati (#CarpiNews #OmbraDelPortico + categoria)
  - 📝 Descrizioni ottimizzate (250 caratteri + hashtag)
  - 🖼️ URL immagini assoluti (compatibili con tutti i social)
- **Utilizzo**: Condivisione immediata su social media - **PERFETTO PER IFTTT**

### 3. Feed Atom
- **URL**: `https://ombradelportico.it/feed/atom/`
- **Contenuto**: Ultimi 10 articoli in formato Atom
- **TTL**: Standard Django
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

### ✅ Vantaggi Principali
- **🚫 Nessuna API complessa**: Non serve gestire API key di Facebook/Twitter/Instagram
- **⚡ Aggiornamento immediato**: Feed RSS aggiornati entro 1 minuto dall'approvazione
- **🛡️ Affidabilità**: IFTTT gestisce retry, errori e rate limiting automaticamente
- **🎯 Flessibilità**: Facile aggiungere nuove piattaforme (LinkedIn, Pinterest, etc.)
- **🎛️ Controllo avanzato**: Filtri, orari, personalizzazione per ogni social
- **💰 Economico**: Funziona con account IFTTT gratuiti
- **🔧 Manutenzione zero**: Nessun aggiornamento API da seguire
- **📊 Analytics**: IFTTT fornisce statistiche di esecuzione

### 🚀 Prestazioni Ottimizzate
- **Prima**: Ritardo 15-60 minuti per rilevare nuovi articoli
- **Ora**: Rilevamento entro 1-5 minuti dall'approvazione
- **Cache intelligente**: Invalidazione automatica sui cambiamenti di stato
- **TTL ottimizzato**: Da 60 minuti a 1 minuto per tutti i feed

### ⚠️ Considerazioni
- **Ritardo minimo**: IFTTT controlla i feed ogni 1-15 minuti (molto migliorato)
- **Personalizzazione**: Formato predefinito, ma altamente ottimizzato per social
- **Dipendenza servizio**: IFTTT ha uptime 99.9%+ e supporto professionale

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

## Novità Tecniche (Versione 2.0)

### 🔄 Sistema di Aggiornamento Immediato
Il sistema utilizza Django signals per invalidare la cache RSS immediatamente quando:
- Un articolo viene creato con `auto_approve=True`
- Un articolo esistente viene cambiato da `approvato=False` a `approvato=True`

### 🖼️ Gestione Intelligente Immagini
- **URL assoluti**: Conversione automatica di percorsi locali (`/media/images/`) in URL completi
- **Compatibilità social**: Support per tutti i formati immagine (JPG, PNG, GIF, WebP)
- **Fallback graceful**: Se l'immagine non è disponibile, condivisione solo testo

### 📱 Telegram Integration Mantenuta
- **Bot API diretta**: Telegram continua ad utilizzare API diretta per condivisione immediata
- **Foto support**: Invio automatico di immagini quando disponibili
- **Markdown formatting**: Titoli in grassetto e link formattati

### 🧹 Codice Semplificato
- **-200 righe**: Rimosso codice Facebook/Twitter API complex
- **-1 dipendenza**: Eliminato `tweepy` da requirements.txt
- **+RSS feeds**: Aggiunto sistema RSS nativo Django ottimizzato

---

**Nota**: Questa soluzione v2.0 sostituisce completamente il sistema API dirette per Facebook/Twitter, eliminando la complessità della gestione delle credenziali social e migliorando drammaticamente l'affidabilità e velocità della condivisione automatica.

**Migrazione**: Il sistema è retrocompatibile. Gli articoli esistenti continueranno a funzionare, mentre i nuovi articoli beneficeranno immediatamente del sistema RSS+IFTTT ottimizzato.