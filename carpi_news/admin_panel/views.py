from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from datetime import timedelta
from .models import Banner


def login_view(request):
    """Vista per il login degli utenti"""
    if request.user.is_authenticated:
        return redirect('admin_panel:banner_list')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f'Benvenuto {user.username}!')
            next_url = request.GET.get('next', 'admin_panel:banner_list')
            return redirect(next_url)
        else:
            messages.error(request, 'Username o password non corretti.')

    return render(request, 'admin_panel/login.html')


def logout_view(request):
    """Vista per il logout degli utenti"""
    logout(request)
    messages.info(request, 'Logout effettuato con successo.')
    return redirect('admin_panel:login')




def register_view(request):
    """Vista per la registrazione di nuovi utenti"""
    if request.user.is_authenticated:
        return redirect('admin_panel:banner_list')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')

        # Validazione
        if not username or not password:
            messages.error(request, 'Username e password sono obbligatori.')
            return render(request, 'admin_panel/register.html')

        if password != password_confirm:
            messages.error(request, 'Le password non coincidono.')
            return render(request, 'admin_panel/register.html')

        if len(password) < 6:
            messages.error(request, 'La password deve contenere almeno 6 caratteri.')
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
            messages.success(request, f'Account creato con successo! Benvenuto {username}!')
            login(request, user)
            return redirect('admin_panel:dashboard')

        except IntegrityError:
            messages.error(request, 'Username già esistente. Scegline un altro.')

    return render(request, 'admin_panel/register.html')


# ===== BANNER VIEWS =====

@login_required(login_url='admin_panel:login')
def banner_list(request):
    """Lista dei banner dell'utente"""
    banners = Banner.objects.filter(user=request.user).order_by('-created_at')
    context = {
        'banners': banners,
    }
    return render(request, 'admin_panel/banner_list.html', context)


