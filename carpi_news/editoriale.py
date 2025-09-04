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
import anthropic

def setup_logging():
    """Configura il logging per l'editoriale"""
    return setup_centralized_logger('editoriale_quotidiano', 'INFO')

def raccoglie_articoli_ieri():
    """Raccoglie tutti gli articoli approvati del giorno precedente"""
    ieri = timezone.now().date() - timedelta(days=1)
    inizio_ieri = timezone.make_aware(datetime.combine(ieri, datetime.min.time()))
    fine_ieri = timezone.make_aware(datetime.combine(ieri, datetime.max.time()))
    
    articoli = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__range=(inizio_ieri, fine_ieri)
    ).exclude(
        categoria='Editoriale'  # Esclude editoriali precedenti
    ).order_by('categoria', 'data_pubblicazione')
    
    return articoli

def raggruppa_per_categoria(articoli):
    """Raggruppa gli articoli per categoria"""
    categorie = {}
    for articolo in articoli:
        categoria = articolo.categoria or 'Generale'
        if categoria not in categorie:
            categorie[categoria] = []
        categorie[categoria].append(articolo)
    
    return categorie

def genera_editoriale_ai(categorie, data_ieri):
    """Genera l'editoriale usando Claude AI"""
    
    print("DEBUG: Inizio generazione editoriale AI")
    logging.info("Inizio generazione editoriale AI")
    
    # Prepara il contenuto per l'AI
    contenuto_articoli = []
    conteggio_totale = 0
    
    for categoria, articoli in categorie.items():
        # Fix encoding issues
        categoria_clean = categoria.replace('�', 'à').replace('�', 'è').replace('�', 'ì').replace('�', 'ò').replace('�', 'ù')
        
        # Ordina gli articoli per numero di views (decrescente) per dare peso agli articoli più visti
        articoli_ordinati = sorted(articoli, key=lambda x: x.views, reverse=True)
        
        contenuto_articoli.append(f"\n## {categoria_clean.upper()} ({len(articoli_ordinati)} articoli)")
        for articolo in articoli_ordinati:
            titolo_clean = articolo.titolo.replace('�', 'à').replace('�', 'è').replace('�', 'ì').replace('�', 'ò').replace('�', 'ù')
            sommario_clean = articolo.contenuto.replace('�', 'à').replace('�', 'è').replace('�', 'ì').replace('�', 'ò').replace('�', 'ù')
            # Aggiungi URL dell'articolo per permettere i link
            article_url = f"/articolo/{articolo.slug}/"
            # Includi il numero di views nel prompt per dare peso agli articoli
            views_info = f" ({articolo.views} visualizzazioni)"
            contenuto_articoli.append(f"- **{titolo_clean}**{views_info} (URL: {article_url})")
            contenuto_articoli.append(f"  {sommario_clean}...\n")
            conteggio_totale += 1
    
    if conteggio_totale == 0:
        return None, None
    
    # Prompt per l'AI
    logging.info(f"Lunghezza contenuto articoli: {len(''.join(contenuto_articoli))} caratteri")
    prompt_editoriale = f"""Sei Umberto Eco che scrive l'editoriale quotidiano per "Ombra del Portico".

Oggi è {timezone.now().strftime('%d %B %Y')} e devi scrivere l'editoriale che riassume e commenti le notizie di ieri ({data_ieri.strftime('%d %B %Y')}) a Carpi.

ARTICOLI DI IERI ({conteggio_totale} articoli totali):
{"".join(contenuto_articoli)}

COMPITO:
Scrivi un editoriale di circa 500-800 parole che:
- Identifichi i temi principali emersi ieri a Carpi
- Offra una riflessione intelligente e molto ironica sui fatti
- Colleghi gli eventi in una narrazione coerente
- Evidenzi l'impatto sulla comunità carpigiana
- Concluda con una considerazione sulla della città

IMPORTANTE: Dai maggiore peso e spazio agli articoli con più visualizzazioni.

STILE:

- Uso dell'ironia sottile quando appropriato  
- Linguaggio colto ma comprensibile
- Prospettiva da osservatore attento della città

FORMATO:
- Un titolo accattivante (max 80 caratteri)
- Testo dell'editoriale ben strutturato in HTML
- Usa **grassetto** per concetti chiave (che diventeranno <strong>)
- Paragrafi racchiusi in tag <p>
- Separa i paragrafi normalmente (non doppia riga)
- COLLEGAMENTI: Quando citi un avvenimento descritto negli articoli, crea un link usando <a href="URL">testo</a> nella parte di testo corretta

IMPORTANTE: 
- Non inventare fatti non presenti negli articoli forniti
- Usa gli URL forniti per creare collegamenti ipertestuali agli articoli citati
- I link devono essere pertinenti e arricchire la lettura

ESEMPIO DI FORMATO RICHIESTO CON LINK:
<p><strong>Solidarietà cittadina:</strong> Il <a href="/articolo/titolo-solidarieta-del-sindaco-righi-a-estefani-yan-dopo-gli-insulti-razzisti/">gesto del sindaco verso Estefani Yan</a> dimostra i valori della nostra comunità.</p>
<p>Mentre si discute di <a href="/articolo/zanzara-tigre-nuovo-intervento-di-disinfestazione-nel-centro-sud-della-citta/">emergenza zanzare</a>, la città guarda anche al mondo con la <a href="/articolo/carpi-si-unisce-alla-flotilla-della-pace-giovedi-il-presidio-per-gaza/">partecipazione alla Flotilla per Gaza</a>.</p>
<p><strong>Conclusione:</strong> Riflessioni finali sulla città.</p>"""

    logging.info(f"Lunghezza prompt completo: {len(prompt_editoriale)} caratteri")
    
    # Debug: save prompt to file for inspection
    with open('debug_prompt.txt', 'w', encoding='utf-8') as f:
        f.write(prompt_editoriale)
    logging.info("Prompt salvato in debug_prompt.txt")
    
    try:
        # Chiamata all'AI con retry
        logging.info("Inizializzazione client Anthropic...")
        
        from django.conf import settings
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            logging.error("ANTHROPIC_API_KEY non configurata!")
            return None, None
            
        client = anthropic.Anthropic(api_key=api_key)
        logging.info("Client Anthropic inizializzato con successo")
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt_editoriale}]
        )
            
        contenuto_completo = response.content[0].text
        
        # Estrai titolo e contenuto
        linee = contenuto_completo.split('\n')
        titolo = linee[0].replace('#', '').replace('*', '').strip()
        contenuto = '\n'.join(linee[1:]).strip()
        
        # Applica content polisher per uniformare il layout
        polisher = ContentPolisher()
        
        # Pulisci il titolo (senza HTML)
        titolo = polisher.clean_title_plain(titolo)
        
        # Converti il contenuto in formato uniforme (markdown -> HTML)
        contenuto_pulito = polisher.clean_content(contenuto)
        
        # Limita titolo
        if len(titolo) > 200:
            titolo = titolo[:197] + "..."
            
        return titolo, contenuto_pulito
        
    except Exception as e:
        print(f"DEBUG: Errore nella generazione AI dell'editoriale: {e}")
        print(f"DEBUG: Tipo errore: {type(e).__name__}")
        import traceback
        print(f"DEBUG: Traceback completo: {traceback.format_exc()}")
        logging.error(f"Errore nella generazione AI dell'editoriale: {e}")
        logging.error(f"Tipo errore: {type(e).__name__}")
        logging.error(f"Traceback completo: {traceback.format_exc()}")
        return None, None

