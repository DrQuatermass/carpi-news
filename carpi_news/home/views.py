import logging
import json
import os
import random
import re
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.template import loader
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import models
from datetime import datetime, timedelta
from .models import Articolo, ChatbotConversation, NewsletterSubscriber, NewsletterLog
from .chatbot_service import ChatbotService
import time
import uuid


logger = logging.getLogger(__name__)


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


# Create your views here.
def home(request):
    # Filtro per categoria (opzionale)
    categoria = request.GET.get('categoria', None)

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
    all_banners_qs = list(Banner.objects.filter(
        position__in=['between_articles', 'both'],
        status='active',
        payment_status='completed',
        approved=True,
        start_date__lte=_now,
        end_date__gte=_now,
    ).exclude(image_vertical='').exclude(image_vertical__isnull=True).select_related('user'))
    # Escludi immagini con rapporto larghezza/altezza > 2 (banner orizzontali nella posizione verticale)
    all_banners = [
        b for b in all_banners_qs
        if b.image_vertical.height > 0 and b.image_vertical.width / b.image_vertical.height <= 2
    ]

    # Verifica che non sia un bot
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'wget', 'python-requests']
    is_bot = any(keyword in user_agent for keyword in bot_keywords)

    # Selezione randomica pesata di 4 banner (uno per riga)
    active_banners = []
    if all_banners:
        for slot_num in range(4):
            banner = weighted_random_choice(all_banners)
            if banner:
                active_banners.append(banner)
                # Incrementa impressions solo se non bot e non già mostrato in questa sessione
                session_key = f'banner_impression_{banner.id}_{page_number}_{slot_num}'
                if not is_bot and not request.session.get(session_key, False):
                    banner.impressions += 1
                    banner.save(update_fields=['impressions'])
                    request.session[session_key] = True
                    logger.debug(f"Impression unica banner: {banner.title} (pag {page_number}, slot {slot_num})")
                elif is_bot:
                    logger.debug(f"Bot rilevato, impression non contata per banner: {banner.title}")
    
    # Log per debugging
    if categoria:
        logger.info(f"Caricati {len(page_obj)} articoli approvati categoria '{categoria}' (pagina {page_number})")
    else:
        logger.info(f"Caricati {len(page_obj)} articoli approvati per la home (pagina {page_number})")
    
    # Ottieni lista categorie disponibili per il menu (raggruppa Editoriale e L'Eco del Consiglio in Rubriche)
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False
    
    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)
    
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

    # Trova la prima immagine articolo per preload LCP
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
        'first_article_image': first_article_image,  # Per preload LCP
        'first_banner_image': first_banner_image,  # Per preload banner
        'current_page': page_obj.number,
        'total_pages': paginator.num_pages,
        'has_prev': page_obj.has_previous(),
        'has_next': page_obj.has_next(),
        'categoria_attiva': categoria,
        'categorie_disponibili': list(categorie_disponibili),
        'current_year': 2025,
        'banner_positions': banner_positions,
        'active_banners_count': len(active_banners),
    }
    
    # Se è una richiesta AJAX, restituisci solo i dati JSON
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
                banners_data.append({
                    'id': banner.id,
                    'image_url': banner.image_vertical.url,
                    'alt_text': banner.alt_text,
                    'image_width': banner.image_vertical.width,
                    'image_height': banner.image_vertical.height,
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

def dettaglio_articolo(request, slug):
    # Recupera articolo pubblicabile (approvato e, se pubbliredazionale, pagato)
    from django.db.models import Q
    articolo = get_object_or_404(
        Articolo,
        slug=slug
    )

    # Verifica che sia pubblicabile
    is_publishable = (
        (not articolo.is_pubbliredazionale and articolo.approvato) or
        (articolo.is_pubbliredazionale and articolo.approvato and articolo.payment_status == 'completed')
    )

    if not is_publishable:
        from django.http import Http404
        raise Http404("Articolo non disponibile")

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
            articolo.refresh_from_db()
            logger.info(f"Visualizzazione unica articolo: {articolo.titolo} (views: {articolo.views})")
        else:
            logger.debug(f"Bot rilevato, view non contata: {articolo.titolo} (UA: {user_agent[:100]})")
    else:
        logger.debug(f"Articolo già visto in questa sessione: {articolo.titolo}")

    # Ricarica l'oggetto comunque per avere dati aggiornati
    articolo.refresh_from_db()
    
    # Ottieni liste categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False
    
    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)
    
    # Articoli correlati: ultimi 6 della stessa categoria (escluso quello corrente, solo pubblicati)
    articoli_correlati = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__lte=timezone.now(),
        categoria=articolo.categoria
    ).exclude(pk=articolo.pk).order_by('-data_pubblicazione')[:6]

    context = {
        'articolo': articolo,
        'articoli_correlati': articoli_correlati,
        'categorie_disponibili': list(categorie_disponibili),
        'categoria_attiva': None,  # Nessuna categoria attiva nel dettaglio
        'current_year': 2025,
    }
    
    return render(request, "dettaglio_articolo.html", context)

