import logging
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import time
import tempfile
import os
import requests
from anthropic import Anthropic
import django
from django.conf import settings

from home.models import Articolo

logger = logging.getLogger(__name__)

def trascrivi(video_id):
    """Estrae la trascrizione da un video YouTube con gestione dirette"""
    try:
        logger.info(f"Inizio trascrizione per video ID: {video_id}")

        # Crea un'istanza dell'API e usa il metodo fetch
        api = YouTubeTranscriptApi()
        transcript_data = api.fetch(video_id, languages=['it'])

        # Concatena tutto il testo dalla trascrizione fetchata
        text = " ".join([snippet.text for snippet in transcript_data])
        logger.info(f"Trascrizione completata: {len(text)} caratteri")

        return text

    except (TranscriptsDisabled, NoTranscriptFound) as e:
        # Verifica se è una diretta in corso
        if _is_live_stream(video_id):
            logger.info(f"Video {video_id} è una diretta in corso - verrà riprovato più tardi")
            _schedule_retry(video_id)
            return None
        else:
            logger.error(f"Transcript non disponibile per video {video_id}: {e}")
            raise

    except Exception as e:
        logger.error(f"Errore nella trascrizione del video {video_id}: {e}")
        raise

def _is_live_stream(video_id):
    """Controlla se un video è una diretta in corso"""
    try:
        # Usa YouTube oEmbed API per ottenere info base
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(oembed_url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            title = data.get('title', '').lower()
            # Indica diretta se nel titolo c'è "live", "diretta", "streaming"
            return any(keyword in title for keyword in ['live', 'diretta', 'streaming', 'in corso'])

        return False
    except Exception:
        # Se non riusciamo a verificare, assumiamo che sia una diretta
        return True

def _schedule_retry(video_id):
    """Programma un retry per il video"""
    try:
        retry_delay = 3600  # 1 ora
        retry_file = f"youtube_retry_{video_id}.txt"
        retry_path = os.path.join(tempfile.gettempdir(), retry_file)

        # Salva timestamp per il retry
        retry_time = time.time() + retry_delay
        with open(retry_path, 'w') as f:
            f.write(str(retry_time))

        logger.info(f"Scheduled retry for video {video_id} in {retry_delay} seconds")

    except Exception as e:
        logger.error(f"Errore scheduling retry per {video_id}: {e}")

def check_and_process_retries():
    """Controlla e processa i video in attesa di retry"""
    try:
        import glob
        retry_files = glob.glob(os.path.join(tempfile.gettempdir(), "youtube_retry_*.txt"))
        current_time = time.time()

        for retry_file in retry_files:
            try:
                with open(retry_file, 'r') as f:
                    retry_time = float(f.read().strip())

                if current_time >= retry_time:
                    # È ora di riprovare
                    video_id = os.path.basename(retry_file).replace('youtube_retry_', '').replace('.txt', '')
                    logger.info(f"Processando retry per video {video_id}")

                    # Prova di nuovo la trascrizione
                    transcript = trascrivi(video_id)
                    if transcript:
                        logger.info(f"Retry riuscito per video {video_id}")
                        # Qui potresti chiamare genera_e_salva_articolo con il video_id specifico
                        # o processare diversamente

                    # Rimuovi il file di retry
                    os.unlink(retry_file)

            except Exception as e:
                # File corrotto, rimuovilo
                try:
                    os.unlink(retry_file)
                except:
                    pass

    except Exception as e:
        logger.error(f"Errore checking pending retries: {e}")
def genera_e_salva_articolo():
    """Genera un articolo usando AI da un video YouTube hardcoded"""
    try:
        logger.info("Inizio generazione articolo")
        
        client = Anthropic(
            api_key=settings.ANTHROPIC_API_KEY
        )
        
        video_id = "MG7eulhZZqk"
        logger.info(f"Generazione articolo per video ID: {video_id}")
        
        message = client.messages.create(
            system='Sei Umberto Eco che dopo aver assistito al consiglio comunale deve scrivere un articolo che lo riassuma e lo commenti, con toni anche ironici',
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": f"{trascrivi(video_id)}"
            }],
            model="claude-sonnet-4-20250514",
        )
        
        # Estrai il testo dall'articolo generato
        articolo_testo = message.content[0].text
        logger.info(f"Articolo generato: {len(articolo_testo)} caratteri")
        
        # Estrai il titolo (prima riga) e contenuto
        linee = articolo_testo.split('\n')
        titolo = linee[0].replace('#', '').strip()[:200]
        contenuto = articolo_testo
        
        # Salva nel database
        from django.utils import timezone
        articolo = Articolo(
            titolo=titolo,
            contenuto=contenuto,
            categoria="L'Eco del Consiglio",
            approvato=False,
            data_pubblicazione=timezone.now()
        )
        articolo.save()
        
        logger.info(f"Articolo salvato nel database con ID: {articolo.id}")
        # La notifica email viene inviata automaticamente tramite il segnale post_save
        return f"Articolo salvato con ID: {articolo.id}"
        
    except Exception as e:
        logger.error(f"Errore nella generazione dell'articolo: {e}")
        raise

   