def salva_editoriale(titolo, contenuto, data_ieri, numero_articoli):
    """Salva l'editoriale nel database"""
    
    # Crea sommario
    
    # Crea slug unico
    data_str = timezone.now().strftime('%Y-%m-%d')
    slug_base = f"editoriale-{data_str}"
    slug = slug_base
    counter = 1
    
    while Articolo.objects.filter(slug=slug).exists():
        slug = f"{slug_base}-{counter}"
        counter += 1
    
    # Crea sommario pulito senza tag HTML
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
        fonte="www.carpinews.it",
        foto=static('home/images/portico_logo_nopayoff.svg'),
    )
    
    return editoriale

def main():
    """Funzione principale"""
    logger = setup_logging()
    
    try:
        logger.info("🏛️ Avvio generazione editoriale quotidiano")
        
        # 1. Raccogli articoli di ieri
        articoli = raccoglie_articoli_ieri()
        if not articoli.exists():
            logger.info("Nessun articolo trovato per ieri, skip editoriale")
            return
            
        data_ieri = (timezone.now().date() - timedelta(days=1))
        logger.info(f"Trovati {articoli.count()} articoli del {data_ieri.strftime('%d/%m/%Y')}")
        
        # 2. Raggruppa per categoria
        categorie = raggruppa_per_categoria(articoli)
        logger.info(f"Articoli raggruppati in {len(categorie)} categorie: {list(categorie.keys())}")
        
        # 3. Genera editoriale
        logger.info("Generazione editoriale con AI...")
        titolo, contenuto = genera_editoriale_ai(categorie, data_ieri)
        
        if not titolo or not contenuto:
            logger.error("Impossibile generare editoriale")
            return
            
        logger.info(f"Editoriale generato: '{titolo}' ({len(contenuto)} caratteri)")
        
        # 4. Salva nel database
        editoriale = salva_editoriale(titolo, contenuto, data_ieri, articoli.count())
        logger.info(f"Editoriale salvato con ID {editoriale.id} e slug '{editoriale.slug}'")
        
        # 5. Report finale
        print("="*60)
        print("EDITORIALE QUOTIDIANO GENERATO")
        print("="*60)
        print(f"Data: {timezone.now().strftime('%d %B %Y alle %H:%M')}")
        print(f"Articoli analizzati: {articoli.count()}")
        print(f"Categorie: {', '.join(categorie.keys())}")
        print(f"Titolo: {titolo}")
        print(f"Slug: {editoriale.slug}")
        print(f"Status: Pubblicato e approvato")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Errore nella generazione editoriale: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