def privacy_policy(request):
    """Vista per la pagina della Privacy Policy"""
    # Ottieni categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False
    
    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)
    
    context = {
        'categorie_disponibili': list(categorie_disponibili),
        'current_year': 2025,
    }
    
    return render(request, "privacy_policy.html", context)

def sitemap_index(request):
    """Vista per il sitemap index"""
    now = timezone.now()

    # Controlla se ci sono articoli in archivio (più vecchi di 30 giorni)
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

    # Data ultimo aggiornamento sitemap news (ultime 48 ore)
    news_cutoff = now - timedelta(hours=48)
    news_lastmod = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=news_cutoff,
        data_pubblicazione__lte=now
    ).exclude(
        titolo__istartswith='test'
    ).exclude(
        categoria__in=['Editoriale', 'Cosa fare oggi']
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

    # Aggiungi campo days_old per priorità dinamiche
    for article in articles:
        article.days_old = (now - article.data_pubblicazione).days

    # Data ultimo aggiornamento
    last_update = articles.first().data_pubblicazione if articles else now

    logger.info(f"Generata sitemap principale con {len(articles)} articoli (ultimi 30 giorni)")

    template = loader.get_template('sitemap.xml')
    context = {
        'articles': articles,
        'last_update': last_update
    }
    return HttpResponse(template.render(context, request), content_type='application/xml')

def sitemap_archive(request):
    """Vista per la sitemap archivio (articoli più vecchi di 30 giorni)"""
    cutoff_date = timezone.now() - timedelta(days=30)

    # Articoli più vecchi di 30 giorni, limitati a 10.000 per performance
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
    """Vista per la sitemap Google News (ultime 48 ore)"""
    # Solo articoli approvati delle ultime 48 ore (non futuri)
    now = timezone.now()
    cutoff_date = now - timedelta(hours=48)
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_date,
        data_pubblicazione__lte=now,
        is_pubbliredazionale=False  # Escludi pubbliredazionali da Google News
    ).exclude(
        titolo__istartswith='test'  # Escludi articoli di test
    ).exclude(
        categoria__in=['Editoriale', 'Cosa fare oggi']  # Google News preferisce notizie, non editoriali o agende
    ).order_by('-data_pubblicazione')

    # Genera keywords per ogni articolo
    stopwords_it = {'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'una', 'di', 'da', 'a', 'in', 'con', 'su', 'per', 'tra', 'fra', 'del', 'della', 'dei', 'delle', 'al', 'alla', 'ai', 'alle', 'dal', 'dalla', 'dai', 'dalle', 'sul', 'sulla', 'sui', 'sulle', 'nel', 'nella', 'nei', 'nelle', 'e', 'o', 'ma', 'se', 'che', 'chi', 'cui'}

    for article in articles:
        # Estrai parole dal titolo (rimuovi punteggiatura, converti lowercase)
        words = re.findall(r'\b\w+\b', article.titolo.lower())
        # Filtra stopwords e parole corte (<3 caratteri)
        keywords = [w.capitalize() for w in words if w not in stopwords_it and len(w) >= 3]
        # Limita a prime 5 keywords + categoria + "Carpi"
        keyword_list = keywords[:5] + [article.categoria, 'Carpi']
        article.keywords = ', '.join(filter(None, keyword_list))  # Filtra valori None/vuoti

    logger.info(f"Generata sitemap news con {len(articles)} articoli")

    template = loader.get_template('sitemap_news.xml')
    context = {'articles': articles}
    return HttpResponse(template.render(context, request), content_type='application/xml')

def fonti_articolo(request, slug):
    """Vista per mostrare tutte le fonti di un articolo"""
    articolo = get_object_or_404(Articolo, slug=slug, approvato=True)

    logger.info(f"Visualizzazione fonti articolo: {articolo.titolo}")

    # Ottieni liste categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    context = {
        'articolo': articolo,
        'categorie_disponibili': list(categorie_disponibili),
        'categoria_attiva': None,
        'current_year': 2025,
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
            # Puzzle di fallback se il file non è valido
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
        # Puzzle di fallback se il file non esiste o è corrotto
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

    # Ottieni categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    # Serializza le zone come JSON per il template
    puzzle_zones_json = json.dumps(puzzle['zones'])

    context = {
        'puzzle': puzzle,
        'puzzle_zones_json': puzzle_zones_json,
        'categorie_disponibili': list(categorie_disponibili),
        'categoria_attiva': None,
        'current_year': 2025,
    }

    return render(request, "caplet.html", context)

def about(request):
    """Vista per la pagina About - Informazioni sul progetto"""
    # Ottieni categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    context = {
        'categorie_disponibili': list(categorie_disponibili),
        'current_year': 2025,
    }

    return render(request, "about.html", context)


