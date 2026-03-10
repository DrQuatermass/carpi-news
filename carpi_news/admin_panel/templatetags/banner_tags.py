from django import template
from django.utils import timezone
from django.db import models
from admin_panel.models import Banner
import random

register = template.Library()

# Cache per gli utenti già mostrati nella pagina corrente
_shown_users = []
# Cache per i banner già mostrati nella pagina corrente (per ID)
_shown_banner_ids = []


def reset_shown_users():
    """Resetta la cache degli utenti mostrati (chiamato a inizio pagina)"""
    global _shown_users, _shown_banner_ids
    _shown_users = []
    _shown_banner_ids = []


def get_priority_weight(priority, user_already_shown=False):
    """
    Calcola il peso per la selezione randomica basato sulla priorità

    Priorità 1 (Massima): peso 5
    Priorità 2 (Alta): peso 4
    Priorità 3 (Media): peso 3
    Priorità 4 (Bassa): peso 2
    Priorità 5 (Minima): peso 1

    Se l'utente è già mostrato nella pagina, il peso viene ridotto del 75%
    """
    weight_map = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}
    weight = weight_map.get(priority, 3)

    # Penalizzazione per utenti già presenti nella pagina
    if user_already_shown:
        weight = weight * 0.25  # Riduce il peso del 75%

    return weight


def weighted_random_choice(banners):
    """
    Seleziona un banner randomicamente basandosi sui pesi di priorità
    Esclude i banner già mostrati nella stessa pagina per garantire diversità
    """
    if not banners:
        return None

    # Filtra i banner già mostrati nella pagina
    available_banners = [b for b in banners if b.id not in _shown_banner_ids]

    # Se tutti i banner sono già stati mostrati, usa tutti i banner disponibili
    # (questo può succedere se ci sono più slot che banner)
    if not available_banners:
        available_banners = banners

    # Calcola i pesi per ogni banner
    weights = []
    for banner in available_banners:
        user_already_shown = banner.user_id in _shown_users
        weight = get_priority_weight(banner.priority, user_already_shown)
        weights.append(weight)

    # Selezione pesata randomica
    selected_banner = random.choices(available_banners, weights=weights, k=1)[0]

    # Aggiungi il banner e l'utente alla cache
    if selected_banner.id not in _shown_banner_ids:
        _shown_banner_ids.append(selected_banner.id)
    if selected_banner.user_id not in _shown_users:
        _shown_users.append(selected_banner.user_id)

    return selected_banner


@register.inclusion_tag('admin_panel/banner_display.html', takes_context=True)
def show_banner(context, position):
    """
    Template tag per mostrare un banner in una specifica posizione con selezione randomica pesata

    - La priorità influenza la probabilità di selezione
    - Gli utenti già presenti nella pagina hanno peso ridotto del 75%
    - Massimizza la diversità di utenti per pagina
    - I banner orizzontali (728×90) sono intercambiabili tra header, footer, article_top, article_bottom
    - I banner verticali (300×250) sono specifici per posizione

    Uso: {% load banner_tags %}
         {% show_banner 'header' %}
    """
    try:
        # Reset della cache all'inizio di ogni richiesta
        if hasattr(context, 'request') and not hasattr(context.request, '_banner_users_reset'):
            reset_shown_users()
            context.request._banner_users_reset = True
        elif not hasattr(context, 'request'):
            # Nessuna request nel context, reset comunque
            reset_shown_users()

        base_qs = Banner.objects.filter(
            status='active',
            payment_status='completed',
            approved=True,
            start_date__lte=timezone.now(),
            end_date__gte=timezone.now(),
        ).select_related('user')

        if position == 'between_articles':
            # Slot verticale: solo banner between_articles con image_vertical
            banners = list(base_qs.filter(position='between_articles').exclude(image_vertical='').exclude(image_vertical__isnull=True))
        else:
            # Per tutti gli slot orizzontali: banner con position='header' e image caricata
            banners = list(base_qs.filter(position='header').exclude(image='').exclude(image__isnull=True))

        if not banners:
            return {
                'banner': None,
                'position': position
            }

        # Selezione randomica pesata
        banner = weighted_random_choice(banners)

        # Incrementa le impressioni
        if banner:
            banner.impressions += 1
            banner.save(update_fields=['impressions'])

        return {
            'banner': banner,
            'position': position  # Passa anche la posizione per il placeholder
        }

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Errore in show_banner per posizione '{position}': {str(e)}")
        return {
            'banner': None,
            'position': position
        }


@register.simple_tag
def get_active_banners_count():
    """Conta i banner attivi"""
    return Banner.objects.filter(
        status='active',
        payment_status='completed',
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    ).count()
