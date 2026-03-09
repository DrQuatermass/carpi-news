from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.http import JsonResponse
from datetime import timedelta
from .models import Banner
import logging

logger = logging.getLogger(__name__)


def login_view(request):
    """Vista per il login degli utenti"""
    if request.user.is_authenticated:
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f'Benvenuto {user.username}!')
            next_url = request.GET.get('next', 'admin_panel:dashboard')
            return redirect(next_url)
        else:
            messages.error(request, 'Username o password non corretti.')

    return render(request, 'admin_panel/login.html')


def logout_view(request):
    """Vista per il logout degli utenti"""
    logout(request)
    messages.info(request, 'Logout effettuato con successo.')
    return redirect('admin_panel:login')




@login_required(login_url='admin_panel:login')
def dashboard(request):
    """Dashboard principale con lista completa di banner e pubbliredazionali"""
    from home.models import Articolo

    # Tutti i banner dell'utente
    banners = Banner.objects.filter(user=request.user).order_by('-created_at')

    # Tutti i pubbliredazionali dell'utente
    pubbliredazionali = Articolo.objects.filter(
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    ).order_by('-data_creazione')

    context = {
        'banners': banners,
        'pubbliredazionali': pubbliredazionali,
    }

    return render(request, 'admin_panel/dashboard.html', context)


def register_view(request):
    """Vista per la registrazione di nuovi utenti"""
    if request.user.is_authenticated:
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')

        # Validazione
        if not username or not password or not email or not first_name or not last_name:
            messages.error(request, 'Tutti i campi sono obbligatori.')
            return render(request, 'admin_panel/register.html')

        if password != password_confirm:
            messages.error(request, 'Le password non coincidono.')
            return render(request, 'admin_panel/register.html')

        if len(password) < 6:
            messages.error(request, 'La password deve contenere almeno 6 caratteri.')
            return render(request, 'admin_panel/register.html')

        # Verifica che l'email non sia già utilizzata
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email già utilizzata. Usa un\'altra email.')
            return render(request, 'admin_panel/register.html')

        try:
            # Crea il nuovo utente
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            messages.success(request, f'Account creato con successo! Benvenuto {first_name}!')
            login(request, user)
            return redirect('admin_panel:dashboard')

        except IntegrityError:
            messages.error(request, 'Username già esistente. Scegline un altro.')

    return render(request, 'admin_panel/register.html')


# ===== BANNER VIEWS =====

