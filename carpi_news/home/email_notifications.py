import logging
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_article_approval_notification(articolo):
    """
    Invia email di notifica quando un nuovo articolo richiede approvazione
    """
    try:
        # Email amministratore (configurabile in settings)
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'redazione@ombradelportico.it')
        
        # Dominio del sito (usa il primo ALLOWED_HOSTS in produzione)
        if hasattr(settings, 'ALLOWED_HOSTS') and settings.ALLOWED_HOSTS:
            # Prendi il primo dominio che non sia localhost/127.0.0.1
            domain = next((host for host in settings.ALLOWED_HOSTS 
                          if not host.startswith(('localhost', '127.0.0.1'))), 
                         'ombradelportico.it')
        else:
            domain = 'ombradelportico.it'
        
        # Usa HTTPS in produzione, HTTP in development
        protocol = 'https' if not getattr(settings, 'DEBUG', False) else 'http'
        base_url = f"{protocol}://{domain}"
        
        # Oggetto email
        subject = f'[Ombra del Portico] Nuovo articolo da approvare: {articolo.titolo[:50]}...'
        
        # Contenuto email HTML
        html_message = f"""
        <h2>Nuovo Articolo da Approvare</h2>
        
        <h3>Dettagli Articolo:</h3>
        <ul>
            <li><strong>Titolo:</strong> {articolo.titolo}</li>
            <li><strong>Categoria:</strong> {articolo.categoria}</li>
            <li><strong>Data creazione:</strong> {articolo.data_creazione.strftime('%d/%m/%Y alle %H:%M')}</li>
            <li><strong>ID Articolo:</strong> {articolo.id}</li>
        </ul>
        
        <h3>Contenuto:</h3>
        <div style="border-left: 3px solid #ccc; padding-left: 10px; margin: 10px 0;">
            {articolo.contenuto[:200]}{"..." if len(articolo.contenuto) > 200 else ""}
        </div>
        
        <h3>Azioni:</h3>
        <p>Per approvare l'articolo, accedi all'admin Django:</p>
        <p><a href="{base_url}/admin/home/articolo/{articolo.id}/change/" 
           style="background: #007cba; color: white; padding: 10px 15px; text-decoration: none; border-radius: 5px;">
           Approva Articolo
        </a></p>
        
        <hr>
        <p><small>Generato automaticamente dal sistema Ombra del Portico</small></p>
        """
        
        # Versione testo semplice
        plain_message = f"""
NUOVO ARTICOLO DA APPROVARE

Titolo: {articolo.titolo}
Categoria: {articolo.categoria}
Data: {articolo.data_creazione.strftime('%d/%m/%Y alle %H:%M')}
ID: {articolo.id}

Contenuto:
{articolo.contenuto[:300]}{"..." if len(articolo.contenuto) > 300 else ""}

Per approvare, vai su: {base_url}/admin/home/articolo/{articolo.id}/change/

---
Generato automaticamente dal sistema Ombra del Portico
        """
        
        # Invia email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[admin_email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Email di notifica inviata per articolo ID {articolo.id} a {admin_email}")
        return True
        
    except Exception as e:
        logger.error(f"Errore nell'invio email per articolo ID {articolo.id}: {e}")
        return False


def send_test_email():
    """
    Invia email di test per verificare la configurazione
    """
    try:
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'redazione@ombradelportico.it')
        
        send_mail(
            subject='[Test] Configurazione Email Ombra del Portico',
            message='Questo è un test per verificare che la configurazione email funzioni correttamente.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[admin_email],
            html_message='<h2>Email Test</h2><p>La configurazione email funziona correttamente!</p>',
            fail_silently=False,
        )
        
        logger.info(f"Email di test inviata con successo a {admin_email}")
        return True
        
    except Exception as e:
        logger.error(f"Errore nell'invio email di test: {e}")
        return False