def pubblicita(request):
    """Vista per la pagina di pubblicità e pricing"""
    import html as _html
    import decimal
    from django.db.models import Max, Sum
    from admin_panel.models import Banner

    def _strip_html(text):
        text = re.sub(r'<[^>]+>', ' ', text)
        text = _html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


    # ── Esempi reali di pubbliredazionali (i più visti) ───────────────────────
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

    # ── Statistiche dinamiche ──────────────────────────────────────────────────
    banner_stats = Banner.objects.filter(impressions__gt=0).aggregate(
        max_impressions=Max('impressions'),
        total_impressions=Sum('impressions'),
        max_clicks=Max('clicks'),
    )
    max_impressions = banner_stats.get('max_impressions') or 0
    total_impressions = banner_stats.get('total_impressions') or 0

    ctr_max = 0
    for b in Banner.objects.filter(impressions__gt=0, clicks__gt=0):
        ctr = round((b.clicks / b.impressions) * 100, 1)
        if ctr > ctr_max:
            ctr_max = ctr

    newsletter_emails_sent = NewsletterLog.objects.filter(stato='success').aggregate(
        total=Sum('num_destinatari')
    )['total'] or 0

    # Prezzi calcolati dal prezzo giornaliero minimo pubblico (€3.40/giorno, visibilità Bassa)
    price_per_day = decimal.Decimal('3.40')
    price_banner_30 = int(price_per_day * 30)   # €102 — include orizzontale + verticale (visibilità Bassa)
    publi_price = 200
    price_bundle = 280  # Pubbliredazionale + banner visibilità Alta 30gg

    # ── Categorie per il menu di navigazione ──────────────────────────────────
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    articoli_count = get_published_articles_query().count()

    context = {
        'categorie_disponibili': list(categorie_disponibili),
        'current_year': 2025,
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

    # Ottieni categorie per il menu
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)

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
        'categorie_disponibili': list(categorie_disponibili),
        'categoria_attiva': None,
        'current_year': 2025,
        'banner_positions': banner_positions,
    }

    return render(request, "chatbot_results.html", context)


def indexnow_key(request):
    """Serve IndexNow verification key file"""
    from django.conf import settings
    key = settings.INDEXNOW_KEY if hasattr(settings, 'INDEXNOW_KEY') else os.getenv('INDEXNOW_KEY', '')
    return HttpResponse(key, content_type='text/plain')


