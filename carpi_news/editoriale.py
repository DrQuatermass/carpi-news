#!/usr/bin/env python3
"""
Script per generare editoriale quotidiano aggregando gli articoli del giorno precedente
Esecuzione programmata: ogni mattina alle 8:00
"""
import sys
import os
import django
from datetime import datetime, timedelta
from django.utils import timezone
import logging
import time

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carpi_news.settings")
django.setup()

from home.models import Articolo
from home.logger_config import setup_centralized_logger
from home.content_polisher import ContentPolisher
from django.templatetags.static import static
from home.rubriche_ai import genera_con_ricerca

# Fonti web e modello dell'ultima generazione, salvati con l'editoriale
ULTIMA_GENERAZIONE = {'fonti_web': [], 'modello': None}

def setup_logging():
    """Configura il logging per l'editoriale"""
    return setup_centralized_logger('editoriale_quotidiano', 'INFO')

MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto',
        'settembre', 'ottobre', 'novembre', 'dicembre']
GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']

# Selezione delle fonti: gli articoli delle ultime 24 ore; solo se sono meno di MIN_CANDIDATI
# si allarga a 48 (dal 28/9/2026 si approvano pochi pezzi al giorno). Con 48 ore fisse vinceva
# il pezzo di due giorni prima, che aveva piu' visite. Punteggio per visite all'ora (un pezzo
# uscito alle 18 non parte svantaggiato). Esclusi gli articoli gia' citati negli editoriali
# degli ultimi 7 giorni, approvati o no: gli editoriali non si approvano quasi mai e col solo
# filtro sugli approvati il 6/11 e' uscito lo stesso tema del 5/11.
# Con meno di MIN_CANDIDATI articoli l'editoriale salta il giorno.
FINESTRE_ORE = (24, 48)
FINESTRA_ORE = FINESTRE_ORE[-1]
MAX_CANDIDATI = 6
MIN_CANDIDATI = 2
CATEGORIE_ESCLUSE = ['Editoriale', 'Cosa fare oggi', 'Cultura & Eventi']


def data_italiana(d):
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year}"


def _slug_gia_commentati(giorni=7):
    import re
    slug = set()
    for testo in Articolo.objects.filter(
            categoria='Editoriale',
            data_creazione__gte=timezone.now() - timedelta(days=giorni)).values_list('contenuto', flat=True):
        slug.update(re.findall(r'href="/articolo/([^/"]+)/', testo or ''))
    return slug


def raccoglie_articoli_ieri():
    """Fino a MAX_CANDIDATI articoli delle ultime 24 ore (48 se non bastano), per visite all'ora.

    Esclusi rubriche, eventi, pubbliredazionali e articoli gia' commentati di recente.
    Ritorna una lista, vuota se il materiale non basta per un editoriale."""
    adesso = timezone.now()
    gia_visti = _slug_gia_commentati()

    def visite_all_ora(a):
        ore = max((adesso - a.data_pubblicazione).total_seconds() / 3600, 6)
        return a.views / ore

    for ore in FINESTRE_ORE:
        qs = Articolo.objects.filter(
            approvato=True,
            is_pubbliredazionale=False,
            data_pubblicazione__range=(adesso - timedelta(hours=ore), adesso),
        ).exclude(categoria__in=CATEGORIE_ESCLUSE)
        candidati = [a for a in qs if a.slug not in gia_visti]
        if len(candidati) >= MIN_CANDIDATI:
            logging.info(f"Editoriale: {len(candidati)} articoli candidati nelle ultime {ore} ore")
            candidati.sort(key=visite_all_ora, reverse=True)
            return candidati[:MAX_CANDIDATI]
    return []


def raggruppa_per_categoria(articoli):
    """Raggruppa gli articoli per categoria"""
    categorie = {}
    for articolo in articoli:
        categorie.setdefault(articolo.categoria or 'Generale', []).append(articolo)
    return categorie


