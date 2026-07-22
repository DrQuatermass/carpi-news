import logging
import json
import os
import random
import re
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.core.cache import cache
from django.http import Http404, JsonResponse, HttpResponse, HttpResponsePermanentRedirect
from django.template import loader
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.views.decorators.http import require_http_methods, require_POST
from django.db import models
from django.db.models import F, FloatField, ExpressionWrapper, Max
from datetime import datetime, timedelta
from .models import Articolo, ArticoloRedirect, ChatbotConversation, NewsletterSubscriber, NewsletterLog
from .chatbot_service import ChatbotService
from .utils import canonical_article_url
import time
import uuid


logger = logging.getLogger(__name__)


CINEMA_FRESH_CACHE_KEY = 'programmazione_cinema:fresh'
CINEMA_STALE_CACHE_KEY = 'programmazione_cinema:stale'
CINEMA_FRESH_TTL = 21600
CINEMA_STALE_TTL = 7 * 24 * 60 * 60


def _build_cinema_schema(cinema_data):
    schema_graph = []
    for cinema in cinema_data:
        for film in cinema.get('films', []):
            schema_graph.append({
                "@type": "ScreeningEvent",
                "name": film.get('title', ''),
                "location": {
                    "@type": "MovieTheater",
                    "name": cinema.get('name', ''),
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": cinema.get('address', ''),
                        "addressLocality": "Carpi",
                        "addressRegion": "MO",
                        "addressCountry": "IT"
                    },
                    "url": cinema.get('website', '')
                },
                "workPresented": {
                    "@type": "Movie",
                    "name": film.get('title', ''),
                    **({"image": film["image"]} if film.get("image") else {})
                },
                "url": "https://ombradelportico.it/cinema/",
                "eventStatus": "https://schema.org/EventScheduled",
                "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                "organizer": {
                    "@type": "Organization",
                    "name": cinema.get('name', ''),
                    "url": cinema.get('website', '')
                }
            })
    return json.dumps({
        "@context": "https://schema.org",
        "@graph": schema_graph
    }, ensure_ascii=False).replace('</', '<\\/') if schema_graph else ''


