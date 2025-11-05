from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError
from django.utils import timezone
from datetime import timedelta
from .models import Banner


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
def dashboard_view(request):
    """Dashboard riservata agli utenti autenticati"""
    # Statistiche banner utente
    user_banners = Banner.objects.filter(user=request.user)
    active_banners = user_banners.filter(status='active', payment_status='completed')
    pending_banners = user_banners.filter(status='pending_payment')

    context = {
        'user': request.user,
        'total_banners': user_banners.count(),
        'active_banners': active_banners.count(),
        'pending_banners': pending_banners.count(),
        'recent_banners': user_banners[:5],
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
            duration_days = int(request.POST.get('duration_days', 1))
            priority = int(request.POST.get('priority', 1))
            image = request.FILES.get('image')

            # Validazione base
            if not all([title, link_url, alt_text, position, image]):
                messages.error(request, 'Tutti i campi sono obbligatori.')
                return render(request, 'admin_panel/banner_form.html', {
                    'positions': Banner.POSITION_CHOICES,
                })

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
                start_date=timezone.now(),
                status='pending_payment',
            )
            banner.save()

            messages.success(request, f'Banner "{title}" creato! Procedi al pagamento.')
            return redirect('admin_panel:banner_payment', banner_id=banner.id)

        except Exception as e:
            messages.error(request, f'Errore nella creazione del banner: {str(e)}')

    context = {
        'positions': Banner.POSITION_CHOICES,
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
        banner.title = request.POST.get('title', banner.title)
        banner.link_url = request.POST.get('link_url', banner.link_url)
        banner.alt_text = request.POST.get('alt_text', banner.alt_text)
        banner.position = request.POST.get('position', banner.position)
        banner.duration_days = int(request.POST.get('duration_days', banner.duration_days))
        banner.priority = int(request.POST.get('priority', banner.priority))

        if 'image' in request.FILES:
            banner.image = request.FILES['image']

        banner.save()
        messages.success(request, 'Banner aggiornato con successo!')
        return redirect('admin_panel:banner_list')

    context = {
        'banner': banner,
        'positions': Banner.POSITION_CHOICES,
        'is_edit': True,
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
    """Pagina di pagamento per il banner"""
    banner = get_object_or_404(Banner, id=banner_id, user=request.user)

    if banner.payment_status == 'completed':
        messages.info(request, 'Questo banner è già stato pagato.')
        return redirect('admin_panel:banner_list')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')

        # Simula il pagamento (in produzione integrare con Stripe/PayPal)
        banner.payment_status = 'completed'
        banner.payment_method = payment_method
        banner.payment_date = timezone.now()
        banner.payment_transaction_id = f'TXN-{timezone.now().timestamp()}'
        banner.status = 'active'
        banner.save()

        messages.success(request, f'Pagamento completato! Il tuo banner è ora attivo.')
        return redirect('admin_panel:banner_list')

    context = {
        'banner': banner,
    }
    return render(request, 'admin_panel/banner_payment.html', context)


# ===== PUBLIC BANNER VIEWS =====

def banner_click(request, banner_id):
    """Traccia i click sui banner e reindirizza"""
    banner = get_object_or_404(Banner, id=banner_id)

    # Incrementa il contatore dei click
    banner.clicks += 1
    banner.save(update_fields=['clicks'])

    # Reindirizza all'URL del banner
    return redirect(banner.link_url)
