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
        <div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
            <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                Nuovo Articolo da Approvare
            </h2>

            <div style="background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #495057;">📰 {articolo.titolo}</h3>

                <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                    <tr>
                        <td style="padding: 8px 0;"><strong>Categoria:</strong></td>
                        <td style="padding: 8px 0;">{articolo.categoria}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>Data creazione:</strong></td>
                        <td style="padding: 8px 0;">{articolo.data_creazione.strftime('%d/%m/%Y alle %H:%M')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>ID Articolo:</strong></td>
                        <td style="padding: 8px 0;">{articolo.id}</td>
                    </tr>
                    {'<tr><td style="padding: 8px 0;"><strong>Fonte:</strong></td><td style="padding: 8px 0;"><a href="' + articolo.fonte + '" target="_blank">' + articolo.fonte[:60] + ('...' if len(articolo.fonte) > 60 else '') + '</a></td></tr>' if articolo.fonte else ''}
                </table>

                <div style="margin: 20px 0;">
                    <strong style="color: #495057;">Sommario:</strong>
                    <p style="color: #6c757d; line-height: 1.6; margin: 10px 0;">
                        {articolo.sommario if articolo.sommario else articolo.contenuto[:300] + '...'}
                    </p>
                </div>

                <div style="margin: 20px 0;">
                    <strong style="color: #495057;">Contenuto completo:</strong>
                    <div style="border-left: 3px solid #3498db; padding-left: 15px; margin: 10px 0; color: #495057; line-height: 1.6; max-height: 400px; overflow-y: auto;">
                        {articolo.contenuto}
                    </div>
                </div>
            </div>

            <div style="text-align: center; margin: 30px 0;">
                <a href="{base_url}/admin/home/articolo/{articolo.id}/change/"
                   style="display: inline-block; background: #28a745; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                   ✓ Approva Articolo
                </a>
                <p style="margin-top: 10px; color: #6c757d; font-size: 14px;">
                    oppure apri: <a href="{base_url}/admin/home/articolo/{articolo.id}/change/" style="color: #007cba;">{base_url}/admin/home/articolo/{articolo.id}/change/</a>
                </p>
            </div>

            <hr style="border: none; border-top: 1px solid #dee2e6; margin: 20px 0;">
            <p style="text-align: center; color: #6c757d; font-size: 12px;">
                Generato automaticamente dal sistema Ombra del Portico
            </p>
        </div>
        """
        
        # Versione testo semplice
        plain_message = f"""
NUOVO ARTICOLO DA APPROVARE

Titolo: {articolo.titolo}
Categoria: {articolo.categoria}
Data: {articolo.data_creazione.strftime('%d/%m/%Y alle %H:%M')}
ID: {articolo.id}
{"Fonte: " + articolo.fonte if articolo.fonte else ""}

Sommario:
{articolo.sommario if articolo.sommario else articolo.contenuto[:300] + '...'}

Contenuto completo:
{articolo.contenuto}

========================================
APPROVA ARTICOLO:
{base_url}/admin/home/articolo/{articolo.id}/change/
========================================

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
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'readazione@ombradelportico.it')
        
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