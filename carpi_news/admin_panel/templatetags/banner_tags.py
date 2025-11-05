from django import template
from django.utils import timezone
from admin_panel.models import Banner

register = template.Library()


@register.inclusion_tag('admin_panel/banner_display.html')
def show_banner(position):
    """
    Template tag per mostrare un banner in una specifica posizione

    Uso: {% load banner_tags %}
         {% show_banner 'header' %}
    """
    try:
        # Ottieni banner attivi per la posizione specificata
        banners = Banner.objects.filter(
            position=position,
            status='active',
            payment_status='completed',
            start_date__lte=timezone.now(),
            end_date__gte=timezone.now()
        ).order_by('-priority', '?')[:1]

        banner = banners.first() if banners else None

        # Incrementa le impressioni se il banner esiste
        if banner:
            banner.impressions += 1
            banner.save(update_fields=['impressions'])

        return {'banner': banner}

    except Exception:
        return {'banner': None}


@register.simple_tag
def get_active_banners_count():
    """Conta i banner attivi"""
    return Banner.objects.filter(
        status='active',
        payment_status='completed',
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    ).count()