@login_required(login_url='admin_panel:login')
def banner_create(request):
    """Crea un nuovo banner"""
    if request.method == 'POST':
        try:
            # Raccogli i dati dal form
            title = request.POST.get('title')
            link_url = request.POST.get('link_url')
            alt_text = request.POST.get('alt_text')
            start_date_str = request.POST.get('start_date')
            end_date_str = request.POST.get('end_date')
            priority = int(request.POST.get('priority', 1))
            image = request.FILES.get('image')
            image_vertical = request.FILES.get('image_vertical')

            # Validazione base
            missing_fields = []
            if not title:
                missing_fields.append('Titolo')
            if not image:
                missing_fields.append('Banner orizzontale')
            if not image_vertical:
                missing_fields.append('Banner verticale')
            if not link_url:
                missing_fields.append('URL di destinazione')
            if not alt_text:
                missing_fields.append('Testo alternativo')
            if not start_date_str:
                missing_fields.append('Data inizio')
            if not end_date_str:
                missing_fields.append('Data fine')

            if missing_fields:
                messages.error(request, f'Campi obbligatori mancanti: {", ".join(missing_fields)}')
                return render(request, 'admin_panel/banner_form.html', {'form_data': request.POST})

            # Converti le date
            from datetime import datetime, date
            start_date = timezone.make_aware(datetime.strptime(start_date_str, '%Y-%m-%d'))
            end_date = timezone.make_aware(datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

            duration_days = (end_date - start_date).days + 1

            if end_date < start_date:
                messages.error(request, 'La data di fine deve essere successiva o uguale alla data di inizio.')
                return render(request, 'admin_panel/banner_form.html', {'form_data': request.POST})

            today = date.today()
            if start_date.date() < today:
                messages.error(request, 'La data di inizio non può essere nel passato.')
                return render(request, 'admin_panel/banner_form.html', {'form_data': request.POST})

            # Calcola il prezzo per giorno in base alla priorità
            if priority == 5 and not request.user.is_staff:
                priority = 4
            base_price_per_day = 1.70
            if priority == 5:
                price_per_day = 0
            else:
                price_per_day = base_price_per_day * (6 - priority)

            # Crea il banner — posizione fissa 'header' (campagna include entrambi i formati)
            banner = Banner(
                user=request.user,
                title=title,
                image=image,
                image_vertical=image_vertical,
                link_url=link_url,
                alt_text=alt_text,
                position='header',
                duration_days=duration_days,
                priority=priority,
                price_per_day=price_per_day,
                start_date=start_date,
                end_date=end_date,
                status='pending_payment',
            )

            try:
                banner.save()
            except Exception as validation_error:
                messages.error(request, str(validation_error))
                return render(request, 'admin_panel/banner_form.html', {'form_data': request.POST})

            messages.success(request, f'Campagna "{title}" creata con successo! Entrambi i banner sono stati ottimizzati in WebP.')
            messages.info(request, 'Completa l\'acquisto per attivare la campagna.')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

        except Exception as e:
            messages.error(request, f'Errore nella creazione della campagna: {str(e)}')

    context = {
        'banner': None,
        'form_data': {},
    }
    return render(request, 'admin_panel/banner_form.html', context)


@login_required(login_url='admin_panel:login')
def banner_edit(request, banner_id):
    """Modifica un banner esistente"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    # Non permettere modifiche a banner già pagati e attivi
    if banner.payment_status == 'completed' and banner.status == 'active':
        messages.warning(request, 'Non puoi modificare un banner già attivo e pagato.')
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        from datetime import datetime

        banner.title = request.POST.get('title', banner.title)
        banner.link_url = request.POST.get('link_url', banner.link_url)
        banner.alt_text = request.POST.get('alt_text', banner.alt_text)

        # Gestisci le date
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')

        if start_date_str:
            banner.start_date = timezone.make_aware(datetime.strptime(start_date_str, '%Y-%m-%d'))

        if end_date_str:
            banner.end_date = timezone.make_aware(datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

        # Ricalcola duration_days
        if banner.start_date and banner.end_date:
            banner.duration_days = (banner.end_date - banner.start_date).days + 1

        priority = int(request.POST.get('priority', banner.priority))

        # Ricalcola il prezzo per giorno in base alla priorità
        # priority 1=Massima→×5, priority 5=Minima gratuita (solo admin)
        if priority == 5 and not request.user.is_staff:
            priority = 4  # fallback a Bassa per utenti normali
        base_price_per_day = 1.70
        if priority == 5:
            banner.price_per_day = 0  # Minima è gratuita, solo admin
        else:
            multiplier = 6 - priority
            banner.price_per_day = base_price_per_day * multiplier
        banner.priority = priority

        if 'image' in request.FILES:
            banner.image = request.FILES['image']
        if 'image_vertical' in request.FILES:
            banner.image_vertical = request.FILES['image_vertical']

        banner.save()
        messages.success(request, 'Campagna banner aggiornata con successo!')
        return redirect('admin_panel:dashboard')

    context = {
        'banner': banner,
        'is_edit': True,
    }
    return render(request, 'admin_panel/banner_form.html', context)


@login_required(login_url='admin_panel:login')
def banner_toggle_status(request, banner_id):
    """Attiva o disattiva un banner"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    # Solo banner pagati possono essere attivati/disattivati
    if banner.payment_status != 'completed':
        messages.error(request, 'Solo i banner pagati possono essere attivati o disattivati.')
        return redirect('admin_panel:dashboard')

    # Solo banner approvati possono essere attivati
    if not banner.approved and banner.status != 'active':
        messages.error(request, 'Il banner deve essere approvato prima di poter essere attivato.')
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        if banner.status == 'active':
            banner.status = 'paused'
            messages.success(request, f'Banner "{banner.title}" disattivato.')
        else:
            banner.status = 'active'
            messages.success(request, f'Banner "{banner.title}" attivato.')

        banner.save()
        return redirect('admin_panel:dashboard')

    # Se GET, mostra pagina di conferma
    context = {'banner': banner}
    return render(request, 'admin_panel/banner_toggle_status.html', context)


@login_required(login_url='admin_panel:login')
def banner_delete(request, banner_id):
    """Elimina un banner"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    if request.method == 'POST':
        title = banner.title
        banner.delete()
        messages.success(request, f'Banner "{title}" eliminato.')
        return redirect('admin_panel:dashboard')

    context = {'banner': banner}
    return render(request, 'admin_panel/banner_delete.html', context)


@login_required(login_url='admin_panel:login')
def banner_payment(request, banner_id):
    """Pagina di pagamento per il banner con PayPal"""
    import requests
    import base64
    from django.conf import settings

    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    if banner.payment_status == 'completed':
        messages.info(request, 'Questo banner è già stato acquistato.')
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        # Check se è una richiesta JSON (azione save)
        if request.content_type == 'application/json':
            import json as json_lib
            from django.core.mail import send_mail

            data = json_lib.loads(request.body)
            action = data.get('action')

            if action == 'save':
                # Salva il banner e invia email all'admin
                banner.payment_status = 'saved'  # Nuovo stato: salvato senza pagamento
                banner.save()

                # Invia email all'admin
                admin_email = settings.ADMINS[0][1] if settings.ADMINS else settings.DEFAULT_FROM_EMAIL
                subject = f'Nuovo Banner da Approvare: {banner.title}'
                message = f'''Un nuovo banner è stato salvato e richiede approvazione.

Titolo: {banner.title}
Utente: {request.user.username} ({request.user.email})
Posizione: {banner.get_position_display()}
Durata: {banner.duration_days} giorni
Periodo: {banner.start_date.strftime("%d/%m/%Y")} - {banner.end_date.strftime("%d/%m/%Y")}

Link per approvare: {settings.SITE_URL}/admin/admin_panel/banner/{banner.id}/change/

Il cliente ha scelto di salvare il banner senza pagamento immediato.
'''

                try:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin_email],
                        fail_silently=False,
                    )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Errore invio email admin: {e}")

                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'Azione non valida'})

        # Altrimenti è un normale POST per pagamento PayPal
        print(f"[DEBUG] Payment POST request received for banner {banner.id}")

        # Gestisci codice promozionale se presente
        from decimal import Decimal
        from .models import PromotionalCode

        promo_code_str = request.POST.get('promo_code', '').strip()
        final_price = banner.total_price
        discount_amount = Decimal('0')
        promo_obj = None

        if promo_code_str:
            try:
                promo_obj = PromotionalCode.objects.get(code=promo_code_str)
                is_valid, msg = promo_obj.is_valid()

                if is_valid and promo_obj.can_apply_to('banner') and final_price >= promo_obj.min_amount:
                    discount_amount = promo_obj.calculate_discount(final_price)
                    final_price = final_price - discount_amount
                    print(f"[DEBUG] Codice promozionale {promo_code_str} applicato: sconto €{discount_amount}")
                else:
                    print(f"[DEBUG] Codice promozionale {promo_code_str} non valido: {msg}")
                    promo_obj = None  # Reset se non valido
            except PromotionalCode.DoesNotExist:
                print(f"[DEBUG] Codice promozionale {promo_code_str} non trovato")
                promo_obj = None

        # Se il prezzo finale è 0 (banner gratuito con sconto 100%), non serve PayPal
        if final_price == 0:
            print(f"[DEBUG] Banner {banner.id} gratuito con codice promo '{promo_code_str}'")

            # Applica il codice promo
            if promo_obj:
                banner.promo_code = promo_obj
                banner.discount_amount = discount_amount
                promo_obj.increment_uses()

            # Marca come completato senza pagamento
            banner.payment_status = 'completed'
            banner.payment_method = 'Codice Promo 100%'
            banner.payment_date = timezone.now()
            banner.payment_transaction_id = f'PROMO-FREE-{promo_code_str}'

            # Se già approvato, attivalo; altrimenti in attesa approvazione
            if banner.approved:
                banner.status = 'active'
            else:
                banner.status = 'pending_approval'

            banner.save()

            # Invia notifica all'admin
            from django.core.mail import send_mail
            admin_email = settings.ADMINS[0][1] if settings.ADMINS else settings.DEFAULT_FROM_EMAIL
            subject = f'Nuovo Banner Gratuito da Approvare: {banner.title}'
            message = f'''Un nuovo banner è stato acquisito gratuitamente con codice promo e richiede approvazione.

Titolo: {banner.title}
Utente: {request.user.username} ({request.user.email})
Posizione: {banner.get_position_display()}
Durata: {banner.duration_days} giorni
Periodo: {banner.start_date.strftime("%d/%m/%Y")} - {banner.end_date.strftime("%d/%m/%Y")}
Codice Promo: {promo_code_str} (sconto 100%)

Link per approvare: {settings.SITE_URL}/admin/admin_panel/banner/{banner.id}/change/
'''

            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [admin_email],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error(f"Errore invio email admin: {e}")

            messages.success(request, 'Banner gratuito acquisito con successo! Il tuo banner è ora in attesa di approvazione da parte dell\'amministratore.')
            return redirect('admin_panel:dashboard')

        # Verifica credenziali PayPal
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
            messages.error(request, 'Configurazione PayPal mancante. Contatta l\'amministratore.')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

        # Determina l'URL base PayPal in base alla modalità
        base_url = 'https://api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'https://api-m.paypal.com'

        # Ottieni access token
        auth = base64.b64encode(f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()).decode()
        token_response = requests.post(
            f'{base_url}/v1/oauth2/token',
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={'grant_type': 'client_credentials'}
        )

        if token_response.status_code != 200:
            messages.error(request, f'Errore autenticazione PayPal: verifica Client ID e Secret in .env')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

        access_token = token_response.json()['access_token']

        # Crea ordine PayPal con prezzo finale (dopo sconto)
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": f"BANNER-{banner.id}",
                "description": f"Banner pubblicitario: {banner.title}",
                "amount": {
                    "currency_code": "EUR",
                    "value": str(final_price)
                }
            }],
            "application_context": {
                "return_url": request.build_absolute_uri(f"/gestionale/banner/{banner.id}/payment/success/"),
                "cancel_url": request.build_absolute_uri(f"/gestionale/banner/{banner.id}/payment/cancel/"),
                "brand_name": "Ombra del Portico",
                "user_action": "PAY_NOW"
            }
        }

        order_response = requests.post(
            f'{base_url}/v2/checkout/orders',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            json=order_data
        )

        if order_response.status_code == 201:
            order = order_response.json()
            banner.payment_transaction_id = order['id']
            banner.save(update_fields=['payment_transaction_id'])

            # Salva codice promozionale in sessione per recuperarlo al ritorno
            if promo_obj:
                request.session[f'promo_banner_{banner.id}'] = {
                    'code': promo_code_str,
                    'discount': float(discount_amount)
                }

            # Trova l'URL di approvazione
            for link in order['links']:
                if link['rel'] == 'approve':
                    return redirect(link['href'])
        else:
            messages.error(request, f'Errore creazione ordine PayPal: {order_response.text}')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

    # Debug info
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Banner payment page - Banner {banner.id}:")
    logger.info(f"  - Duration: {banner.duration_days} giorni")
    logger.info(f"  - Price per day: €{banner.price_per_day}")
    logger.info(f"  - Total price: €{banner.total_price}")
    logger.info(f"  - Start: {banner.start_date}")
    logger.info(f"  - End: {banner.end_date}")

    context = {
        'banner': banner,
    }
    return render(request, 'admin_panel/banner_payment.html', context)


@login_required(login_url='admin_panel:login')
def banner_payment_success(request, banner_id):
    """Callback PayPal dopo pagamento riuscito"""
    import requests
    import base64
    from django.conf import settings

    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    token = request.GET.get('token')  # Order ID da PayPal v2

    if not token:
        messages.error(request, 'Pagamento non valido.')
        return redirect('admin_panel:dashboard')

    # Determina l'URL base PayPal
    base_url = 'https://api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'https://api-m.paypal.com'

    # Ottieni access token
    auth = base64.b64encode(f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()).decode()
    token_response = requests.post(
        f'{base_url}/v1/oauth2/token',
        headers={
            'Authorization': f'Basic {auth}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={'grant_type': 'client_credentials'}
    )

    if token_response.status_code != 200:
        messages.error(request, 'Errore autenticazione PayPal.')
        return redirect('admin_panel:dashboard')

    access_token = token_response.json()['access_token']

    # Cattura il pagamento
    capture_response = requests.post(
        f'{base_url}/v2/checkout/orders/{token}/capture',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    )

    if capture_response.status_code == 201:
        # Pagamento completato
        banner.payment_status = 'completed'
        banner.payment_method = 'PayPal'
        banner.payment_date = timezone.now()
        banner.payment_transaction_id = token

        # Recupera e applica codice promozionale dalla sessione
        from decimal import Decimal
        from .models import PromotionalCode

        promo_session_key = f'promo_banner_{banner.id}'
        promo_data = request.session.get(promo_session_key)

        if promo_data:
            try:
                promo = PromotionalCode.objects.get(code=promo_data['code'])
                banner.promo_code = promo
                banner.discount_amount = Decimal(str(promo_data['discount']))
                promo.increment_uses()  # Incrementa contatore utilizzi
                print(f"[DEBUG] Codice promozionale {promo.code} salvato e incrementato")
            except PromotionalCode.DoesNotExist:
                print(f"[DEBUG] Codice promozionale {promo_data['code']} non trovato al ritorno")
            finally:
                # Rimuovi dalla sessione
                del request.session[promo_session_key]

        # Dopo il pagamento, il banner va in attesa di approvazione
        # Se è già approvato, attivalo direttamente
        if banner.approved:
            banner.status = 'active'
        else:
            banner.status = 'pending_approval'

        banner.save()

        # Invia notifica all'admin
        from django.core.mail import send_mail
        admin_email = settings.ADMINS[0][1] if settings.ADMINS else settings.DEFAULT_FROM_EMAIL
        subject = f'Nuovo Banner Pagato da Approvare: {banner.title}'
        message = f'''Un nuovo banner è stato pagato e richiede approvazione.

Titolo: {banner.title}
Utente: {request.user.username} ({request.user.email})
Posizione: {banner.get_position_display()}
Durata: {banner.duration_days} giorni
Periodo: {banner.start_date.strftime("%d/%m/%Y")} - {banner.end_date.strftime("%d/%m/%Y")}
Prezzo pagato: €{banner.total_price}
Transazione ID: {token}

Link per approvare: {settings.SITE_URL}/admin/admin_panel/banner/{banner.id}/change/
'''

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [admin_email],
                fail_silently=False,
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Errore invio email admin: {e}")

        messages.success(request, f'Acquisto completato con successo! Il tuo banner è ora in attesa di approvazione da parte dell\'amministratore.')
        return redirect('admin_panel:dashboard')
    else:
        messages.error(request, f'Errore nell\'esecuzione dell\'acquisto.')
        return redirect('admin_panel:banner_payment', banner_id=banner.id)


@login_required(login_url='admin_panel:login')
def banner_payment_cancel(request, banner_id):
    """Callback PayPal dopo annullamento acquisto"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)
    messages.warning(request, 'Acquisto annullato. Puoi riprovare quando vuoi.')
    return redirect('admin_panel:banner_payment', banner_id=banner.id)


# ===== PUBLIC BANNER VIEWS =====

def banner_click(request, banner_id):
    """Traccia i click sui banner e reindirizza"""
    banner = get_object_or_404(Banner, id=banner_id)

    # Incrementa il contatore dei click
    banner.clicks += 1
    banner.save(update_fields=['clicks'])

    # Reindirizza all'URL del banner
    return redirect(banner.link_url)


@xframe_options_sameorigin
def banner_preview_layout(request):
    """Vista interattiva per selezionare la posizione del banner"""
    from home.models import Articolo

    # Prendi alcuni articoli per la preview
    articoli = Articolo.objects.filter(approvato=True).order_by('-data_pubblicazione')[:4]

    context = {
        'articoli': articoli,
        'is_preview_mode': True,
    }
    return render(request, 'admin_panel/banner_preview_layout.html', context)


# ===== PUBBLIREDAZIONALE VIEWS =====

@login_required(login_url='admin_panel:login')
def pubbliredazionale_create(request):
    """Form iniziale per creare un nuovo pubbliredazionale"""
    from home.models import Articolo

    if request.method == 'POST':
        nome_azienda = request.POST.get('nome_azienda', '').strip()
        sito_web = request.POST.get('sito_web', '').strip()
        intervistato_nome = request.POST.get('intervistato_nome', '').strip()
        intervistato_cognome = request.POST.get('intervistato_cognome', '').strip()
        intervistato_ruolo = request.POST.get('intervistato_ruolo', '').strip()
        promo_code = request.POST.get('promo_code', '').strip()

        # Validazione: solo nome azienda obbligatorio
        if not nome_azienda:
            messages.error(request, 'Il nome dell\'azienda è obbligatorio.')
            return render(request, 'admin_panel/pubbliredazionale_form.html', {
                'form_data': request.POST
            })

        # Crea pubbliredazionale - categoria sempre "Attualità"
        pubbliredazionale = Articolo.objects.create(
            is_pubbliredazionale=True,
            pubbliredazionale_user=request.user,
            nome_azienda=nome_azienda,
            sito_web=sito_web,  # Opzionale, può essere link Facebook
            intervistato_nome=intervistato_nome,
            intervistato_cognome=intervistato_cognome,
            intervistato_ruolo=intervistato_ruolo,
            categoria='Attualità',  # Sempre Attualità
            titolo=f'Pubbliredazionale {nome_azienda}',  # Temporaneo
            contenuto='',  # Verrà generato dall'AI
            approvato=False,
            payment_status='pending'
        )

        # Salva codice promo in sessione se presente
        if promo_code:
            request.session[f'promo_pubbliredazionale_{pubbliredazionale.id}'] = promo_code
            logger.info(f"Codice promo '{promo_code}' salvato in sessione per pubbliredazionale {pubbliredazionale.id}")

        messages.success(request, f'Pubbliredazionale per "{nome_azienda}" creato! Procediamo con l\'intervista.')
        return redirect('admin_panel:pubbliredazionale_interview', pubbliredazionale_id=pubbliredazionale.id)

    context = {
        'form_data': {}
    }
    return render(request, 'admin_panel/pubbliredazionale_form.html', context)


@login_required(login_url='admin_panel:login')
def pubbliredazionale_interview(request, pubbliredazionale_id):
    """Chat interattiva con AI agent per l'intervista"""
    from home.models import Articolo
    from home.publiredazionale_agent import PubbliredazioneAgent

    pubbliredazionale = get_object_or_404(
        Articolo,
        id=pubbliredazionale_id,
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    )

    # Se l'intervista è già completata (ha titolo e contenuto), redirect a preview
    if pubbliredazionale.titolo and pubbliredazionale.contenuto and pubbliredazionale.interview_data:
        return redirect('admin_panel:pubbliredazionale_preview', pubbliredazionale_id=pubbliredazionale.id)

    # Se POST, processa risposta utente o upload foto
    if request.method == 'POST':
        import json as json_lib
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Check se è FormData (upload foto)
            if request.POST.get('action') == 'upload_photo' and request.FILES.get('foto'):
                foto = request.FILES['foto']

                # Validazione formato immagine
                allowed_formats = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
                if foto.content_type not in allowed_formats:
                    return JsonResponse({'success': False, 'error': 'Formato immagine non valido. Usa JPG, PNG o WEBP.'})

                # Validazione dimensione (max 5MB)
                if foto.size > 5 * 1024 * 1024:
                    return JsonResponse({'success': False, 'error': 'L\'immagine è troppo grande. Dimensione massima: 5MB.'})

                # Salva immagine
                pubbliredazionale.foto_upload = foto
                pubbliredazionale.save()

                logger.info(f"Foto caricata per pubbliredazionale {pubbliredazionale_id}: {foto.name}")

                # Invia email all'admin dopo upload foto
                from django.core.mail import send_mail
                from django.contrib.auth.models import User
                try:
                    admin_emails = User.objects.filter(is_superuser=True).values_list('email', flat=True)
                    admin_emails = [email for email in admin_emails if email]

                    logger.info(f"Trovati {len(admin_emails)} admin con email configurata")

                    if admin_emails:
                        admin_url = f"{settings.SITE_URL}/admin/home/articolo/{pubbliredazionale.id}/change/"
                        subject = f'📷 Intervista completata + foto caricata: {pubbliredazionale.nome_azienda}'

                        # Formatta nome intervistato con ruolo
                        intervistato_info = f"{pubbliredazionale.intervistato_nome} {pubbliredazionale.intervistato_cognome}"
                        if pubbliredazionale.intervistato_ruolo:
                            intervistato_info += f" ({pubbliredazionale.intervistato_ruolo})"

                        message = f"""Ciao,

un nuovo pubbliredazionale ha completato l'intervista e caricato la foto.

Dettagli:
- Azienda: {pubbliredazionale.nome_azienda}
- Sito web: {pubbliredazionale.sito_web or 'N/A'}
- Utente: {pubbliredazionale.pubbliredazionale_user.username} ({pubbliredazionale.pubbliredazionale_user.email})
- Intervistato: {intervistato_info}
- Foto caricata: ✓

L'articolo sarà generato automaticamente dal sistema tra circa 107 minuti (o domani mattina se fuori orario lavorativo).

Dettagli pubbliredazionale: {admin_url}

---
Ombra del Portico - Sistema di gestione pubbliredazionali
"""

                        send_mail(
                            subject=subject,
                            message=message,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=admin_emails,
                            fail_silently=False,
                        )
                        logger.info(f"✅ Email admin inviata dopo upload foto per pubbliredazionale {pubbliredazionale_id} a {', '.join(admin_emails)}")
                    else:
                        logger.warning(f"⚠️ Nessun admin con email configurata - email NON inviata per pubbliredazionale {pubbliredazionale_id}")
                except Exception as e:
                    logger.error(f"❌ Errore invio email admin dopo upload foto: {e}", exc_info=True)

                return JsonResponse({'success': True, 'message': 'Foto caricata con successo'})

            # Altrimenti è una richiesta JSON (intervista)
            data = json_lib.loads(request.body)
            action = data.get('action')

            logger.info(f"Pubbliredazionale interview POST: action={action}, user={request.user}, pub_id={pubbliredazionale_id}")

            agent = PubbliredazioneAgent(pubbliredazionale)

            if action == 'start':
                # Inizia intervista
                result = agent.start_interview()
                logger.info(f"Start interview result: {result.get('success')}")
                return JsonResponse(result)

            elif action == 'answer':
                # Processa risposta utente
                user_answer = data.get('answer', '').strip()
                if not user_answer:
                    return JsonResponse({'success': False, 'error': 'Risposta vuota'})

                result = agent.process_user_answer(user_answer)
                return JsonResponse(result)

            else:
                return JsonResponse({'success': False, 'error': 'Azione non valida'})

        except Exception as e:
            logger.error(f"Errore pubbliredazionale_interview: {e}", exc_info=True)
            return JsonResponse({'success': False, 'error': str(e)})

    # GET: mostra interfaccia chat
    context = {
        'pubbliredazionale': pubbliredazionale,
    }
    return render(request, 'admin_panel/pubbliredazionale_interview.html', context)


@login_required(login_url='admin_panel:login')
def pubbliredazionale_preview(request, pubbliredazionale_id):
    """Anteprima articolo generato con opzioni di rigenerazione"""
    from home.models import Articolo
    from home.publiredazionale_agent import PubbliredazioneAgent

    pubbliredazionale = get_object_or_404(
        Articolo,
        id=pubbliredazionale_id,
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    )

    # Verifica che l'intervista sia completata (ha conversazione con almeno 3 domande)
    interview_data = pubbliredazionale.interview_data or {}
    conversation = interview_data.get('conversation', [])
    questions_asked = len([msg for msg in conversation if msg.get('role') == 'agent'])

    # Se l'intervista non è completata (meno di 3 domande O nessun articolo generato)
    if questions_asked < 3 or not pubbliredazionale.titolo or not pubbliredazionale.contenuto:
        messages.warning(request, 'Devi completare l\'intervista prima di vedere l\'anteprima.')
        return redirect('admin_panel:pubbliredazionale_interview', pubbliredazionale_id=pubbliredazionale.id)

    # Se POST con feedback per rigenerazione o upload foto
    if request.method == 'POST':
        import json as json_lib

        # Check se è FormData con foto (multipart/form-data)
        if request.POST.get('action') and request.FILES.get('foto'):
            action = request.POST.get('action')
            foto = request.FILES['foto']

            # Valida formato immagine
            allowed_formats = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
            if foto.content_type not in allowed_formats:
                return JsonResponse({'success': False, 'error': 'Formato immagine non valido. Usa JPG, PNG o WEBP.'})

            # Valida dimensione (max 5MB)
            if foto.size > 5 * 1024 * 1024:
                return JsonResponse({'success': False, 'error': 'L\'immagine è troppo grande. Dimensione massima: 5MB.'})

            # Salva immagine
            pubbliredazionale.foto_upload = foto
            pubbliredazionale.save()

            # Processa l'azione richiesta (save o proceed_to_payment)
            if action == 'save':
                # Salva l'articolo e invia email all'admin
                from django.core.mail import send_mail
                from django.conf import settings

                # Marca come salvato (in attesa approvazione admin)
                pubbliredazionale.payment_status = 'saved'
                pubbliredazionale.save()

                # Invia email all'admin
                admin_email = settings.ADMINS[0][1] if settings.ADMINS else settings.DEFAULT_FROM_EMAIL
                subject = f'Nuovo Pubbliredazionale da Approvare: {pubbliredazionale.nome_azienda}'
                message = f'''Un nuovo pubbliredazionale è stato salvato e richiede approvazione.

Azienda: {pubbliredazionale.nome_azienda}
Utente: {request.user.username} ({request.user.email})
Titolo: {pubbliredazionale.titolo}

Link per approvare: {settings.SITE_URL}/admin/home/articolo/{pubbliredazionale.id}/change/

Il cliente ha scelto di salvare l'articolo senza pagamento immediato.
'''

                try:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin_email],
                        fail_silently=False,
                    )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Errore invio email admin: {e}")

                return JsonResponse({'success': True, 'redirect_url': '/gestionale/'})

            elif action == 'proceed_to_payment':
                # Verifica che possa procedere
                if not pubbliredazionale.can_proceed_to_payment():
                    return JsonResponse({'success': False, 'error': 'Non puoi procedere al pagamento'})

                return JsonResponse({'success': True, 'redirect_url': f'/gestionale/pubbliredazionale/{pubbliredazionale.id}/payment/'})

            else:
                return JsonResponse({'success': False, 'error': 'Azione non valida'})

        # Check se è FormData senza foto ma con action (save/proceed_to_payment senza nuovo upload)
        elif request.POST.get('action'):
            action = request.POST.get('action')

            # Verifica che abbia già una foto caricata
            if not pubbliredazionale.foto_upload:
                return JsonResponse({'success': False, 'error': 'Devi caricare una foto prima di procedere'})

            if action == 'save':
                # Salva l'articolo e invia email all'admin
                from django.core.mail import send_mail
                from django.conf import settings

                # Marca come salvato
                pubbliredazionale.payment_status = 'saved'
                pubbliredazionale.save()

                # Invia email all'admin
                admin_email = settings.ADMINS[0][1] if settings.ADMINS else settings.DEFAULT_FROM_EMAIL
                subject = f'Nuovo Pubbliredazionale da Approvare: {pubbliredazionale.nome_azienda}'
                message = f'''Un nuovo pubbliredazionale è stato salvato e richiede approvazione.

Azienda: {pubbliredazionale.nome_azienda}
Utente: {request.user.username} ({request.user.email})
Titolo: {pubbliredazionale.titolo}

Link per approvare: {settings.SITE_URL}/admin/home/articolo/{pubbliredazionale.id}/change/

Il cliente ha scelto di salvare l'articolo senza pagamento immediato.
'''

                try:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin_email],
                        fail_silently=False,
                    )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Errore invio email admin: {e}")

                return JsonResponse({'success': True, 'redirect_url': '/gestionale/'})

            elif action == 'proceed_to_payment':
                if not pubbliredazionale.can_proceed_to_payment():
                    return JsonResponse({'success': False, 'error': 'Non puoi procedere al pagamento'})

                return JsonResponse({'success': True, 'redirect_url': f'/gestionale/pubbliredazionale/{pubbliredazionale.id}/payment/'})

        # Altrimenti è una richiesta JSON (rigenerazione)
        else:
            data = json_lib.loads(request.body)
            action = data.get('action')

            if action == 'regenerate':
                feedback = data.get('feedback', '').strip()
                if not feedback:
                    return JsonResponse({'success': False, 'error': 'Feedback vuoto'})

                agent = PubbliredazioneAgent(pubbliredazionale)
                result = agent.regenerate_article(feedback)
                return JsonResponse(result)

            else:
                return JsonResponse({'success': False, 'error': 'Azione non valida'})

    # GET: mostra anteprima
    context = {
        'pubbliredazionale': pubbliredazionale,
    }
    return render(request, 'admin_panel/pubbliredazionale_preview.html', context)