def _scrape_cinema_parallel(stale_by_name=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .cinema_scraping import (
        cinema_payload,
        scrape_ariston,
        scrape_corso,
        scrape_eden,
        scrape_spacecity,
    )

    scrapers = [
        ('Space City Multisala', scrape_spacecity, cinema_payload('Space City Multisala', "Viale dell'Industria 9, Carpi", 'https://www.spacecity.it/')),
        ('Cinema Eden', scrape_eden, cinema_payload('Cinema Eden', 'Via Santa Chiara 22, Carpi', 'https://www.cinemaedencarpi.it/')),
        ('Cinema Ariston', scrape_ariston, cinema_payload('Cinema Ariston', 'Via Ernesto Boccaletti 3, San Marino di Carpi', 'https://www.aristoncinemacarpi.it/')),
        ('Cinema Corso', scrape_corso, cinema_payload('Cinema Corso', 'Corso M. Fanti 91, Carpi', 'https://www.cinemacorsocarpi.it/')),
    ]
    stale_by_name = stale_by_name or {}
    results = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(scraper): (name, empty_payload) for name, scraper, empty_payload in scrapers}
        for future in as_completed(future_map):
            name, empty_payload = future_map[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.error("Errore scraping %s: %s", name, exc)
                results[name] = stale_by_name.get(name, empty_payload)

    return [results.get(name, stale_by_name.get(name, empty_payload)) for name, _, empty_payload in scrapers]


def _get_cinema_data():
    fresh = cache.get(CINEMA_FRESH_CACHE_KEY)
    if fresh is not None:
        return fresh

    stale = cache.get(CINEMA_STALE_CACHE_KEY) or []
    stale_by_name = {cinema.get('name'): cinema for cinema in stale}
    cinema_data = _scrape_cinema_parallel(stale_by_name=stale_by_name)
    cache.set(CINEMA_FRESH_CACHE_KEY, cinema_data, CINEMA_FRESH_TTL)
    cache.set(CINEMA_STALE_CACHE_KEY, cinema_data, CINEMA_STALE_TTL)
    return cinema_data


CATEGORIA_MAP = {
    'attualita': 'Attualit\u00e0',
    'cronaca': 'Cronaca',
    'sport': 'Sport',
    'cultura-eventi': 'Cultura & Eventi',
    'politica': 'Politica',
    'rubriche': 'Rubriche',
    'cosa-fare-oggi': 'Cosa fare oggi',
    'editoriale': 'Editoriale',
    'eco-del-consiglio': "L'Eco del Consiglio",
}


def get_published_articles_query():
    """
    Restituisce una query per articoli pubblicabili.
    - Articoli normali: approvato=True
    - Pubbliredazionali: approvato=True AND payment_status='completed'
    """
    from django.db.models import Q
    return Articolo.objects.filter(
        Q(is_pubbliredazionale=False, approvato=True) |  # Articoli normali approvati
        Q(is_pubbliredazionale=True, approvato=True, payment_status='completed')  # Pubbliredazionali approvati E pagati
    )


def custom_404(request, exception):
    request._skip_categories_menu = True
    articoli = cache.get('error404_articoli')
    if articoli is None:
        articoli = list(
            get_published_articles_query()
            .filter(data_pubblicazione__lte=timezone.now())
            .order_by('-data_pubblicazione')
            .values('titolo', 'slug')[:6]
        )
        cache.set('error404_articoli', articoli, 3600)
    return render(request, '404.html', {'articoli_recenti': articoli}, status=404)


# Create your views here.
@cache_page(300)
@vary_on_headers('X-Requested-With')
def home(request):
    # Filtro per categoria (opzionale)
    categoria = getattr(request, '_categoria_nome', None) or request.GET.get('categoria', None)
    categoria_slug = getattr(request, '_categoria_slug', None)

    # Query base: solo articoli pubblicabili (approvati e, se pubbliredazionali, pagati) e pubblicati (non futuri)
    articoli_query = get_published_articles_query().filter(
        data_pubblicazione__lte=timezone.now()
    ).only(
        'id', 'titolo', 'sommario', 'categoria', 'slug', 'foto', 'foto_upload', 'data_pubblicazione', 'spotlight'
    )

    # Applica filtro categoria se specificato
    if categoria and categoria != 'tutti':
        if categoria.lower() == 'rubriche':
            # Filtra per Editoriale e L'Eco del Consiglio
            articoli_query = articoli_query.filter(categoria__in=['Editoriale', "L'Eco del Consiglio"])
        else:
            articoli_query = articoli_query.filter(categoria__iexact=categoria)

    # ARTICOLI SPOTLIGHT: massimo 4 articoli in evidenza (SOLO in homepage senza filtri)
    if not categoria or categoria == 'tutti':
        articoli_spotlight = articoli_query.filter(spotlight=True).order_by('-data_pubblicazione')[:4]
        # ARTICOLI NORMALI: escludi i 4 spotlight mostrati, includi eventuali spotlight in eccesso
        spotlight_ids = [a.id for a in articoli_spotlight]
        articoli_list = articoli_query.exclude(id__in=spotlight_ids).order_by('-data_pubblicazione')
    else:
        # Con filtro categoria: nessuno spotlight, mostra tutti come card normali
        articoli_spotlight = []
        articoli_list = articoli_query.order_by('-data_pubblicazione')

    # Paginazione: 8 articoli per pagina (4 righe x 3 colonne = 12 slot, 8 articoli + 4 banner)
    paginator = Paginator(articoli_list, 8)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it').rstrip('/')
    canonical_path = f"/categoria/{categoria_slug}/" if categoria_slug else "/"
    if page_obj.number > 1:
        canonical_url = f"{site_url}{canonical_path}?page={page_obj.number}"
    else:
        canonical_url = f"{site_url}{canonical_path}"

    # LOGICA BANNER: 1 banner per riga, mai in posizione 0 o 11, mai adiacenti
    # Riga 1 (0,1,2): banner in 1 o 2
    # Riga 2 (3,4,5): banner in 3, 4 o 5
    # Riga 3 (6,7,8): banner in 6, 7 o 8
    # Riga 4 (9,10,11): banner in 9 o 10
    from admin_panel.models import Banner
    from admin_panel.templatetags.banner_tags import weighted_random_choice, reset_shown_users

    # Reset cache utenti mostrati per questa pagina
    reset_shown_users()

    # Genera posizioni random per ogni riga, evitando adiacenze tra righe
    def get_banner_positions():
        row1_options = [1, 2]
        row2_options = [3, 4, 5]
        row3_options = [6, 7, 8]
        row4_options = [9, 10]

        pos1 = random.choice(row1_options)
        # Riga 2: evita adiacenza con riga 1 (pos1+1 se pos1=2 -> evita 3)
        row2_valid = [p for p in row2_options if p != pos1 + 1]
        pos2 = random.choice(row2_valid) if row2_valid else random.choice(row2_options)
        # Riga 3: evita adiacenza con riga 2
        row3_valid = [p for p in row3_options if p != pos2 + 1]
        pos3 = random.choice(row3_valid) if row3_valid else random.choice(row3_options)
        # Riga 4: evita adiacenza con riga 3
        row4_valid = [p for p in row4_options if p != pos3 + 1]
        pos4 = random.choice(row4_valid) if row4_valid else random.choice(row4_options)

        return [pos1, pos2, pos3, pos4]

    banner_positions = get_banner_positions()

    # Banner verticali per la griglia homepage: position 'between_articles' o 'both' con image_vertical
    _now = timezone.now()
    all_banners_qs = Banner.objects.filter(
        position__in=['between_articles', 'both'],
        status='active',
        payment_status='completed',
        approved=True,
        start_date__lte=_now,
        end_date__gte=_now,
    ).exclude(image_vertical='').exclude(image_vertical__isnull=True).select_related('user')
    # image_vertical_width/height sono proprietà calcolate dal file, non colonne DB.
    # Materializza una sola volta e applica lo stesso filtro di rapporto.
    all_banners = [
        b for b in all_banners_qs
        if b.image_vertical_height > 0 and b.image_vertical_width / b.image_vertical_height <= 2
    ]

    # Selezione randomica pesata di 4 banner (uno per riga). Le impression sono contate dal beacon JS.
    active_banners = []
    if all_banners:
        for slot_num in range(4):
            banner = weighted_random_choice(all_banners)
            if banner:
                active_banners.append(banner)

    # Log per debugging
    if categoria:
        logger.info(f"Caricati {len(page_obj)} articoli approvati categoria '{categoria}' (pagina {page_number})")
    else:
        logger.info(f"Caricati {len(page_obj)} articoli approvati per la home (pagina {page_number})")
    # Crea la griglia mescolando articoli e banner/placeholder
    # 12 posizioni totali: 8 articoli + 4 banner (1 per riga)
    grid_items = []
    article_index = 0
    banner_index = 0
    first_article_added = False

    for i in range(12):  # 12 posizioni totali (0-11)
        if i in banner_positions:
            # Slot banner: mostra banner attivo o placeholder
            banner_data = active_banners[banner_index] if banner_index < len(active_banners) else None
            grid_items.append({
                'type': 'banner',
                'banner': banner_data,  # None = placeholder, oggetto Banner = banner attivo
                'slot_index': banner_index
            })
            banner_index += 1
        else:
            # Slot articolo
            if article_index < len(page_obj):
                is_first = not first_article_added
                grid_items.append({
                    'type': 'article',
                    'data': page_obj[article_index],
                    'is_first_article': is_first  # Flag per LCP optimization
                })
                if is_first:
                    first_article_added = True
                article_index += 1

    # Spotlight principale: immagine per preload LCP (elemento piÃ¹ grande above-the-fold)
    first_spotlight_image = articoli_spotlight[0].get_image_url() if articoli_spotlight else None

    # Trova la prima immagine articolo per preload LCP (fallback se no spotlight)
    first_article_image = None
    for item in grid_items:
        if item['type'] == 'article':
            first_article_image = item['data'].get_image_url()
            break

    # Trova il primo banner per preload (se in posizione 0-2)
    first_banner_image = None
    for i, item in enumerate(grid_items[:3]):  # Solo primi 3 slot
        if item['type'] == 'banner' and item.get('banner') and item['banner'].image_vertical:
            first_banner_image = item['banner'].image_vertical.url
            break

    # Ottieni banner orizzontale dalla tabella Banner (posizione 'horizontal')
    from admin_panel.models import Banner
    banner_orizzontale = Banner.objects.filter(
        position='horizontal',
        status='active',
        payment_status='completed',
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    ).first()

    context = {
        'articoli': page_obj,
        'articoli_spotlight': articoli_spotlight,  # 4 articoli in evidenza
        'banner_orizzontale': banner_orizzontale,  # Banner orizzontale dopo spotlight
        'grid_items': grid_items,  # Griglia con articoli e banner/placeholder
        'first_spotlight_image': first_spotlight_image,  # Per preload LCP spotlight (LCP principale)
        'first_article_image': first_article_image,  # Per preload LCP (fallback)
        'first_banner_image': first_banner_image,  # Per preload banner
        'current_page': page_obj.number,
        'total_pages': paginator.num_pages,
        'has_prev': page_obj.has_previous(),
        'has_next': page_obj.has_next(),
        'categoria_attiva': categoria,
        'current_year': timezone.now().year,
        'canonical_url': canonical_url,
        'banner_positions': banner_positions,
        'active_banners_count': len(active_banners),
    }
    
    # Se Ã¨ una richiesta AJAX, restituisci solo i dati JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Mesi italiani abbreviati
        ITALIAN_MONTHS_SHORT = {
            1: 'gen', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'mag', 6: 'giu', 7: 'lug', 8: 'ago',
            9: 'set', 10: 'ott', 11: 'nov', 12: 'dic'
        }

        from home.templatetags.webp_images import image_srcset

        articoli_data = []
        for articolo in page_obj:
            # Formatta data in italiano
            data_pub = articolo.data_pubblicazione
            data_italiana = f"{data_pub.day} {ITALIAN_MONTHS_SHORT[data_pub.month]} {data_pub.year}"

            image_url = articolo.get_image_url()
            articoli_data.append({
                'titolo': articolo.titolo,
                'sommario': articolo.sommario,
                'categoria': articolo.categoria,
                'data_pubblicazione': data_italiana,
                'slug': articolo.slug,
                'foto': image_url,
                'foto_srcset': image_srcset(image_url),
            })

        # Prepara dati banner attivi per JSON
        banners_data = []
        for i, banner in enumerate(active_banners):
            if banner:
                banner_img_url = banner.image_vertical.url
                banners_data.append({
                    'id': banner.id,
                    'image_url': banner_img_url,
                    'image_srcset': image_srcset(banner_img_url),
                    'alt_text': banner.alt_text,
                    'image_width': banner.image_vertical_width,
                    'image_height': banner.image_vertical_height,
                    'position_index': i  # Indice nello slot (0-3)
                })

        return JsonResponse({
            'articoli': articoli_data,
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_prev': page_obj.has_previous(),
            'has_next': page_obj.has_next(),
            'categoria_attiva': categoria,
            'banner_positions': banner_positions,
            'num_banner_slots': len(banner_positions),
            'active_banners': banners_data,  # Banner attivi con dati
        })
    
    return render(request, "homepage.html", context)


@cache_page(300)
@vary_on_headers('X-Requested-With')
def categoria_articoli(request, categoria_slug):
    categoria = CATEGORIA_MAP.get(categoria_slug)
    if not categoria:
        raise Http404("Categoria non trovata")
    request._categoria_slug = categoria_slug
    request._categoria_nome = categoria
    return home(request)

@vary_on_headers('Accept-Encoding')
def dettaglio_articolo(request, slug):
    try:
        redirect_obj = ArticoloRedirect.objects.select_related('articolo').get(
            old_slug=slug
        )
        return HttpResponsePermanentRedirect(
            f"/articolo/{redirect_obj.new_slug}/"
        )
    except ArticoloRedirect.DoesNotExist:
        pass

    # Recupera articolo pubblicabile (approvato e, se pubbliredazionale, pagato)
    from django.db.models import Q
    publishable_filter = (
        Q(is_pubbliredazionale=False, approvato=True) |
        Q(is_pubbliredazionale=True, approvato=True, payment_status='completed')
    )
    cache_key = f"articolo_ctx_{slug}"
    cached_ctx = cache.get(cache_key)

    if cached_ctx:
        articolo = cached_ctx['articolo']
        # Non cachiamo la decisione di pubblicabilita': la rivalidiamo sempre,
        # cosi' un pubbliredazionale cambiato di stato non resta servito.
        if not Articolo.objects.filter(publishable_filter, pk=articolo.pk).exists():
            cache.delete(cache_key)
            raise Http404("Articolo non disponibile")
        articoli_correlati = cached_ctx['articoli_correlati']
    else:
        articolo = get_object_or_404(
            Articolo.objects.filter(publishable_filter),
            slug=slug
        )
        # Articoli correlati: ultimi 6 della stessa categoria (escluso quello corrente, solo pubblicati)
        articoli_correlati = list(Articolo.objects.filter(
            approvato=True,
            data_pubblicazione__lte=timezone.now(),
            categoria=articolo.categoria
        ).exclude(pk=articolo.pk).only(
            'id', 'titolo', 'slug', 'foto', 'foto_upload', 'foto_valida',
            'image_16x9', 'image_4x3', 'image_1x1', 'categoria',
            'data_pubblicazione', 'sommario'
        ).order_by('-data_pubblicazione')[:6])

        cache.set(cache_key, {
            'articolo': articolo,
            'articoli_correlati': articoli_correlati,
        }, 600)

    # Incrementa il contatore delle views solo se non visto in questa sessione
    session_key = f'viewed_article_{articolo.pk}'
    if not request.session.get(session_key, False):
        from django.db.models import F

        # Verifica che non sia un bot noto
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'wget', 'python-requests']
        is_bot = any(keyword in user_agent for keyword in bot_keywords)

        if not is_bot:
            Articolo.objects.filter(pk=articolo.pk).update(views=F('views') + 1)
            # Segna come visto in questa sessione (scade con la sessione)
            request.session[session_key] = True
            articolo.views = (articolo.views or 0) + 1
            logger.info(f"Visualizzazione unica articolo: {articolo.titolo} (views: {articolo.views})")
        else:
            logger.debug(f"Bot rilevato, view non contata: {articolo.titolo} (UA: {user_agent[:100]})")
    else:
        logger.debug(f"Articolo giÃ  visto in questa sessione: {articolo.titolo}")

    canonical_url = canonical_article_url(articolo)

    context = {
        'articolo': articolo,
        'articoli_correlati': articoli_correlati,
        'categoria_attiva': None,  # Nessuna categoria attiva nel dettaglio
        'current_year': timezone.now().year,
        'canonical_url': canonical_url,
        'share_url': canonical_url,
    }
    
    return render(request, "dettaglio_articolo.html", context)


