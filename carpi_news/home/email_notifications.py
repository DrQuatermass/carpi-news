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
        from django.utils.html import escape

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

        # Prepara fonte per HTML (escaped)
        fonte_html = ''
        if articolo.fonte:
            fonte_escaped = escape(articolo.fonte)
            fonte_display = fonte_escaped[:60] + ('...' if len(fonte_escaped) > 60 else '')
            fonte_html = f'''
                    <tr>
                        <td style="padding: 8px 0;"><strong>Fonte:</strong></td>
                        <td style="padding: 8px 0;"><a href="{fonte_escaped}" target="_blank" style="color: #007cba; word-break: break-all;">{fonte_display}</a></td>
                    </tr>'''

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
                    {fonte_html}
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


def send_pubbliredazionale_approved_notification(articolo):
    """
    Invia email al cliente quando il pubbliredazionale viene approvato
    """
    try:
        if not articolo.is_pubbliredazionale or not articolo.pubbliredazionale_user:
            logger.warning(f"Tentativo di inviare notifica approvazione per articolo non-pubbliredazionale o senza utente: {articolo.id}")
            return False

        cliente_email = articolo.pubbliredazionale_user.email
        if not cliente_email:
            logger.warning(f"Utente pubbliredazionale {articolo.pubbliredazionale_user.username} senza email")
            return False

        # URL articolo pubblicato
        protocol = 'https' if not getattr(settings, 'DEBUG', False) else 'http'
        domain = getattr(settings, 'SITE_URL', 'https://ombradelportico.it').replace('https://', '').replace('http://', '')
        article_url = f"{protocol}://{domain}/articolo/{articolo.slug}/"

        subject = f'✅ Il tuo pubbliredazionale "{articolo.nome_azienda}" è stato approvato!'

        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #27ae60; border-bottom: 2px solid #27ae60; padding-bottom: 10px;">
                🎉 Pubbliredazionale Approvato!
            </h2>

            <p>Gentile <strong>{articolo.pubbliredazionale_user.get_full_name() or articolo.pubbliredazionale_user.username}</strong>,</p>

            <p>Siamo lieti di informarti che il tuo pubbliredazionale è stato approvato ed è ora <strong>pubblicato</strong> su Ombra del Portico!</p>

            <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #27ae60; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Dettagli Pubbliredazionale:</h3>
                <p><strong>Azienda:</strong> {articolo.nome_azienda}</p>
                <p><strong>Titolo:</strong> {articolo.titolo}</p>
                <p><strong>Data pubblicazione:</strong> {articolo.data_pubblicazione.strftime('%d/%m/%Y %H:%M') if articolo.data_pubblicazione else 'Ora'}</p>
            </div>

            <p style="text-align: center; margin: 30px 0;">
                <a href="{article_url}"
                   style="background-color: #3498db; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                    📰 Visualizza il tuo articolo
                </a>
            </p>

            <p>Il tuo articolo è ora visibile a tutti i lettori di Ombra del Portico e verrà condiviso sui nostri canali social.</p>

            <p style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; color: #7f8c8d; font-size: 12px;">
                Grazie per aver scelto Ombra del Portico!<br>
                <em>La Redazione</em>
            </p>
        </div>
        """

        plain_message = f"""
🎉 Pubbliredazionale Approvato!

Gentile {articolo.pubbliredazionale_user.get_full_name() or articolo.pubbliredazionale_user.username},

Siamo lieti di informarti che il tuo pubbliredazionale è stato approvato ed è ora pubblicato su Ombra del Portico!

Dettagli Pubbliredazionale:
- Azienda: {articolo.nome_azienda}
- Titolo: {articolo.titolo}
- Data pubblicazione: {articolo.data_pubblicazione.strftime('%d/%m/%Y %H:%M') if articolo.data_pubblicazione else 'Ora'}

Visualizza il tuo articolo: {article_url}

Il tuo articolo è ora visibile a tutti i lettori di Ombra del Portico e verrà condiviso sui nostri canali social.

Grazie per aver scelto Ombra del Portico!
La Redazione
        """

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[cliente_email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"Email di approvazione pubbliredazionale inviata a {cliente_email} per articolo ID {articolo.id}")
        return True

    except Exception as e:
        logger.error(f"Errore nell'invio email approvazione pubbliredazionale ID {articolo.id}: {e}")
        return False


def send_banner_approved_notification(banner):
    """
    Invia email al cliente quando il banner viene approvato
    """
    try:
        from admin_panel.models import Banner

        if not isinstance(banner, Banner) or not banner.user:
            logger.warning(f"Tentativo di inviare notifica approvazione per banner senza utente: {banner.id if hasattr(banner, 'id') else 'unknown'}")
            return False

        cliente_email = banner.user.email
        if not cliente_email:
            logger.warning(f"Utente banner {banner.user.username} senza email")
            return False

        # URL dashboard gestionale
        protocol = 'https' if not getattr(settings, 'DEBUG', False) else 'http'
        domain = getattr(settings, 'SITE_URL', 'https://ombradelportico.it').replace('https://', '').replace('http://', '')
        dashboard_url = f"{protocol}://{domain}/gestionale/dashboard/"

        subject = f'✅ Il tuo banner "{banner.title}" è stato approvato!'

        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #27ae60; border-bottom: 2px solid #27ae60; padding-bottom: 10px;">
                🎉 Banner Approvato!
            </h2>

            <p>Gentile <strong>{banner.user.get_full_name() or banner.user.username}</strong>,</p>

            <p>Siamo lieti di informarti che il tuo banner è stato approvato ed è ora <strong>attivo</strong> su Ombra del Portico!</p>

            <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #27ae60; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Dettagli Banner:</h3>
                <p><strong>Titolo:</strong> {banner.title}</p>
                <p><strong>Posizione:</strong> {banner.get_position_display()}</p>
                <p><strong>Periodo:</strong> {banner.start_date.strftime('%d/%m/%Y')} - {banner.end_date.strftime('%d/%m/%Y')}</p>
                <p><strong>Durata:</strong> {banner.duration_days} giorni</p>
            </div>

            <p style="text-align: center; margin: 30px 0;">
                <a href="{dashboard_url}"
                   style="background-color: #3498db; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                    📊 Visualizza Dashboard
                </a>
            </p>

            <p>Il tuo banner è ora visibile nella posizione selezionata e puoi monitorare le statistiche (impression e click) dalla tua dashboard.</p>

            <p style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; color: #7f8c8d; font-size: 12px;">
                Grazie per aver scelto Ombra del Portico!<br>
                <em>La Redazione</em>
            </p>
        </div>
        """

        plain_message = f"""
🎉 Banner Approvato!

Gentile {banner.user.get_full_name() or banner.user.username},

Siamo lieti di informarti che il tuo banner è stato approvato ed è ora attivo su Ombra del Portico!

Dettagli Banner:
- Titolo: {banner.title}
- Posizione: {banner.get_position_display()}
- Periodo: {banner.start_date.strftime('%d/%m/%Y')} - {banner.end_date.strftime('%d/%m/%Y')}
- Durata: {banner.duration_days} giorni

Visualizza Dashboard: {dashboard_url}

Il tuo banner è ora visibile nella posizione selezionata e puoi monitorare le statistiche (impression e click) dalla tua dashboard.

Grazie per aver scelto Ombra del Portico!
La Redazione
        """

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[cliente_email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"Email di approvazione banner inviata a {cliente_email} per banner ID {banner.id}")
        return True

    except Exception as e:
        logger.error(f"Errore nell'invio email approvazione banner ID {banner.id if hasattr(banner, 'id') else 'unknown'}: {e}")
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