@login_required(login_url='admin_panel:login')
def pubbliredazionale_payment(request, pubbliredazionale_id):
    """Pagina di pagamento per il pubbliredazionale (€5) con PayPal"""
    import requests
    import base64
    from django.conf import settings
    from home.models import Articolo

    pubbliredazionale = get_object_or_404(
        Articolo,
        id=pubbliredazionale_id,
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    )

    # Verifica che sia pronto per il pagamento (intervista completata)
    if not (pubbliredazionale.titolo and pubbliredazionale.contenuto and pubbliredazionale.interview_data):
        messages.warning(request, 'Questo pubbliredazionale non è pronto per il pagamento.')
        return redirect('admin_panel:dashboard')

    if pubbliredazionale.payment_status == 'completed':
        messages.info(request, 'Hai già acquistato questo pubbliredazionale.')
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        # Check se è una richiesta JSON (azione save)
        if request.content_type == 'application/json':
            import json as json_lib
            from django.core.mail import send_mail
            from admin_panel.models import PromotionalCode
            from decimal import Decimal

            data = json_lib.loads(request.body)
            action = data.get('action')

            if action == 'save':
                # Gestisci codice promozionale se presente
                promo_code_str = data.get('promo_code', '').strip()
                final_price = pubbliredazionale.total_price
                discount_amount = Decimal('0')
                promo_obj = None

                if promo_code_str:
                    try:
                        promo_obj = PromotionalCode.objects.get(code=promo_code_str)
                        is_valid, message = promo_obj.is_valid()

                        if is_valid and promo_obj.can_apply_to('pubbliredazionale'):
                            discount_amount = promo_obj.calculate_discount(final_price)
                            final_price = max(Decimal('0'), final_price - discount_amount)
                            logger.info(f"Codice promo '{promo_code_str}' applicato: sconto €{discount_amount}, prezzo finale €{final_price}")

                            # Applica il codice promo
                            pubbliredazionale.promo_code = promo_obj
                            pubbliredazionale.discount_amount = discount_amount
                            promo_obj.increment_uses()
                        else:
                            logger.warning(f"Codice promo '{promo_code_str}' non valido o non applicabile: {message}")
                    except PromotionalCode.DoesNotExist:
                        logger.warning(f"Codice promo '{promo_code_str}' non trovato")

                # Salva il pubbliredazionale con stato 'saved' (o 'completed' se gratuito con promo)
                if final_price == 0 and promo_obj:
                    # Pubbliredazionale gratuito con codice promo
                    pubbliredazionale.payment_status = 'completed'
                    pubbliredazionale.payment_transaction_id = f'PROMO-FREE-{promo_code_str}'
                    pubbliredazionale.save()

                    # Invia notifica all'admin
                    pubbliredazionale.send_admin_notification()

                    return JsonResponse({'success': True, 'message': 'Pubbliredazionale gratuito attivato!'})
                else:
                    # Salvato senza pagamento
                    pubbliredazionale.payment_status = 'saved'
                    pubbliredazionale.save()

                    # Invia email all'admin
                    admin_email = settings.ADMIN_EMAIL or settings.DEFAULT_FROM_EMAIL
                    subject = f'Nuovo Pubbliredazionale da Approvare: {pubbliredazionale.nome_azienda}'
                    message = f'''Un nuovo pubbliredazionale è stato salvato e richiede approvazione.

Azienda: {pubbliredazionale.nome_azienda}
Sito Web: {pubbliredazionale.sito_web}
Categoria: {pubbliredazionale.categoria}
Utente: {request.user.username} ({request.user.email})

Titolo Articolo: {pubbliredazionale.titolo}

Link per approvare: {settings.SITE_URL}/admin/home/articolo/{pubbliredazionale.id}/change/

Il cliente ha scelto di salvare il pubbliredazionale senza pagamento immediato.
'''

                    try:
                        send_mail(
                            subject,
                            message,
                            settings.DEFAULT_FROM_EMAIL,
                            [admin_email],
                            fail_silently=False,
                        )
                    except Exception as e:
                        logger.error(f"Errore invio email admin: {e}")

                    return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'Azione non valida'})

        # Altrimenti è un normale POST per pagamento PayPal
        from admin_panel.models import PromotionalCode
        from decimal import Decimal

        # Gestisci codice promozionale se presente (dalla form o dalla sessione)
        promo_code_str = request.POST.get('promo_code', '').strip()
        if not promo_code_str:
            promo_code_str = request.session.get(f'promo_pubbliredazionale_{pubbliredazionale.id}', '').strip()
        final_price = pubbliredazionale.total_price
        discount_amount = Decimal('0')
        promo_obj = None

        if promo_code_str:
            try:
                promo_obj = PromotionalCode.objects.get(code=promo_code_str)
                is_valid, message = promo_obj.is_valid()

                if is_valid and promo_obj.can_apply_to('pubbliredazionale'):
                    discount_amount = promo_obj.calculate_discount(final_price)
                    final_price = max(Decimal('0'), final_price - discount_amount)
                    logger.info(f"Codice promo '{promo_code_str}' applicato: sconto €{discount_amount}, prezzo finale €{final_price}")
                else:
                    logger.warning(f"Codice promo '{promo_code_str}' non valido o non applicabile: {message}")
                    promo_obj = None
            except PromotionalCode.DoesNotExist:
                logger.warning(f"Codice promo '{promo_code_str}' non trovato")
                promo_obj = None

        # Se il prezzo finale è 0 (pubbliredazionale gratuito), non serve PayPal
        if final_price == 0:
            logger.info(f"Pubbliredazionale {pubbliredazionale.id} gratuito con codice promo '{promo_code_str}'")

            # Applica il codice promo
            if promo_obj:
                pubbliredazionale.promo_code = promo_obj
                pubbliredazionale.discount_amount = discount_amount
                promo_obj.increment_uses()

            # Marca come completato senza pagamento
            pubbliredazionale.payment_status = 'completed'
            pubbliredazionale.payment_transaction_id = f'PROMO-FREE-{promo_code_str}'
            pubbliredazionale.save()

            # Pulisci sessione
            if f'promo_pubbliredazionale_{pubbliredazionale.id}' in request.session:
                del request.session[f'promo_pubbliredazionale_{pubbliredazionale.id}']

            # Invia notifica all'admin
            pubbliredazionale.send_admin_notification()

            messages.success(request, 'Pubbliredazionale gratuito attivato! Il tuo articolo è ora in attesa di approvazione.')
            return redirect('admin_panel:dashboard')

        # Verifica credenziali PayPal
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
            messages.error(request, 'Configurazione PayPal mancante. Contatta l\'amministratore.')
            return redirect('admin_panel:pubbliredazionale_payment', pubbliredazionale_id=pubbliredazionale.id)

        # Determina URL base PayPal
        base_url = 'https://api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'https://api-m.paypal.com'

        # Ottieni access token
        auth = base64.b64encode(f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()).decode()
        token_response = requests.post(
            f'{base_url}/v1/oauth2/token',
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={'grant_type': 'client_credentials'}
        )

        if token_response.status_code != 200:
            messages.error(request, 'Errore autenticazione PayPal.')
            return redirect('admin_panel:pubbliredazionale_payment', pubbliredazionale_id=pubbliredazionale.id)

        access_token = token_response.json()['access_token']

        # Salva info promo in sessione per recupero dopo PayPal
        if promo_obj:
            request.session[f'promo_pubbliredazionale_payment_{pubbliredazionale.id}'] = {
                'code': promo_code_str,
                'discount': float(discount_amount)
            }

        # Crea ordine PayPal con prezzo finale (eventualmente scontato)
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": f"PUBBLIREDAZIONALE-{pubbliredazionale.id}",
                "description": f"Articolo pubbliredazionale: {pubbliredazionale.nome_azienda}",
                "amount": {
                    "currency_code": "EUR",
                    "value": str(final_price)
                }
            }],
            "application_context": {
                "return_url": request.build_absolute_uri(f"/gestionale/pubbliredazionale/{pubbliredazionale.id}/payment/success/"),
                "cancel_url": request.build_absolute_uri(f"/gestionale/pubbliredazionale/{pubbliredazionale.id}/payment/cancel/"),
                "brand_name": "Ombra del Portico",
                "user_action": "PAY_NOW"
            }
        }

        order_response = requests.post(
            f'{base_url}/v2/checkout/orders',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            json=order_data
        )

        if order_response.status_code == 201:
            order = order_response.json()
            pubbliredazionale.payment_transaction_id = order['id']
            pubbliredazionale.save(update_fields=['payment_transaction_id'])

            # Trova URL di approvazione
            for link in order['links']:
                if link['rel'] == 'approve':
                    return redirect(link['href'])
        else:
            messages.error(request, f'Errore creazione ordine PayPal.')
            return redirect('admin_panel:pubbliredazionale_payment', pubbliredazionale_id=pubbliredazionale.id)

    context = {
        'pubbliredazionale': pubbliredazionale,
    }
    return render(request, 'admin_panel/pubbliredazionale_payment.html', context)


