from django import template
from django.utils import timezone
import locale

register = template.Library()

ITALIAN_MONTHS = {
    1: 'gennaio', 2: 'febbraio', 3: 'marzo', 4: 'aprile',
    5: 'maggio', 6: 'giugno', 7: 'luglio', 8: 'agosto',
    9: 'settembre', 10: 'ottobre', 11: 'novembre', 12: 'dicembre'
}

ITALIAN_MONTHS_SHORT = {
    1: 'gen', 2: 'feb', 3: 'mar', 4: 'apr',
    5: 'mag', 6: 'giu', 7: 'lug', 8: 'ago',
    9: 'set', 10: 'ott', 11: 'nov', 12: 'dic'
}

@register.filter
def italian_date(value, format_type='long'):
    """
    Format date in Italian
    format_type: 'long' for "8 settembre 2025", 'short' for "8 set 2025"
    """
    if not value:
        return ''
    
    if hasattr(value, 'strftime'):
        day = value.day
        month = value.month
        year = value.year
        
        if format_type == 'short':
            month_name = ITALIAN_MONTHS_SHORT[month]
        else:
            month_name = ITALIAN_MONTHS[month]
        
        return f"{day} {month_name} {year}"
    
    return value

@register.filter
def italian_datetime(value):
    """
    Format datetime in Italian with time
    """
    if not value:
        return ''
    
    if hasattr(value, 'strftime'):
        day = value.day
        month = value.month
        year = value.year
        hour = value.hour
        minute = value.minute
        
        month_name = ITALIAN_MONTHS[month]
        
        return f"{day} {month_name} {year} alle {hour:02d}:{minute:02d}"
    
    return value