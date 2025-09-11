import logging
import threading
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from .models import Articolo
from .email_notifications import send_article_approval_notification
from .social_sharing import social_manager

logger = logging.getLogger(__name__)


def invalidate_rss_feeds():
    """
    Invalida la cache dei feed RSS per forzare l'aggiornamento immediato
    """
    try:
        # Django syndication framework usa cache interno per i feed
        # Invalidiamo le chiavi di cache comuni per i feed RSS
        cache_keys_to_invalidate = [
            'syndication:rss-feed',
            'syndication:atom-feed', 
            'syndication:recenti-feed',
            'feeds:ArticoliFeedRSS',
            'feeds:ArticoliFeedAtom',
            'feeds:ArticoliRecentiFeed',
        ]
        
        for key in cache_keys_to_invalidate:
            cache.delete(key)
        
        # Invalida anche eventuali cache con timestamp
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        cache.delete(f'rss_feed_{today}')
        cache.delete(f'rss_recenti_{today}')
        
        logger.info("Cache dei feed RSS invalidata per aggiornamento immediato")
        
    except Exception as e:
        logger.error(f"Errore nell'invalidazione cache RSS: {e}")


@receiver(pre_save, sender=Articolo)
def track_approval_change(sender, instance, **kwargs):
    """Traccia i cambiamenti dello stato di approvazione prima del salvataggio"""
    if instance.pk:
        try:
            # Ottieni lo stato precedente dall'oggetto esistente
            old_instance = Articolo.objects.get(pk=instance.pk)
            # Salva lo stato precedente in cache per il post_save
            cache.set(f'article_approval_state_{instance.pk}', {
                'was_approved': old_instance.approvato,
                'is_approved': instance.approvato
            }, 60)  # Cache per 1 minuto
        except Articolo.DoesNotExist:
            # Caso edge: pk esiste ma oggetto non trovato
            cache.set(f'article_approval_state_{instance.pk}', {
                'was_approved': False,
                'is_approved': instance.approvato
            }, 60)
    else:
        # Nuovo articolo (pk è None) - usa l'id dell'oggetto Python temporaneamente
        cache.set(f'article_approval_state_new_{id(instance)}', {
            'was_approved': False,
            'is_approved': instance.approvato
        }, 60)


@receiver(post_save, sender=Articolo)
def article_created_notification(sender, instance, created, **kwargs):
    """
    Invia notifica email quando viene creato un nuovo articolo non approvato
    """
    if created and not instance.approvato:
        logger.info(f"Nuovo articolo creato (ID: {instance.id}) - Invio notifica email")
        
        # Invia email di notifica in modo asincrono per non bloccare il salvataggio
        try:
            success = send_article_approval_notification(instance)
            if success:
                logger.info(f"Notifica email inviata per articolo ID {instance.id}")
            else:
                logger.warning(f"Impossibile inviare notifica email per articolo ID {instance.id}")
        except Exception as e:
            logger.error(f"Errore nell'invio notifica per articolo ID {instance.id}: {e}")


@receiver(post_save, sender=Articolo)
def handle_article_approval(sender, instance, created, **kwargs):
    """
    Gestisce la condivisione automatica quando un articolo viene approvato
    """
    # Recupera lo stato di approvazione dalla cache
    approval_state = cache.get(f'article_approval_state_{instance.pk}')
    
    # Per articoli nuovi, controlla anche la cache temporanea
    if not approval_state and created:
        approval_state = cache.get(f'article_approval_state_new_{id(instance)}')
        if approval_state:
            cache.delete(f'article_approval_state_new_{id(instance)}')
    
    if not approval_state:
        # Se non c'è cache, assumiamo sia un nuovo articolo
        was_approved = False
        is_approved = instance.approvato
    else:
        was_approved = approval_state['was_approved']
        is_approved = approval_state['is_approved']
        # Pulizia cache
        if instance.pk:
            cache.delete(f'article_approval_state_{instance.pk}')
    
    # Condividi se:
    # 1. L'articolo è passato da non approvato ad approvato (approvazione manuale)
    # 2. L'articolo è nuovo e già approvato (auto-approvazione)
    if (not was_approved and is_approved) or (created and is_approved):
        logger.info(f"Articolo '{instance.titolo}' appena approvato, aggiorno feed RSS e avvio condivisione automatica")
        
        # Invalida immediatamente la cache RSS per IFTTT
        invalidate_rss_feeds()
        
        # Avvia la condivisione in background per non bloccare la request
        thread = threading.Thread(
            target=_share_article_background,
            args=(instance.pk, instance.titolo)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Feed RSS aggiornato e thread di condivisione avviato per articolo: {instance.titolo}")


def _share_article_background(article_id, article_title):
    """
    Esegue la condivisione sui social in background
    """
    try:
        # Piccolo ritardo per evitare race conditions con la transazione di approvazione
        import time
        time.sleep(1)
        
        # Ricarica l'articolo dal database per sicurezza
        articolo = Articolo.objects.get(pk=article_id)
        
        # Verifica che sia ancora approvato (doppio controllo)
        if not articolo.approvato:
            logger.warning(f"Articolo {article_title} non più approvato, annullo condivisione. Controllare signals, potrebbe essere un race condition.")
            return
        
        # Esegui la condivisione
        results = social_manager.share_article_on_approval(articolo)
        
        # Log dei risultati
        successful_platforms = [platform for platform, success in results.items() if success]
        failed_platforms = [platform for platform, success in results.items() if not success]
        
        if successful_platforms:
            logger.info(f"Condivisione completata con successo per '{article_title}' su: {', '.join(successful_platforms)}")
        
        if failed_platforms:
            logger.warning(f"Condivisione fallita per '{article_title}' su: {', '.join(failed_platforms)}")
            
    except Articolo.DoesNotExist:
        logger.error(f"Articolo con ID {article_id} non trovato durante condivisione")
    except Exception as e:
        logger.error(f"Errore durante condivisione background per articolo '{article_title}': {str(e)}")