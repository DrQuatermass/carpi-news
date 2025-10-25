# Setup "Cosa fare oggi?" - Rubrica Giornaliera Eventi

Questa guida spiega come configurare la generazione automatica dell'articolo giornaliero "Cosa fare oggi?" che aggrega gli eventi del giorno.

## Funzionalità

- Ogni mattina alle **8:05** viene generato automaticamente un articolo
- Raccoglie tutti gli eventi del giorno dalle categorie "Cultura" ed "Eventi"
- Crea un articolo con link a tutti gli eventi
- Categoria: "Cosa fare oggi?"

## Requisiti

1. **Campo data_evento**: Gli articoli di eventi devono avere il campo `data_evento` compilato
2. **Migration**: Eseguire la migration per aggiungere il campo al database
3. **Cron job**: Configurare l'esecuzione automatica

## 1. Eseguire la Migration

```bash
cd /var/www/carpi-news/carpi_news
source ../venv/bin/activate
python manage.py migrate
```

## 2. Configurare il Cron Job

Aggiungi questa riga al crontab del server:

```bash
# Apri il crontab
crontab -e

# Aggiungi questa riga (genera articolo ogni giorno alle 8:05)
5 8 * * * cd /var/www/carpi-news && source venv/bin/activate && cd carpi_news && python manage.py genera_cosa_fare_oggi >> /var/www/carpi-news/logs/cosa_fare_oggi.log 2>&1
```

**Spiegazione:**
- `5 8 * * *`: Esegui alle 8:05 ogni giorno
- `cd /var/www/carpi-news`: Vai nella directory del progetto
- `source venv/bin/activate`: Attiva il virtual environment
- `python manage.py genera_cosa_fare_oggi`: Esegui il comando
- `>> logs/cosa_fare_oggi.log`: Salva output in un log

## 3. Testare il Comando

### Anteprima (dry-run)
```bash
python manage.py genera_cosa_fare_oggi --dry-run
```

### Generare articolo per oggi
```bash
python manage.py genera_cosa_fare_oggi
```

### Generare articolo per una data specifica
```bash
python manage.py genera_cosa_fare_oggi --data 2025-10-30
```

## 4. Workflow per gli Articoli di Eventi

Quando crei o approvi un articolo di evento:

1. **Categoria**: Imposta "Cultura" o "Eventi"
2. **Data evento**: Compila il campo `data_evento` con la data dell'evento
3. **Approva**: L'articolo deve essere approvato per essere incluso

### Nell'Admin Django

Il campo `data_evento` è ora visibile:
- Nella lista articoli (colonna dedicata)
- Nel form di modifica (dopo categoria)
- Filtrabile per categoria

## 5. Esempio Output Articolo

**Titolo:**
```
Cosa fare oggi? Mercoledì 30 ottobre
```

**Contenuto:**
```html
<p>Buongiorno! Ecco cosa succede oggi, <strong>mercoledì 30 ottobre</strong>, a Carpi e nei dintorni.</p>

<p>Abbiamo selezionato per voi <strong>3 eventi</strong> interessanti da non perdere:</p>

<h3>1. <a href="/articolo/festa-castagne-montecreto/" class="internal-link">Festa delle Castagne a Montecreto</a></h3>
<p>Tradizionale sagra autunnale con prodotti tipici...</p>
<p><a href="/articolo/festa-castagne-montecreto/" class="internal-link">👉 Leggi tutti i dettagli</a></p>

<h3>2. <a href="/articolo/halloween-formigine/" class="internal-link">Halloween a Formigine</a></h3>
...
```

## 6. Monitoraggio

### Verificare esecuzione cron
```bash
# Visualizza log
tail -f /var/www/carpi-news/logs/cosa_fare_oggi.log

# Verificare cron attivi
crontab -l
```

### Verificare articoli generati
```bash
# Tramite Django shell
python manage.py shell

>>> from home.models import Articolo
>>> from datetime import date
>>> articoli_oggi = Articolo.objects.filter(categoria="Cosa fare oggi?", data_pubblicazione__date=date.today())
>>> print(articoli_oggi.count())
```

## 7. Troubleshooting

### Nessun articolo generato?
- Verifica che esistano eventi con `data_evento` per oggi
- Controlla che gli eventi siano approvati
- Verifica che la categoria sia "Cultura" o "Eventi"
- Controlla il log: `/var/www/carpi-news/logs/cosa_fare_oggi.log`

### Cron non esegue?
```bash
# Verifica sintassi cron
crontab -l

# Controlla log cron di sistema
sudo tail -f /var/log/cron

# Test manuale
cd /var/www/carpi-news && source venv/bin/activate && cd carpi_news && python manage.py genera_cosa_fare_oggi
```

## 8. Personalizzazione

### Modificare orario esecuzione
Modifica la riga del crontab:
```
# Per 7:30
30 7 * * * cd /var/www/carpi-news && ...

# Per 9:00
0 9 * * * cd /var/www/carpi-news && ...
```

### Aggiungere altre categorie
Modifica `genera_cosa_fare_oggi.py` alla riga ~47:
```python
eventi_query = Articolo.objects.filter(
    data_evento=target_date,
    approvato=True
).filter(
    models.Q(categoria__icontains='Cultura') |
    models.Q(categoria__icontains='Eventi') |
    models.Q(categoria__icontains='Spettacoli')  # Aggiungi qui
).order_by('titolo')
```

## 9. Best Practices

1. **Compilare sempre data_evento** per articoli di eventi
2. **Anticipare la pubblicazione** degli eventi (almeno 1 giorno prima)
3. **Controllare il log** periodicamente per errori
4. **Testare con dry-run** prima di modifiche al comando
5. **Backup**: Il comando è sicuro, non modifica articoli esistenti

## Comandi Utili

```bash
# Anteprima articolo di domani
python manage.py genera_cosa_fare_oggi --data 2025-10-31 --dry-run

# Generare manualmente per oggi
python manage.py genera_cosa_fare_oggi

# Vedere tutti gli eventi con data
python manage.py shell
>>> from home.models import Articolo
>>> eventi = Articolo.objects.filter(data_evento__isnull=False).order_by('data_evento')
>>> for e in eventi:
...     print(f"{e.data_evento} - {e.titolo}")
```

## Note

- Il comando è **idempotente**: può essere eseguito più volte senza duplicare articoli (crea sempre nuovi articoli)
- Gli eventi vengono **ordinati alfabeticamente** per titolo
- Il sommario include **max 3 eventi** per leggibilità
- Lo **slug** viene generato automaticamente da Django

---

**Creato con:** Claude Code
**Data:** Ottobre 2025
**Versione:** 1.0