def genera_editoriale_ai(categorie, data_ieri):
    """Genera l'editoriale con Claude. Ritorna (titolo, contenuto, sommario) o (None, None, None)."""
    import re
    from home.universal_news_monitor import parse_ai_article_json

    logging.info("Inizio generazione editoriale AI")
    articoli = [a for lista in categorie.values() for a in lista]
    if not articoli:
        return None, None, None

    blocchi = []
    for a in articoli:
        testo = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', a.contenuto or '')).strip()
        blocchi.append(f"- {a.titolo} [{a.categoria}, {a.views} visualizzazioni] (URL: /articolo/{a.slug}/)\n  {testo}\n")

    prompt_editoriale = f"""Scrivi l'editoriale quotidiano di "Ombra del Portico", giornale online di Carpi. Lo firma la redazione: una voce colta, ironica quando serve, che conosce la città e chi la abita. Non imitare nessuno scrittore o giornalista famoso.

Oggi è {data_italiana(timezone.localdate())}. Commenti le notizie delle ultime ore a Carpi.

ARTICOLI PIÙ LETTI (ultimi due giorni, dal più letto; esclusi eventi e rubriche):
{"".join(blocchi)}
COMPITO:
Scrivi un commento di 400-700 parole.
- Non è un riassunto. Scegli una notizia, al massimo due se hanno un legame reale, che ha davvero qualcosa da dire, e costruisci il pezzo intorno a quella. Le altre restano fuori.
- Parti da un fatto concreto, non da una riflessione generale.
- L'opinione deve poggiare su fatti presenti negli articoli. Puoi dire che qualcosa non torna, ma spiega perché. Niente rilievi formali sui comunicati (nomi, firme, cariche, refusi) se non cambiano la sostanza.
- Ironia sul potere, sulla burocrazia e sulle contraddizioni; mai su vittime, malati o persone in difficoltà.
- Chiudi su un fatto, una domanda aperta o un'immagine concreta, non su una morale generale sulla città.

EVITA (sono già comparse troppe volte negli editoriali precedenti):
- aperture come "Ci sono giornate in cui...", "Esiste una semiotica...", "Ieri Carpi ci ha raccontato...", "Se un marziano..."
- raccordi come "quattro storie", "un'unica grammatica", "stessa grammatica", "una sola morale", "il filo rosso", "il tema del giorno"
- riferimenti a semiotica e semiologi
- etichette nel testo come "Conclusione:", "La morale" o "In sintesi:"

STILE: linguaggio colto ma comprensibile, frasi di lunghezza varia, niente aggettivi enfatici. Grassetto (<strong>) con parsimonia.

COLLEGAMENTI: quando citi un fatto di uno degli articoli, metti un link <a href="URL">testo</a> sulle parole giuste, usando gli URL forniti. Non inventare fatti che non sono negli articoli.

RISPOSTA: solo un oggetto JSON valido, senza testo fuori e senza blocchi ```, con questi campi:
- "titolo": titolo dell'editoriale, testo semplice, massimo 80 caratteri, in italiano corretto;
- "sommario": una o due frasi (massimo 250 caratteri), testo semplice, che dicono di cosa parla e qual è la tesi: finisce nei post social sotto il titolo;
- "contenuto": il testo in HTML, paragrafi in <p>, senza titolo e senza <h1>."""

    try:
        from django.conf import settings
        if not settings.ANTHROPIC_API_KEY:
            logging.error("ANTHROPIC_API_KEY non configurata!")
            return None, None, None

        # Modello, ricerca web e tracking costi: home/rubriche_ai.py
        esito = genera_con_ricerca(prompt_editoriale, operation='editoriale_quotidiano')
        ULTIMA_GENERAZIONE['fonti_web'] = esito['fonti_web']
        ULTIMA_GENERAZIONE['modello'] = esito['modello']
        logging.info("Editoriale generato con %s, %d ricerche web" % (esito['modello'], esito['ricerche']))

        polisher = ContentPolisher()
        parsed = parse_ai_article_json(esito['testo'])
        if parsed:
            titolo = parsed.get('titolo', '')
            contenuto = parsed.get('contenuto', '')
            sommario = polisher.clean_content_plain(parsed.get('sommario', ''))[:300]
        else:
            # Risposta non JSON: titolo sulla prima riga, come in passato
            linee = esito['testo'].split('\n')
            titolo = linee[0].replace('#', '').replace('*', '')
            contenuto = '\n'.join(linee[1:])
            sommario = ''

        titolo = polisher.clean_title_plain(titolo.strip())
        if len(titolo) > 200:
            titolo = titolo[:197] + "..."
        return titolo, polisher.clean_content(contenuto.strip()), sommario

    except Exception as e:
        import traceback
        logging.error(f"Errore nella generazione AI dell'editoriale: {e}")
        logging.error(f"Traceback completo: {traceback.format_exc()}")
        return None, None, None


