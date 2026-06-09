"""
Context processors per template tags globali
"""

from django.conf import settings


def get_categorie_menu(rubriche_at_end=False):
    from django.core.cache import cache

    cache_key = 'categorie_menu_rubriche_end' if rubriche_at_end else 'categorie_menu'
    categorie = cache.get(cache_key)
    if categorie is None:
        from .views import get_published_articles_query

        raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
        categorie = []
        has_rubriche = False
        for cat in sorted(raw):
            if cat in ['Editoriale', "L'Eco del Consiglio"]:
                if rubriche_at_end:
                    has_rubriche = True
                elif not has_rubriche:
                    categorie.append('Rubriche')
                    has_rubriche = True
            else:
                categorie.append(cat)
        if rubriche_at_end and has_rubriche:
            categorie.append('Rubriche')
        cache.set(cache_key, categorie, 3600)

    return categorie


def categorie_menu(request):
    if getattr(request, '_skip_categories_menu', False):
        return {'categorie_disponibili': []}

    categorie = get_categorie_menu()
    return {'categorie_disponibili': categorie}


def canonical_url(request):
    """
    Aggiunge URL canonico e costanti SEO al context di tutti i template
    """
    # Dominio canonico
    canonical_domain = 'ombradelportico.it'

    # Path pulito (sempre senza query params)
    path = request.path

    # URL canonico standard (senza query params, anche per filtri categoria)
    return {
        'canonical_url': f"https://{canonical_domain}{path}",
        'FACEBOOK_PAGE_URL': settings.FACEBOOK_PAGE_URL,
        'FACEBOOK_APP_ID': getattr(settings, 'FACEBOOK_APP_ID', ''),
        'TWITTER_SITE': settings.TWITTER_SITE,
    }
