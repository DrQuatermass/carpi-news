import logging
from youtube_transcript_api import YouTubeTranscriptApi
import time
from anthropic import Anthropic
import os
import django
from django.conf import settings

from home.models import Articolo

logger = logging.getLogger(__name__)

def trascrivi(video_id):
    """Estrae la trascrizione da un video YouTube"""
    try:
        logger.info(f"Inizio trascrizione per video ID: {video_id}")
        
        # Crea un'istanza dell'API
        api = YouTubeTranscriptApi()

        # Usa il metodo fetch() con la nuova API
        transcript = api.fetch(video_id, languages=['it'])
        
        # Concatena tutto il testo
        text = " ".join([entry.text for entry in transcript])
        logger.info(f"Trascrizione completata: {len(text)} caratteri")


        return text
    except Exception as e:
        logger.error(f"Errore nella trascrizione del video {video_id}: {e}")
        raise
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

   