@login_required(login_url='admin_panel:login')
def banner_create(request):
    """Crea un nuovo banner"""
    if request.method == 'POST':
        try:
            # Raccogli i dati dal form
            title = request.POST.get('title')
            link_url = request.POST.get('link_url')
            alt_text = request.POST.get('alt_text')
            position = request.POST.get('position')
            start_date_str = request.POST.get('start_date')
            end_date_str = request.POST.get('end_date')
            priority = int(request.POST.get('priority', 1))
            image = request.FILES.get('image')

            # Validazione base
            missing_fields = []
            if not title:
                missing_fields.append('Titolo')
            if not image:
                missing_fields.append('Immagine')
            if not link_url:
                missing_fields.append('URL di destinazione')
            if not alt_text:
                missing_fields.append('Testo alternativo')
            if not position:
                missing_fields.append('Posizione')
            if not start_date_str:
                missing_fields.append('Data inizio')
            if not end_date_str:
                missing_fields.append('Data fine')

            if missing_fields:
                messages.error(request, f'Campi obbligatori mancanti: {", ".join(missing_fields)}')
                context = {
                    'positions': Banner.POSITION_CHOICES,
                    'form_data': request.POST,
                    'occupied_positions': list(Banner.objects.filter(
                        user=request.user,
                        status='active',
                        payment_status='completed'
                    ).values_list('position', flat=True)),
                }
                return render(request, 'admin_panel/banner_form.html', context)

            # Converti le date
            from datetime import datetime, date
            start_date = timezone.make_aware(datetime.strptime(start_date_str, '%Y-%m-%d'))
            end_date = timezone.make_aware(datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

            # Calcola duration_days
            duration_days = (end_date - start_date).days + 1

            # Validazione date
            if end_date < start_date:
                messages.error(request, 'La data di fine deve essere successiva o uguale alla data di inizio.')
                context = {
                    'positions': Banner.POSITION_CHOICES,
                    'form_data': request.POST,
                    'occupied_positions': list(Banner.objects.filter(
                        user=request.user,
                        status='active',
                        payment_status='completed'
                    ).values_list('position', flat=True)),
                }
                return render(request, 'admin_panel/banner_form.html', context)

            # Permetti data inizio da oggi (non prima)
            # Confronta solo le date, non l'ora
            today = date.today()
            start_date_only = start_date.date()
            if start_date_only < today:
                messages.error(request, 'La data di inizio non può essere nel passato.')
                context = {
                    'positions': Banner.POSITION_CHOICES,
                    'form_data': request.POST,
                    'occupied_positions': list(Banner.objects.filter(
                        user=request.user,
                        status='active',
                        payment_status='completed'
                    ).values_list('position', flat=True)),
                }
                return render(request, 'admin_panel/banner_form.html', context)

            # Calcola il prezzo per giorno in base alla priorità
            base_price_per_day = 1.00
            multiplier = {1: 5, 2: 3, 3: 2, 4: 1}.get(priority, 1)
            price_per_day = base_price_per_day * multiplier

            # Crea il banner
            banner = Banner(
                user=request.user,
                title=title,
                image=image,
                link_url=link_url,
                alt_text=alt_text,
                position=position,
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
                # Gestisci errori di validazione immagine
                messages.error(request, str(validation_error))
                context = {
                    'positions': Banner.POSITION_CHOICES,
                    'form_data': request.POST,
                    'occupied_positions': list(Banner.objects.filter(
                        user=request.user,
                        status='active',
                        payment_status='completed'
                    ).values_list('position', flat=True)),
                }
                return render(request, 'admin_panel/banner_form.html', context)

            # Ottieni le dimensioni consigliate per il messaggio
            recommended_size = Banner.get_recommended_size(position)
            messages.success(request, f'Banner "{title}" creato! L\'immagine è stata scalata a larghezza massima {recommended_size[0]}px mantenendo le proporzioni e convertita in WebP.')
            messages.info(request, 'Completa l\'acquisto per attivare il banner.')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

        except Exception as e:
            messages.error(request, f'Errore nella creazione del banner: {str(e)}')

    # Trova le posizioni già occupate dall'utente corrente (banner attivi)
    # Tutte le posizioni possono avere più banner (gestiti con priorità)
    # Questa lista serve solo per mostrare visivamente quali posizioni hanno già banner
    occupied_positions = list(Banner.objects.filter(
        user=request.user,
        status='active',
        payment_status='completed'
    ).values_list('position', flat=True).distinct())

    context = {
        'positions': Banner.POSITION_CHOICES,
        'occupied_positions': occupied_positions,
        'banner': None,  # Nessun banner esistente in modalità creazione
        'form_data': {},  # Nessun dato form da ripristinare
    }
    return render(request, 'admin_panel/banner_form.html', context)


@login_required(login_url='admin_panel:login')
def banner_edit(request, banner_id):
    """Modifica un banner esistente"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    # Non permettere modifiche a banner già pagati e attivi
    if banner.payment_status == 'completed' and banner.status == 'active':
        messages.warning(request, 'Non puoi modificare un banner già attivo e pagato.')
        return redirect('admin_panel:banner_list')

    if request.method == 'POST':
        from datetime import datetime

        banner.title = request.POST.get('title', banner.title)
        banner.link_url = request.POST.get('link_url', banner.link_url)
        banner.alt_text = request.POST.get('alt_text', banner.alt_text)
        banner.position = request.POST.get('position', banner.position)

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
        base_price_per_day = 1.00
        multiplier = {1: 5, 2: 3, 3: 2, 4: 1}.get(priority, 1)
        banner.price_per_day = base_price_per_day * multiplier
        banner.priority = priority

        if 'image' in request.FILES:
            banner.image = request.FILES['image']

        banner.save()
        messages.success(request, 'Banner aggiornato con successo!')
        return redirect('admin_panel:banner_list')

    # Trova le posizioni già occupate dall'utente corrente (escludi il banner in modifica)
    # Tutte le posizioni possono avere più banner (gestiti con priorità)
    # Questa lista serve solo per mostrare visivamente quali posizioni hanno già banner
    occupied_positions = list(Banner.objects.filter(
        user=request.user,
        status='active',
        payment_status='completed'
    ).exclude(id=banner.id).values_list('position', flat=True).distinct())

    context = {
        'banner': banner,
        'positions': Banner.POSITION_CHOICES,
        'is_edit': True,
        'occupied_positions': occupied_positions,
    }
    return render(request, 'admin_panel/banner_form.html', context)


@login_required(login_url='admin_panel:login')
def banner_delete(request, banner_id):
    """Elimina un banner"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    if request.method == 'POST':
        title = banner.title
        banner.delete()
        messages.success(request, f'Banner "{title}" eliminato.')
        return redirect('admin_panel:banner_list')

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
        return redirect('admin_panel:banner_list')

    if request.method == 'POST':
        print(f"[DEBUG] Payment POST request received for banner {banner.id}")

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

        # Crea ordine PayPal
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": f"BANNER-{banner.id}",
                "description": f"Banner pubblicitario: {banner.title}",
                "amount": {
                    "currency_code": "EUR",
                    "value": str(banner.total_price)
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

            # Trova l'URL di approvazione
            for link in order['links']:
                if link['rel'] == 'approve':
                    return redirect(link['href'])
        else:
            messages.error(request, f'Errore creazione ordine PayPal: {order_response.text}')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

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
        return redirect('admin_panel:banner_list')

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
        return redirect('admin_panel:banner_list')

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

        # Dopo il pagamento, il banner va in attesa di approvazione
        # Se è già approvato, attivalo direttamente
        if banner.approved:
            banner.status = 'active'
        else:
            banner.status = 'pending_approval'

        banner.save()

        messages.success(request, f'Acquisto completato con successo! Il tuo banner è ora in attesa di approvazione da parte dell\'amministratore.')
        return redirect('admin_panel:banner_list')
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