def privacy_policy(request):
    """Vista per la pagina della Privacy Policy"""
    context = {
        'current_year': timezone.now().year,
    }
    
    return render(request, "privacy_policy.html", context)

def sitemap_index(request):
    """Vista per il sitemap index"""
    now = timezone.now()

    # Controlla se ci sono articoli in archivio (piÃ¹ vecchi di 30 giorni)
    archive_cutoff = now - timedelta(days=30)
    has_archive = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__lt=archive_cutoff
    ).exists()

    # Data ultimo aggiornamento archivio
    archive_lastmod = None
    if has_archive:
        latest_archive = Articolo.objects.filter(
            approvato=True,
            data_pubblicazione__lt=archive_cutoff
        ).order_by('-data_pubblicazione').first()
        if latest_archive:
            archive_lastmod = latest_archive.data_pubblicazione

    # Data ultimo aggiornamento sitemap principale (ultimi 30 giorni)
    main_lastmod = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=archive_cutoff,
        data_pubblicazione__lte=now
    ).aggregate(max_date=models.Max('data_pubblicazione'))['max_date'] or now

    # Data ultimo aggiornamento sitemap news (ultime 72 ore)
    news_cutoff = now - timedelta(hours=72)
    news_lastmod = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=news_cutoff,
        data_pubblicazione__lte=now
    ).exclude(
        titolo__istartswith='test'
    ).exclude(
        categoria='Cosa fare oggi'
    ).aggregate(max_date=models.Max('data_pubblicazione'))['max_date'] or now

    template = loader.get_template('sitemap_index.xml')
    context = {
        'main_lastmod': main_lastmod,
        'news_lastmod': news_lastmod,
        'has_archive': has_archive,
        'archive_lastmod': archive_lastmod
    }
    return HttpResponse(template.render(context, request), content_type='application/xml')

