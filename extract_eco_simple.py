"""
Script semplice per estrarre articolo da video YouTube
"""
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import re
import json
import sqlite3
from datetime import datetime
import unicodedata

# Carica variabili ambiente
load_dotenv(r'c:\news\carpi_news\.env')

VIDEO_URL = "https://www.youtube.com/watch?v=g6iAJPXANPY"
VIDEO_ID = "g6iAJPXANPY"
DB_PATH = r'c:\news\carpi_news\db.sqlite3'

def extract_transcript(video_id):
    """Estrae il trascritto dal video YouTube"""
    try:
        # Crea istanza API e ottieni lista transcript disponibili
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # Prova prima con transcript italiano manuale
        transcript = None
        try:
            transcript = transcript_list.find_transcript(['it'])
            print("   Trovato transcript italiano")
        except NoTranscriptFound:
            # Se non c'è italiano manuale, prova con autogenerato
            try:
                transcript = transcript_list.find_generated_transcript(['it'])
                print("   Trovato transcript autogenerato italiano")
            except NoTranscriptFound:
                # Se non c'è nemmeno autogenerato, prova con qualsiasi lingua
                for t in transcript_list:
                    transcript = t
                    print(f"   Usando transcript in {t.language}")
                    break

        if not transcript:
            raise NoTranscriptFound("Nessun transcript disponibile")

        # Estrai il testo dal transcript
        transcript_data = transcript.fetch()
        text = " ".join([
            item['text'] if isinstance(item, dict) else item.text
            for item in transcript_data
        ])
        return text
    except Exception as e:
        print(f"Errore estrazione trascritto: {e}")
        return None

def generate_article(transcript):
    """Genera articolo usando Claude AI"""
    client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    prompt = f"""Sei un giornalista esperto che scrive articoli per un portale di notizie locali di Carpi.

Trascrizione video YouTube:
{transcript}

Crea un articolo giornalistico professionale seguendo queste regole:
1. Titolo accattivante e informativo (max 100 caratteri)
2. Contenuto completo e dettagliato (400-600 parole)
3. Stile giornalistico professionale
4. Focus su fatti e informazioni concrete
5. Linguaggio chiaro e accessibile

Formato richiesto (JSON):
{{
    "titolo": "titolo dell'articolo",
    "contenuto": "contenuto completo dell'articolo",
    "sommario": "riassunto di 2-3 righe"
}}

Restituisci SOLO il JSON, senza altri testi."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6-20260217",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text
        # Estrai JSON dalla risposta
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return None
    except Exception as e:
        print(f"Errore generazione articolo: {e}")
        return None

def slugify_title(text):
    """Converti titolo in slug URL-friendly"""
    # Normalizza unicode
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    # Converti in minuscolo e sostituisci spazi con trattini
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text

def save_to_db(article_data):
    """Salva articolo direttamente nel database SQLite"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Genera slug dal titolo
        slug = slugify_title(article_data['titolo'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            INSERT INTO home_articolo
            (titolo, contenuto, sommario, categoria, slug, approvato, fonte, foto, views,
             data_creazione, data_pubblicazione, data_modifica,
             total_price, spotlight, telegram_notified,
             is_pubbliredazionale, nome_azienda, sito_web,
             intervistato_nome, intervistato_cognome, intervistato_ruolo,
             payment_status, payment_method, payment_transaction_id,
             discount_amount, admin_notes, interview_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article_data['titolo'],
            article_data['contenuto'],
            article_data['sommario'],
            'Generale',
            slug,
            0,  # Non approvato
            VIDEO_URL,
            f"https://img.youtube.com/vi/{VIDEO_ID}/maxresdefault.jpg",
            0,  # views
            now,  # data_creazione
            now,  # data_pubblicazione
            now,  # data_modifica
            200.00,  # total_price (default)
            0,  # spotlight
            0,  # telegram_notified
            0,  # is_pubbliredazionale
            '',  # nome_azienda
            '',  # sito_web
            '',  # intervistato_nome
            '',  # intervistato_cognome
            '',  # intervistato_ruolo
            '',  # payment_status
            '',  # payment_method
            '',  # payment_transaction_id
            0.00,  # discount_amount
            '',  # admin_notes
            '{}'  # interview_data (JSON vuoto)
        ))

        article_id = cursor.lastrowid
        conn.commit()
        conn.close()

        print(f"\n[OK] Articolo salvato con successo!")
        print(f"ID: {article_id}")
        print(f"Titolo: {article_data['titolo']}")
        print(f"Slug: {slug}")
        print(f"Approvato: No (richiede approvazione)")
        return article_id

    except Exception as e:
        print(f"Errore salvataggio: {e}")
        return None

if __name__ == "__main__":
    print(f"Estrazione articolo da video: {VIDEO_URL}\n")

    # 1. Estrai trascritto
    print("1. Estrazione trascritto...")
    transcript = extract_transcript(VIDEO_ID)
    if not transcript:
        print("[X] Impossibile estrarre il trascritto")
        exit(1)
    print(f"[OK] Trascritto estratto ({len(transcript)} caratteri)")

    # 2. Genera articolo
    print("\n2. Generazione articolo con AI...")
    article_data = generate_article(transcript)
    if not article_data:
        print("[X] Impossibile generare l'articolo")
        exit(1)
    print(f"[OK] Articolo generato")
    print(f"   Titolo: {article_data['titolo']}")

    # 3. Salva nel database
    print("\n3. Salvataggio nel database...")
    article_id = save_to_db(article_data)
    if not article_id:
        exit(1)

    print(f"\n[COMPLETATO] L'articolo e' ora in attesa di approvazione nell'admin.")