def programmazione_cinema(request):
    """
    Vista per mostrare la programmazione aggiornata dei cinema locali
    Effettua scraping in tempo reale dei siti dei cinema di Carpi
    Mostra SOLO i film con proiezioni OGGI
    """
    import requests
    from bs4 import BeautifulSoup
    from datetime import datetime
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cinema_data = []

    # Calcola la data di oggi in vari formati
    today = datetime.now()
    today_day = today.day
    today_day_padded = f"{today_day:02d}"  # Giorno con zero iniziale (es: "03")
    today_month_it = ['', 'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                      'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'][today.month]
    today_month_num = f"{today.month:02d}"  # Mese con zero iniziale (es: "12")
    weekdays_it = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
    today_weekday = weekdays_it[today.weekday()]

    # Pattern per trovare la data di oggi nel testo
    # Es: "Martedì 3", "3 dicembre", "mercoledì 3 dicembre", "03/12/2025"
    # Usa word boundary \b per evitare match parziali (es: "3" in "31")
    all_months_it = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                     'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
    other_months_it = '|'.join(m for m in all_months_it if m != today_month_it)
    today_patterns = [
        # "mercoledì 3" - con negative lookahead per escludere altri mesi (es: "venerdì 13 giugno")
        f"{today_weekday}\\s+\\b{today_day}\\b(?!\\s+(?:{other_months_it}))",
        f"{today_weekday}\\s+\\b{today_day_padded}\\b(?!\\s+(?:{other_months_it}))",
        f"\\b{today_day}\\b\\s+{today_month_it}",  # "3 dicembre" (non "31 dicembre")
        f"\\b{today_day_padded}\\b\\s+{today_month_it}",  # "03 dicembre"
        f"{today_weekday}\\s+\\b{today_day}\\b\\s+{today_month_it}",  # "mercoledì 3 dicembre"
        f"{today_day_padded}/{today_month_num}/",  # "03/12/2025" (Space City format)
    ]

    # Cinema Eden
    try:
        response = requests.get('https://www.cinemaedencarpi.it/', timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            films = []
            film_cards = soup.find_all('div', class_='tmb')

            for card in film_cards:
                try:
                    title_elem = card.find('h2', class_='t-entry-title') or card.find('h3')
                    title = title_elem.get_text(strip=True) if title_elem else None

                    if not title:
                        continue

                    # Cerca le informazioni del film (orari, date)
                    text_elem = card.find('div', class_='t-entry-text')
                    if not text_elem:
                        continue

                    info_text = text_elem.get_text(separator=' ', strip=True).lower()

                    # Verifica se il film ha proiezioni OGGI
                    has_today = False
                    today_showtimes = []

                    for pattern in today_patterns:
                        if re.search(pattern, info_text, re.IGNORECASE):
                            has_today = True
                            # Cerca orari dopo la data di oggi
                            # Pattern orari: 15:00, 21:30, etc
                            time_pattern = r'\b(\d{1,2}[:.]\d{2})\b'
                            # Cerca il testo dopo la data di oggi
                            match = re.search(pattern, info_text, re.IGNORECASE)
                            if match:
                                text_after_date = info_text[match.end():match.end()+100]
                                times = re.findall(time_pattern, text_after_date)
                                today_showtimes.extend(times[:3])  # Max 3 orari
                            break

                    if not has_today:
                        continue

                    # Cerca l'immagine
                    img_elem = card.find('img')
                    image = ''
                    if img_elem:
                        image = img_elem.get('data-src') or img_elem.get('src') or img_elem.get('data-lazy-src', '')
                        if 'placeholder' in image.lower() or 'default' in image.lower():
                            image = ''

                    # Formatta info
                    info = f"Oggi {today_weekday} {today_day} {today_month_it}"
                    if today_showtimes:
                        info += f" - Orari: {', '.join(today_showtimes)}"

                    films.append({
                        'title': title,
                        'image': image if image else '',
                        'info': info
                    })
                except Exception as e:
                    logger.error(f"Errore parsing film Cinema Eden: {e}")
                    continue

            if films:
                cinema_data.append({
                    'name': 'Cinema Eden',
                    'address': 'Via Santa Chiara 22, Carpi',
                    'website': 'https://www.cinemaedencarpi.it/',
                    'films': films
                })
    except Exception as e:
        logger.error(f"Errore scraping Cinema Eden: {e}")

    # Cinema Ariston - Cerca nella sezione id="movie"
    try:
        # User-Agent necessario: Ariston blocca richieste senza header browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get('https://www.aristoncinemacarpi.it/', headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            films = []

            # Cerca la sezione con id="movie"
            movie_section = soup.find('section', id='movie')

            if movie_section:
                # Trova tutti gli article (la classe è 'list-article' non 'news-item')
                articles = movie_section.find_all('article')

                logger.info(f"Cinema Ariston - Trovati {len(articles)} articoli in sezione #movie")

                for article in articles:
                    try:
                        # Titolo in h2.entry-title > a
                        title_elem = article.find('h2', class_='entry-title')
                        if not title_elem:
                            continue

                        title_link = title_elem.find('a')
                        title = title_link.get_text(strip=True) if title_link else title_elem.get_text(strip=True)

                        if not title or len(title) < 3:
                            continue

                        # Programmazione in div.entry-excerpt
                        excerpt = article.find('div', class_='entry-excerpt')
                        if not excerpt:
                            continue

                        # Analizza le righe della programmazione
                        lines = excerpt.get_text(separator='\n').split('\n')
                        has_today = False
                        today_showtimes = []

                        for line in lines:
                            line_lower = line.strip().lower()
                            if not line_lower:
                                continue

                            # Verifica se questa riga contiene la data di oggi
                            for pattern in today_patterns:
                                if re.search(pattern, line_lower, re.IGNORECASE):
                                    has_today = True
                                    # Estrai orario da questa riga (formato: "Lunedì 3 Dicembre 2025 – Ore 21:00")
                                    time_match = re.search(r'ore\s*(\d{1,2}:\d{2})', line_lower, re.IGNORECASE)
                                    if time_match:
                                        today_showtimes.append(time_match.group(1))
                                    break

                        if not has_today:
                            continue

                        # Immagine in div.list-article-thumb > a > img
                        image = ''
                        thumb = article.find('div', class_='list-article-thumb')
                        if thumb:
                            img_elem = thumb.find('img')
                            if img_elem:
                                image = img_elem.get('src', '')
                                # Fallback: prova data-src se src è vuoto
                                if not image:
                                    image = img_elem.get('data-src', '')

                        # Formatta info
                        info = f"Oggi {today_weekday} {today_day} {today_month_it}"
                        if today_showtimes:
                            info += f" - Orari: {', '.join(set(today_showtimes))}"

                        films.append({
                            'title': title,
                            'image': image if image else '',
                            'info': info
                        })

                        logger.info(f"Cinema Ariston - Film trovato: {title}")

                    except Exception as e:
                        logger.error(f"Errore parsing articolo Ariston: {e}")
                        continue
            else:
                logger.warning("Cinema Ariston - Sezione #movie non trovata")

            if films:
                cinema_data.append({
                    'name': 'Cinema Ariston',
                    'address': 'Via Ernesto Boccaletti 3, San Marino di Carpi',
                    'website': 'https://www.aristoncinemacarpi.it/',
                    'films': films
                })
            else:
                logger.warning("Cinema Ariston: nessun film per oggi")

    except Exception as e:
        logger.error(f"Errore scraping Cinema Ariston: {e}")

    # Cinema Corso (stessa struttura di Cinema Eden)
    try:
        response = requests.get('https://www.cinemacorsocarpi.it/', timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            films = []
            film_cards = soup.find_all('div', class_='tmb')

            for card in film_cards:
                try:
                    title_elem = card.find('h2', class_='t-entry-title') or card.find('h3')
                    title = title_elem.get_text(strip=True) if title_elem else None

                    if not title:
                        continue

                    # Cerca le informazioni del film
                    text_elem = card.find('div', class_='t-entry-text')
                    if not text_elem:
                        continue

                    info_text = text_elem.get_text(separator=' ', strip=True).lower()

                    # Verifica se il film ha proiezioni OGGI
                    has_today = False
                    today_showtimes = []

                    for pattern in today_patterns:
                        if re.search(pattern, info_text, re.IGNORECASE):
                            has_today = True
                            time_pattern = r'\b(\d{1,2}[:.]\d{2})\b'
                            match = re.search(pattern, info_text, re.IGNORECASE)
                            if match:
                                text_after_date = info_text[match.end():match.end()+100]
                                times = re.findall(time_pattern, text_after_date)
                                today_showtimes.extend(times[:3])
                            break

                    if not has_today:
                        continue

                    # Cerca l'immagine
                    img_elem = card.find('img')
                    image = ''
                    if img_elem:
                        image = img_elem.get('data-src') or img_elem.get('src', '')
                        if 'placeholder' in image.lower():
                            image = ''

                    # Formatta info
                    info = f"Oggi {today_weekday} {today_day} {today_month_it}"
                    if today_showtimes:
                        info += f" - Orari: {', '.join(today_showtimes)}"

                    films.append({
                        'title': title,
                        'image': image if image else '',
                        'info': info
                    })
                except Exception as e:
                    logger.error(f"Errore parsing film Cinema Corso: {e}")
                    continue

            if films:
                cinema_data.append({
                    'name': 'Cinema Corso',
                    'address': 'Corso M. Fanti 91, Carpi',
                    'website': 'https://www.cinemacorsocarpi.it/',
                    'films': films
                })
    except Exception as e:
        logger.error(f"Errore scraping Cinema Corso: {e}")

    # Space City Multisala
    try:
        # User-Agent per evitare blocchi
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get('https://www.spacecity.it/', headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            films = []

            # Cerca i div con class "movie movie--preview"
            movie_divs = soup.find_all('div', class_='movie--preview')

            for movie_div in movie_divs:
                try:
                    # Estrai il titolo dal link a.movie__title
                    title_elem = movie_div.find('a', class_='movie__title')
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not title:
                        continue

                    # Estrai l'immagine
                    image = ''
                    img_elem = movie_div.find('img', class_='img-fluid')
                    if img_elem:
                        image = img_elem.get('src', '')

                    # Cerca la sezione schedule per verificare la data
                    schedule_section = movie_div.find('div', class_='schedule-section-show')
                    if not schedule_section:
                        continue

                    schedule_text = schedule_section.get_text(separator=' ', strip=True).lower()

                    # Verifica se ha proiezioni OGGI e estrai solo gli orari di oggi
                    has_today = False
                    today_showtimes = []

                    # La schedule contiene tutti i giorni in un'unica riga
                    # Devo estrarre solo gli orari tra la data di oggi e la data successiva
                    schedule_full_text = schedule_section.get_text(separator=' ', strip=True)

                    # Cerca la data di oggi nel testo
                    for pattern in today_patterns:
                        match = re.search(pattern, schedule_full_text, re.IGNORECASE)
                        if match:
                            has_today = True

                            # Estrai il testo dopo la data di oggi
                            text_after_today = schedule_full_text[match.end():]

                            # Trova dove finisce la sezione di oggi (cerca la prossima data)
                            # Pattern per trovare la prossima data (es: "Giovedì 04/12/2025")
                            next_date_pattern = r'(luned[ìi]|marted[ìi]|mercoled[ìi]|gioved[ìi]|venerd[ìi]|sabato|domenica)\s+\d{2}/\d{2}/\d{4}'
                            next_date_match = re.search(next_date_pattern, text_after_today, re.IGNORECASE)

                            if next_date_match:
                                # Prendi solo il testo fino alla prossima data
                                today_section = text_after_today[:next_date_match.start()]
                            else:
                                # Non c'è una data successiva, prendi tutto
                                today_section = text_after_today[:200]

                            # Estrai tutti gli orari dalla sezione di oggi
                            times = re.findall(r'\b(\d{1,2}:\d{2})\b', today_section)
                            today_showtimes.extend(times)
                            break

                    if not has_today:
                        continue

                    # Formatta info - solo orari, no sale
                    info = f"Oggi {today_weekday} {today_day} {today_month_it}"
                    if today_showtimes:
                        info += f" - Orari: {', '.join(today_showtimes)}"

                    films.append({
                        'title': title,
                        'image': image if image else '',
                        'info': info
                    })

                    logger.info(f"Space City - Trovato film: {title} - {info}")

                except Exception as e:
                    logger.error(f"Errore parsing film Space City: {e}")
                    continue

            if films:
                cinema_data.insert(0, {  # Inserisci all'inizio
                    'name': 'Space City Multisala',
                    'address': 'Viale dell\'Industria 9, Carpi',
                    'website': 'https://www.spacecity.it/',
                    'films': films
                })
            else:
                logger.warning("Space City: nessun film trovato per oggi")

    except Exception as e:
        logger.error(f"Errore scraping Space City: {e}")

    # Ottieni categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    if has_rubriche:
        categorie_disponibili.append('Rubriche')

    context = {
        'cinema_data': cinema_data,
        'last_update': datetime.now(),
        'current_year': datetime.now().year,
        'categorie_disponibili': categorie_disponibili,
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

    # Ottieni categorie per il menu di navigazione
    categorie_raw = get_published_articles_query().values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    if has_rubriche:
        categorie_disponibili.append('Rubriche')

    context['categorie_disponibili'] = categorie_disponibili

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
    # articoli già inclusi nella newsletter precedente.
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

    # Banner orizzontali attivi per la newsletter (max 2, per priorità poi shuffle)
    try:
        from admin_panel.models import Banner as _Banner
        _now = timezone.now()
        _horizontal = ['header', 'footer', 'article_top', 'article_middle', 'article_bottom']
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
                    return JsonResponse({'ok': False, 'already': True, 'message': 'Sei già iscritto alla newsletter.'})
                msg.info(request, 'Questa email è già iscritta alla newsletter.')
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