def sitemap(request):
    """Vista per la sitemap principale (ultimi 30 giorni)"""
    now = timezone.now()
    cutoff_date = now - timedelta(days=30)

    # Articoli ultimi 30 giorni (solo pubblicati, non futuri)
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_date,
        data_pubblicazione__lte=now
    ).order_by('-data_pubblicazione')

    # Aggiungi campo days_old per prioritÃ  dinamiche
    for article in articles:
        article.days_old = (now - article.data_pubblicazione).days

    # Data ultimo aggiornamento
    last_update = articles.first().data_pubblicazione if articles else now

    logger.info(f"Generata sitemap principale con {len(articles)} articoli (ultimi 30 giorni)")

    template = loader.get_template('sitemap.xml')
    context = {
        'articles': articles,
        'last_update': last_update,
        'categoria_slugs': list(CATEGORIA_MAP.keys()),
    }
    return HttpResponse(template.render(context, request), content_type='application/xml')

def sitemap_archive(request):
    """Vista per la sitemap archivio (articoli piÃ¹ vecchi di 30 giorni)"""
    cutoff_date = timezone.now() - timedelta(days=30)

    # Articoli piÃ¹ vecchi di 30 giorni, limitati a 10.000 per performance
    # Usa only() per caricare solo i campi necessari e ridurre memoria
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__lt=cutoff_date
    ).only('slug', 'data_pubblicazione').order_by('-data_pubblicazione')[:10000]

    logger.info(f"Generata sitemap archivio con {articles.count()} articoli")

    template = loader.get_template('sitemap_archive.xml')
    context = {'articles': articles}
    return HttpResponse(template.render(context, request), content_type='application/xml')