@login_required(login_url='admin_panel:login')
def pubbliredazionale_payment_success(request, pubbliredazionale_id):
    """Callback PayPal dopo pagamento riuscito"""
    import requests
    import base64
    from django.conf import settings
    from home.models import Articolo

    pubbliredazionale = get_object_or_404(
        Articolo,
        id=pubbliredazionale_id,
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    )

    token = request.GET.get('token')

    if not token:
        messages.error(request, 'Pagamento non valido.')
        return redirect('admin_panel:dashboard')

    # Determina URL base PayPal
    base_url = 'https://api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'https://api-m.paypal.com'

    # Ottieni access token
    auth = base64.b64encode(f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()).decode()
    token_response = requests.post(
        f'{base_url}/v1/oauth2/token',
        headers={
            'Authorization': f'Basic {auth}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={'grant_type': 'client_credentials'}
    )

    if token_response.status_code != 200:
        messages.error(request, 'Errore autenticazione PayPal.')
        return redirect('admin_panel:dashboard')

    access_token = token_response.json()['access_token']

    # Cattura pagamento
    capture_response = requests.post(
        f'{base_url}/v2/checkout/orders/{token}/capture',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    )

    if capture_response.status_code == 201:
        from admin_panel.models import PromotionalCode
        from decimal import Decimal

        # Recupera e applica codice promozionale dalla sessione
        promo_session_key = f'promo_pubbliredazionale_payment_{pubbliredazionale.id}'
        promo_data = request.session.get(promo_session_key)

        if promo_data:
            try:
                promo = PromotionalCode.objects.get(code=promo_data['code'])
                pubbliredazionale.promo_code = promo
                pubbliredazionale.discount_amount = Decimal(str(promo_data['discount']))
                promo.increment_uses()
                logger.info(f"Codice promo '{promo_data['code']}' applicato a pubbliredazionale {pubbliredazionale.id}")
            except PromotionalCode.DoesNotExist:
                logger.warning(f"Codice promo '{promo_data['code']}' non trovato durante success callback")

            # Pulisci sessione
            del request.session[promo_session_key]

        # Pulisci anche la sessione iniziale del codice
        initial_promo_key = f'promo_pubbliredazionale_{pubbliredazionale.id}'
        if initial_promo_key in request.session:
            del request.session[initial_promo_key]

        # Pagamento completato - invia notifica admin
        pubbliredazionale.payment_status = 'completed'
        pubbliredazionale.payment_method = 'PayPal'
        pubbliredazionale.payment_date = timezone.now()
        pubbliredazionale.payment_transaction_id = token
        pubbliredazionale.save()

        # Invia notifica all'admin
        pubbliredazionale.send_admin_notification()

        messages.success(request, 'Acquisto completato! Il tuo articolo pubbliredazionale è ora in attesa di approvazione da parte dell\'amministratore.')
        return redirect('admin_panel:dashboard')
    else:
        messages.error(request, 'Errore nell\'esecuzione dell\'acquisto.')
        return redirect('admin_panel:pubbliredazionale_payment', pubbliredazionale_id=pubbliredazionale.id)


@login_required(login_url='admin_panel:login')
def pubbliredazionale_payment_cancel(request, pubbliredazionale_id):
    """Callback PayPal dopo annullamento acquisto"""
    from home.models import Articolo

    pubbliredazionale = get_object_or_404(
        Articolo,
        id=pubbliredazionale_id,
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    )
    messages.warning(request, 'Acquisto annullato. Puoi riprovare quando vuoi.')
    return redirect('admin_panel:pubbliredazionale_payment', pubbliredazionale_id=pubbliredazionale.id)


@login_required(login_url='admin_panel:login')
def pubbliredazionale_delete(request, pubbliredazionale_id):
    """Elimina un pubbliredazionale"""
    from home.models import Articolo

    pubbliredazionale = get_object_or_404(
        Articolo,
        id=pubbliredazionale_id,
        is_pubbliredazionale=True,
        pubbliredazionale_user=request.user
    )

    # Non permettere eliminazione se già pagato/pubblicato
    if pubbliredazionale.payment_status == 'completed':
        messages.error(request, 'Non puoi eliminare un pubbliredazionale già pagato.')
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        nome_azienda = pubbliredazionale.nome_azienda
        pubbliredazionale.delete()
        messages.success(request, f'Pubbliredazionale "{nome_azienda}" eliminato.')
        return redirect('admin_panel:dashboard')

    context = {'pubbliredazionale': pubbliredazionale}
    return render(request, 'admin_panel/pubbliredazionale_delete.html', context)


# ===== API CODICI PROMOZIONALI =====

@login_required(login_url='admin_panel:login')
def validate_promo_code(request):
    """API per validare codici promozionali"""
    if request.method != 'POST':
        return JsonResponse({'valid': False, 'message': 'Metodo non consentito'})

    import json as json_lib
    from decimal import Decimal
    from .models import PromotionalCode

    try:
        data = json_lib.loads(request.body)
        code = data.get('code', '').strip()
        item_type = data.get('item_type')  # 'banner' o 'pubbliredazionale'
        original_price = Decimal(str(data.get('original_price', 0)))

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Validazione codice promo: {code} per {item_type}, prezzo: €{original_price}")

        if not code:
            return JsonResponse({'valid': False, 'message': 'Codice mancante'})

        # Cerca il codice (case-sensitive)
        try:
            promo = PromotionalCode.objects.get(code=code)
            logger.info(f"Codice trovato: {promo.code} - Attivo: {promo.is_active}")
        except PromotionalCode.DoesNotExist:
            logger.warning(f"Codice non trovato: {code}")
            return JsonResponse({'valid': False, 'message': 'Codice non valido'})

        # Verifica validità
        is_valid, message = promo.is_valid()
        logger.info(f"is_valid(): {is_valid}, message: {message}")
        if not is_valid:
            return JsonResponse({'valid': False, 'message': message})

        # Verifica che si applichi al tipo di item
        if not promo.can_apply_to(item_type):
            applies_to_text = promo.get_applies_to_display()
            return JsonResponse({
                'valid': False,
                'message': f'Questo codice è valido solo per {applies_to_text}'
            })

        # Verifica importo minimo
        if original_price < promo.min_amount:
            return JsonResponse({
                'valid': False,
                'message': f'Importo minimo richiesto: €{promo.min_amount}'
            })

        # Calcola lo sconto
        discount = promo.calculate_discount(original_price)

        return JsonResponse({
            'valid': True,
            'code': code,
            'discount_amount': float(discount),
            'description': promo.get_discount_display(),
            'message': 'Codice applicato con successo!'
        })

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Errore validate_promo_code: {e}", exc_info=True)
        return JsonResponse({'valid': False, 'message': 'Errore interno'})
