import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Articolo
from .email_notifications import send_article_approval_notification

logger = logging.getLogger(__name__)


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