def news_sitemap(request):
    """Vista per la sitemap Google News (ultime 72 ore)"""
    now = timezone.now()
    cutoff_date = now - timedelta(hours=72)
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_date,
        data_pubblicazione__lte=now,
        is_pubbliredazionale=False
    ).exclude(
        titolo__istartswith='test'
    ).exclude(
        categoria='Cosa fare oggi'
    ).order_by('-data_pubblicazione')

    for article in articles:
        article.keywords = article.meta_keywords

    logger.info(f"Generata sitemap news con {len(articles)} articoli")

    template = loader.get_template('sitemap_news.xml')
    context = {'articles': articles}
    return HttpResponse(template.render(context, request), content_type='application/xml')

def fonti_articolo(request, slug):
    """Vista per mostrare tutte le fonti di un articolo"""
    articolo = get_object_or_404(Articolo, slug=slug, approvato=True)

    logger.info(f"Visualizzazione fonti articolo: {articolo.titolo}")
    context = {
        'articolo': articolo,
        'categoria_attiva': None,
        'current_year': timezone.now().year,
    }

    return render(request, "fonti.html", context)

def caplet(request):
    """Vista per il gioco Caplet"""
    # Carica i puzzle dal file JSON
    puzzle_file = os.path.join(settings.BASE_DIR, 'home', 'static', 'home', 'strategic_puzzles_20250922_085045.json')

    try:
        with open(puzzle_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Seleziona un puzzle casuale
        puzzles = data.get('puzzles', [])
        if puzzles:
            puzzle = random.choice(puzzles)
        else:
            # Puzzle di fallback se il file non Ã¨ valido
            puzzle = {
                "id": "puzzle_5x5_fallback",
                "size": 5,
                "zones": [
                    [1, 1, 2, 2, 2],
                    [1, 3, 3, 2, 2],
                    [1, 3, 4, 4, 5],
                    [1, 3, 4, 5, 5],
                    [1, 3, 4, 5, 5]
                ]
            }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        # Puzzle di fallback se il file non esiste o Ã¨ corrotto
        puzzle = {
            "id": "puzzle_5x5_fallback",
            "size": 5,
            "zones": [
                [1, 1, 2, 2, 2],
                [1, 3, 3, 2, 2],
                [1, 3, 4, 4, 5],
                [1, 3, 4, 5, 5],
                [1, 3, 4, 5, 5]
            ]
        }
    # Serializza le zone come JSON per il template
    puzzle_zones_json = json.dumps(puzzle['zones'])

    context = {
        'puzzle': puzzle,
        'puzzle_zones_json': puzzle_zones_json,
        'categoria_attiva': None,
        'current_year': timezone.now().year,
    }

    return render(request, "caplet.html", context)

def about(request):
    """Vista per la pagina About - Informazioni sul progetto"""
    context = {
        'current_year': timezone.now().year,
    }

    return render(request, "about.html", context)


def autore_sven(request):
    """Pagina autore di Sven Rinaldi (direttore editoriale) - baricentro sulla persona."""
    context = {
        'current_year': timezone.now().year,
    }
    return render(request, "autore_sven_rinaldi.html", context)


def pubblicita(request):
    """Vista per la pagina di pubblicitÃ  e pricing"""
    import html as _html
    import decimal
    from django.db.models import Max, Sum
    from admin_panel.models import Banner

    def _strip_html(text):
        text = re.sub(r'<[^>]+>', ' ', text)
        text = _html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


    # â”€â”€ Esempi reali di pubbliredazionali (i piÃ¹ visti) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    publi_raw = Articolo.objects.filter(
        is_pubbliredazionale=True
    ).exclude(contenuto='').exclude(contenuto__isnull=True).order_by('-views')

    esempi_publi = []
    for p in publi_raw:
        contenuto = p.contenuto or ''
        if len(contenuto) < 100:
            continue
        clean = _strip_html(contenuto)
        if len(clean.split()) < 60:
            continue

        esempi_publi.append({
            'titolo': p.titolo or '',
            'estratto': clean[:500],
            'parole': len(clean.split()),
            'foto': p.foto or '',
            'slug': p.slug or '',
        })

        if len(esempi_publi) >= 4:
            break

    # â”€â”€ Statistiche dinamiche â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    banner_stats = Banner.objects.filter(impressions__gt=0).aggregate(
        max_impressions=Max('impressions'),
        total_impressions=Sum('impressions'),
        max_clicks=Max('clicks'),
    )
    max_impressions = banner_stats.get('max_impressions') or 0
    total_impressions = banner_stats.get('total_impressions') or 0

    ctr_max = Banner.objects.filter(impressions__gt=0, clicks__gt=0).aggregate(
        m=Max(ExpressionWrapper(F('clicks') * 100.0 / F('impressions'), output_field=FloatField()))
    )['m'] or 0
    ctr_max = round(ctr_max, 1)

    newsletter_emails_sent = NewsletterLog.objects.filter(stato='success').aggregate(
        total=Sum('num_destinatari')
    )['total'] or 0

    # Prezzi calcolati dal prezzo giornaliero minimo pubblico (â‚¬3.40/giorno, visibilitÃ  Bassa)
    price_per_day = decimal.Decimal('3.40')
    price_banner_30 = int(price_per_day * 30)   # â‚¬102 â€” include orizzontale + verticale (visibilitÃ  Bassa)
    publi_price = 200
    price_bundle = 280  # Pubbliredazionale + banner visibilitÃ  Alta 30gg
    articoli_count = get_published_articles_query().count()

    context = {
        'current_year': timezone.now().year,
        'esempi_publi': esempi_publi,
        'ctr_max': ctr_max,
        'max_impressions': max_impressions,
        'total_impressions': total_impressions,
        'newsletter_emails_sent': newsletter_emails_sent,
        'articoli_count': articoli_count,
        'price_banner_30': price_banner_30,
        'price_per_day': price_per_day,
        'publi_price': publi_price,
        'price_bundle': price_bundle,
    }

    return render(request, "pubblicita.html", context)