def salva_editoriale(titolo, contenuto, data_ieri, numero_articoli, sommario=''):
    """Salva l'editoriale nel database (da approvare). Il sommario viene dall'AI; se manca,
    l'inizio del testo."""

    # Crea slug unico
    data_str = timezone.now().strftime('%Y-%m-%d')
    slug_base = f"editoriale-{data_str}"
    slug = slug_base
    counter = 1
    
    while Articolo.objects.filter(slug=slug).exists():
        slug = f"{slug_base}-{counter}"
        counter += 1
    
    if not sommario:
        import re
        sommario_clean = re.sub(r'<[^>]+>', '', contenuto)  # Rimuovi tag HTML
        sommario_clean = re.sub(r'\s+', ' ', sommario_clean)  # Normalizza spazi
        sommario = sommario_clean[:200].strip() + '...' if len(sommario_clean) > 200 else sommario_clean.strip()
    
    # Salva l'editoriale
    editoriale = Articolo.objects.create(
        titolo=titolo,
        contenuto=contenuto,
        sommario=sommario,
        categoria='Editoriale',
        slug=slug,
        approvato=False, 
        data_pubblicazione=timezone.now(),
        fonti_web=ULTIMA_GENERAZIONE['fonti_web'] or None,
        ai_model_used=ULTIMA_GENERAZIONE['modello'],
    
        foto=static('home/images/portico_logo_nopayoff.png'),
    )
    
    return editoriale

def main():
    """Funzione principale"""
    logger = setup_logging()

    # Lock file per prevenire esecuzioni concorrenti
    from pathlib import Path

    locks_dir = Path('locks')
    locks_dir.mkdir(exist_ok=True)
    lock_file_path = locks_dir / 'editoriale_generation.lock'

    lock_file = None
    try:
        # Apri il lock file
        lock_file = open(lock_file_path, 'w')

        # Acquisci lock esclusivo (non-blocking)
        if os.name == 'nt':  # Windows
            import msvcrt
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                logger.info("Un altro processo sta già generando l'editoriale, skip")
                return 0
        else:  # Unix/Linux
            import fcntl
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                logger.info("Un altro processo sta già generando l'editoriale, skip")
                return 0

        logger.info("🏛️ Avvio generazione editoriale quotidiano")

        # 0. Controlla se esiste già un editoriale per oggi
        today = timezone.now().date()
        existing_editoriale = Articolo.objects.filter(
            categoria='Editoriale',
            data_pubblicazione__date=today
        ).first()

        if existing_editoriale:
            logger.info(f"✓ Editoriale già esistente per oggi ({today.strftime('%d/%m/%Y')})")
            logger.info(f"  ID: {existing_editoriale.id}, Slug: {existing_editoriale.slug}")
            logger.info("  Skip generazione per evitare duplicati")
            return 0

        # 1. Raccogli gli articoli candidati (ultime 48 ore, vedi raccoglie_articoli_ieri)
        articoli = raccoglie_articoli_ieri()
        if not articoli:
            logger.info(f"Meno di {MIN_CANDIDATI} articoli nuovi nelle ultime {FINESTRA_ORE} ore, skip editoriale")
            return

        data_ieri = (timezone.now().date() - timedelta(days=1))
        logger.info(f"Candidati: {len(articoli)} articoli - " + "; ".join(a.titolo[:50] for a in articoli))
        
        # 2. Raggruppa per categoria
        categorie = raggruppa_per_categoria(articoli)
        logger.info(f"Articoli raggruppati in {len(categorie)} categorie: {list(categorie.keys())}")
        
        # 3. Genera editoriale
        logger.info("Generazione editoriale con AI...")
        titolo, contenuto, sommario = genera_editoriale_ai(categorie, data_ieri)
        
        if not titolo or not contenuto:
            logger.error("Impossibile generare editoriale")
            return
            
        logger.info(f"Editoriale generato: '{titolo}' ({len(contenuto)} caratteri)")
        
        # 4. Salva nel database
        editoriale = salva_editoriale(titolo, contenuto, data_ieri, len(articoli), sommario)
        logger.info(f"Editoriale salvato con ID {editoriale.id} e slug '{editoriale.slug}'")
        
        # 5. Report finale
        print("="*60)
        print("EDITORIALE QUOTIDIANO GENERATO")
        print("="*60)
        print(f"Data: {timezone.now().strftime('%d %B %Y alle %H:%M')}")
        print(f"Articoli candidati: {len(articoli)}")
        print(f"Categorie: {', '.join(categorie.keys())}")
        print(f"Titolo: {titolo}")
        print(f"Slug: {editoriale.slug}")
        print("Status: salvato, in attesa di approvazione")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Errore nella generazione editoriale: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
    finally:
        # Rilascia il lock
        if lock_file:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except Exception:
                pass

        return 0

if __name__ == "__main__":
    sys.exit(main())