@require_http_methods(["POST"])
@csrf_exempt
def chatbot_api(request):
    """
    API endpoint per il chatbot
    Riceve messaggi dall'utente e restituisce risposte + articoli pertinenti
    """
    try:
        # Parse JSON body
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        conversation_history = data.get('conversation_history', [])
        session_id = data.get('session_id', str(uuid.uuid4()))

        if not user_message:
            return JsonResponse({
                'error': 'Messaggio vuoto'
            }, status=400)

        # Traccia tempo di risposta
        start_time = time.time()

        # Processa il messaggio con il servizio chatbot
        chatbot = ChatbotService()
        result = chatbot.process_message(user_message, conversation_history)

        # Calcola tempo di risposta
        response_time_ms = int((time.time() - start_time) * 1000)

        # Estrai metadata
        user_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
        if user_ip:
            user_ip = user_ip.split(',')[0].strip()
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        # Salva conversazione nel database
        article_ids = [a['id'] for a in result['articles']]
        ChatbotConversation.objects.create(
            session_id=session_id,
            user_message=user_message,
            bot_response=result['response'],
            intent_data=result['intent'],
            articles_found=len(result['articles']),
            articles_ids=article_ids,
            user_ip=user_ip,
            user_agent=user_agent[:500] if user_agent else '',
            response_time_ms=response_time_ms
        )

        logger.info(f"Chatbot richiesta: '{user_message}' -> {len(result['articles'])} articoli trovati ({response_time_ms}ms)")
        logger.info(f"Intent restituito: {result.get('intent', 'MANCANTE')}")
        logger.info(f"Lunghezza risposta: {len(result['response'])} caratteri")

        return JsonResponse({
            'response': result['response'],
            'articles': result['articles'],
            'intent': result['intent'],
            'session_id': session_id
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'JSON non valido'
        }, status=400)
    except Exception as e:
        logger.error(f"Errore API chatbot: {e}", exc_info=True)
        return JsonResponse({
            'error': 'Errore interno del server'
        }, status=500)


def chatbot_results(request):
    """
    Vista per mostrare i risultati della ricerca chatbot
    Mostra gli articoli trovati in base alla query
    """
    query = request.GET.get('q', '')
    intent_json = request.GET.get('intent', '{}')

    try:
        intent = json.loads(intent_json)
    except Exception:
        intent = {}

    # Ricerca articoli usando lo stesso servizio del chatbot
    chatbot = ChatbotService()
    articles = chatbot._search_articles(intent)
    # Paginazione: 8 articoli per pagina (come homepage)
    # Con 4 banner in posizioni fisse, avremo 12 elementi totali
    paginator = Paginator(articles, 8)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Posizioni fisse dei banner (1 per riga, mai in pos 0 o 11)
    banner_positions = [1, 4, 7, 10]  # Banner in posizioni non contigue

    # Serializza intent per template
    intent_str = json.dumps(intent)

    context = {
        'articoli': page_obj,
        'query': query,
        'intent': intent_str,
        'total_results': len(articles),
        'categoria_attiva': None,
        'current_year': timezone.now().year,
        'banner_positions': banner_positions,
    }

    return render(request, "chatbot_results.html", context)


def indexnow_key(request):
    """Serve IndexNow verification key file"""
    from django.conf import settings
    key = settings.INDEXNOW_KEY if hasattr(settings, 'INDEXNOW_KEY') else os.getenv('INDEXNOW_KEY', '')
    return HttpResponse(key, content_type='text/plain')


@cache_page(1800)
def programmazione_cinema(request):
    """
    Vista per mostrare la programmazione aggiornata dei cinema locali.
    Usa una cache applicativa fresh/stale e scraping parallelo su cache miss.
    """
    from .context_processors import get_categorie_menu

    cinema_data = _get_cinema_data()
    now = datetime.now()
    context = {
        'cinema_data': cinema_data,
        'last_update': now,
        'current_year': now.year,
        'categorie_disponibili': get_categorie_menu(rubriche_at_end=True),
        'schema_json': _build_cinema_schema(cinema_data),
    }

    return render(request, 'programmazione_cinema.html', context)


def calendario_eventi(request):
    """
    Vista per mostrare il calendario degli eventi
    Mostra gli articoli con data_evento in formato calendario mensile
    """
    from calendar import monthcalendar, month_name
    from collections import defaultdict

    # Ottieni mese e anno da parametri GET, default a mese corrente
    now = timezone.now()
    try:
        year = int(request.GET.get('year', now.year))
        month = int(request.GET.get('month', now.month))
    except (ValueError, TypeError):
        year = now.year
        month = now.month

    # Valida mese/anno
    if month < 1 or month > 12:
        month = now.month
    if year < 2020 or year > 2030:
        year = now.year

    # Calcola mese precedente e successivo
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    # Ottieni eventi del mese
    from datetime import date
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    eventi = Articolo.objects.filter(
        approvato=True,
        data_evento__gte=start_date,
        data_evento__lt=end_date
    ).only(
        'id', 'titolo', 'slug', 'foto', 'data_evento', 'data_pubblicazione'
    ).order_by('data_evento', 'data_pubblicazione')

    # Organizza eventi per giorno
    eventi_per_giorno = defaultdict(list)
    for evento in eventi:
        if evento.data_evento:
            eventi_per_giorno[evento.data_evento.day].append(evento)

    # Genera struttura calendario
    cal = monthcalendar(year, month)
    calendario_struttura = []

    for week in cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append({'day': None, 'events': []})
            else:
                week_data.append({
                    'day': day,
                    'events': eventi_per_giorno.get(day, []),
                    'is_today': (day == now.day and month == now.month and year == now.year)
                })
        calendario_struttura.append(week_data)

    # Ottieni nomi mesi in italiano
    mesi_italiani = [
        '', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
        'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre'
    ]

    context = {
        'calendario': calendario_struttura,
        'month': month,
        'year': year,
        'month_name': mesi_italiani[month],
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'current_year': now.year,
        'total_eventi': eventi.count(),
    }
    from .context_processors import get_categorie_menu
    context['categorie_disponibili'] = get_categorie_menu(rubriche_at_end=True)

    return render(request, 'calendario_eventi.html', context)


# ---------------------------------------------------------------------------
# NEWSLETTER
# ---------------------------------------------------------------------------

def _get_newsletter_context():
    """Recupera gli articoli per la newsletter (logica condivisa tra preview e command)."""
    from datetime import date, time
    from django.utils.timezone import make_aware
    import datetime as dt

    oggi = date.today()
    domani = oggi + dt.timedelta(days=1)
    oggi_mezzanotte = make_aware(dt.datetime.combine(oggi, time.min))
    ieri_mezzanotte = oggi_mezzanotte - dt.timedelta(days=1)

    _categorie_escluse = ['Cultura & Eventi', 'Cosa fare oggi']

    # Articoli pubblicati oggi (dalla mezzanotte), esclusi Cultura & Eventi e Cosa fare oggi
    articoli_oggi_qs = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=oggi_mezzanotte,
        escludi_newsletter=False,
    ).exclude(categoria__in=_categorie_escluse).order_by('-views')

    # Articoli dal momento dell'ultimo invio a oggi mezzanotte.
    # Usa il timestamp dell'ultimo invio riuscito come cutoff per non riproporre
    # articoli giÃ  inclusi nella newsletter precedente.
    ultimo_invio = NewsletterLog.objects.filter(
        stato__in=['success', 'partial']
    ).order_by('-data_invio').first()
    cutoff_ieri = ultimo_invio.data_invio if ultimo_invio else ieri_mezzanotte

    articoli_ieri_qs = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_ieri,
        data_pubblicazione__lt=oggi_mezzanotte,
        escludi_newsletter=False,
    ).exclude(categoria__in=_categorie_escluse).order_by('-views')

    # Raggruppa per categoria
    def raggruppa_per_categoria(qs):
        result = {}
        for art in qs:
            result.setdefault(art.categoria, []).append(art)
        return result

    # Eventi Cultura & Eventi con data_evento = domani
    eventi_domani = Articolo.objects.filter(
        approvato=True,
        categoria='Cultura & Eventi',
        data_evento=domani,
        escludi_newsletter=False,
    ).order_by('-views')

    # Banner orizzontali attivi per la newsletter (max 2, per prioritÃ  poi shuffle)
    try:
        from admin_panel.models import Banner as _Banner
        _now = timezone.now()
        _horizontal = ['both', 'header', 'footer', 'article_top', 'article_middle', 'article_bottom']
        _banners = list(_Banner.objects.filter(
            position__in=_horizontal,
            status='active',
            payment_status__in=['completed', 'saved'],
            approved=True,
            start_date__lte=_now,
            end_date__gte=_now,
        ).order_by('priority'))
        random.shuffle(_banners)
        _banners.sort(key=lambda b: b.priority)
        _site = getattr(settings, 'SITE_URL', 'https://ombradelportico.it').rstrip('/')
        newsletter_banners = []
        for _b in _banners[:4]:
            if not _b.image:
                continue
            _img = _b.image.url
            if not _img.startswith('http'):
                _img = _site + _img
            newsletter_banners.append({
                'image_url': _img,
                'link_url': f"{_site}/admin-panel/banner/{_b.id}/click/",
                'alt_text': _b.alt_text or _b.title,
            })
    except Exception:
        newsletter_banners = []

    return {
        'articoli_oggi': raggruppa_per_categoria(articoli_oggi_qs),
        'articoli_ieri': raggruppa_per_categoria(articoli_ieri_qs),
        'eventi_domani': list(eventi_domani),
        'data_oggi': oggi,
        'data_domani': domani,
        'newsletter_banners': newsletter_banners,
        'site_url': getattr(settings, 'SITE_URL', 'https://ombradelportico.it'),
    }


def newsletter_subscribe(request):
    """Pagina di iscrizione alla newsletter."""
    from django.contrib import messages as msg

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    success = False
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        nome = request.POST.get('nome', '').strip()
        if email:
            subscriber, created = NewsletterSubscriber.objects.get_or_create(
                email=email,
                defaults={'nome': nome},
            )
            if created:
                success = True
            elif not subscriber.attivo:
                subscriber.attivo = True
                if nome:
                    subscriber.nome = nome
                subscriber.save()
                success = True
            else:
                if is_ajax:
                    return JsonResponse({'ok': False, 'already': True, 'message': 'Sei giÃ  iscritto alla newsletter.'})
                msg.info(request, 'Questa email Ã¨ giÃ  iscritta alla newsletter.')
        else:
            if is_ajax:
                return JsonResponse({'ok': False, 'message': 'Inserisci un indirizzo email valido.'})
            msg.error(request, 'Inserisci un indirizzo email valido.')

        if is_ajax and success:
            return JsonResponse({'ok': True, 'message': 'Iscrizione completata! Da oggi riceverai le notizie di Carpi ogni pomeriggio.'})

    return render(request, 'newsletter/subscribe.html', {'success': success})


def newsletter_unsubscribe(request, token):
    """Disiscrizione dalla newsletter tramite token univoco."""
    try:
        subscriber = NewsletterSubscriber.objects.get(token_disiscrizione=token)
        subscriber.attivo = False
        subscriber.save()
        disiscritto = True
    except NewsletterSubscriber.DoesNotExist:
        disiscritto = False

    return render(request, 'newsletter/unsubscribe.html', {'disiscritto': disiscritto})


def newsletter_preview(request):
    """Preview HTML della newsletter (solo staff)."""
    if not request.user.is_staff:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    ctx = _get_newsletter_context()
    ctx['site_url'] = request.build_absolute_uri('/').rstrip('/')
    ctx['subscriber'] = None  # preview: nessun token reale
    ctx['is_preview'] = True
    return render(request, 'newsletter/preview.html', ctx)


def short_link_redirect(request, token):
    """Redirect tracciato per short link social."""
    from django.core.cache import cache
    from django.db.models import F
    from django.http import Http404, HttpResponseRedirect
    from .models import ShortLink
    from .share_links import build_share_url

    try:
        short_link = ShortLink.objects.select_related('articolo').get(token=token)
    except ShortLink.DoesNotExist:
        raise Http404("Short link non trovato")

    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:80]
    cache_key = f"shortlink:{short_link.pk}:{ip}:{hash(user_agent)}"
    if not cache.get(cache_key):
        referer = request.META.get('HTTP_REFERER', '')[:500]
        ShortLink.objects.filter(pk=short_link.pk).update(
            clicks_count=F('clicks_count') + 1,
            last_referer=referer,
        )
        cache.set(cache_key, True, 60)

    return HttpResponseRedirect(build_share_url(short_link.articolo, short_link.platform, short_link.medium))


@csrf_exempt
@require_POST
def banner_impression(request, banner_id):
    """Beacon JS: conta un'impression banner, dedup via cache, atomico."""
    from admin_panel.models import Banner

    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'wget', 'python-requests']
    if any(keyword in user_agent for keyword in bot_keywords):
        return HttpResponse(status=204)

    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
    cache_key = f"banner_impr:{banner_id}:{ip}:{hash(user_agent[:80])}"
    if not cache.get(cache_key):
        updated = Banner.objects.filter(pk=banner_id, status='active').update(
            impressions=F('impressions') + 1
        )
        if updated:
            cache.set(cache_key, True, 600)

    return HttpResponse(status=204)


def link_in_bio_search(request):
    """Fragment AJAX per ricerca nella smart link in bio."""
    return link_in_bio(request, search_only=True)


@cache_page(60 * 5)  # cache 5 minuti
@vary_on_headers('X-Requested-With')  # cache separata per richieste AJAX
def link_in_bio(request, search_only=False):
    """
    Landing page per il link in bio Instagram.
    Mostra gli articoli condivisi su IG (post/storia/reel) in layout lista
    verticale mobile-first stile Linktree, con infinite scroll.

    Paginazione: 25 articoli per pagina via ?page=N.
    Se richiesta AJAX (X-Requested-With: XMLHttpRequest), restituisce solo il
    fragment delle card, per essere appeso dal JS lato client.

    URL: /instagram/
    """
    from .models import SocialPublicationLog
    from .share_links import build_short_share_url
    from django.core.paginator import Paginator
    from django.db.models import Max, Q
    from django.utils import timezone
    from datetime import timedelta

    ig_platforms = ['instagram', 'instagram_story', 'instagram_reel']
    now = timezone.now()
    last_7_days = now - timedelta(days=7)
    last_24_hours = now - timedelta(hours=24)
    search_query = request.GET.get('q', '').strip()

    article_ids = (
        SocialPublicationLog.objects
        .filter(platform__in=ig_platforms, success=True, published_at__gte=last_7_days)
        .values_list('articolo_id', flat=True)
        .distinct()
    )

    story_ids = set(
        SocialPublicationLog.objects.filter(
            platform='instagram_story',
            success=True,
            published_at__gte=last_24_hours,
            articolo_id__in=article_ids,
        ).values_list('articolo_id', flat=True)
    )

    from django.db.models import Case, IntegerField, Value, When
    recent_story_order = Case(
        When(id__in=story_ids, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    articoli_qs = (
        Articolo.objects
        .filter(id__in=article_ids, approvato=True)
        .annotate(last_ig_publication=Max('social_publications__published_at'), recent_story_order=recent_story_order)
        .only('id', 'titolo', 'sommario', 'categoria', 'slug', 'foto',
              'foto_upload', 'data_pubblicazione')
        .order_by('-recent_story_order', '-data_pubblicazione', '-last_ig_publication')
    )
    if search_query:
        articoli_qs = articoli_qs.filter(
            Q(titolo__icontains=search_query) | Q(categoria__icontains=search_query)
        )

    paginator = Paginator(articoli_qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    for articolo in page.object_list:
        articolo.bio_short_url = build_short_share_url(articolo, 'instagram', 'bio')
        articolo.is_recent_story = articolo.pk in story_ids

    # AJAX -> solo fragment delle cards (no header/footer)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    template = 'link_in_bio_cards.html' if (is_ajax or search_only) else 'link_in_bio.html'
    return render(request, template, {
        'articoli': page,
        'search_query': search_query,
        'has_recent_story': bool(story_ids),
    })
