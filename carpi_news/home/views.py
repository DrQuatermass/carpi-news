import logging
import json
import os
import random
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.template import loader
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from datetime import datetime, timedelta
from .models import Articolo, ChatbotConversation
from .chatbot_service import ChatbotService
import time
import uuid


logger = logging.getLogger(__name__)

# Create your views here.
def home(request):
    # Filtro per categoria (opzionale)
    categoria = request.GET.get('categoria', None)
    
    # Query base: solo articoli approvati
    articoli_query = Articolo.objects.filter(approvato=True)
    
    # Applica filtro categoria se specificato
    if categoria and categoria != 'tutti':
        if categoria.lower() == 'rubriche':
            # Filtra per Editoriale e L'Eco del Consiglio
            articoli_query = articoli_query.filter(categoria__in=['Editoriale', "L'Eco del Consiglio"])
        else:
            articoli_query = articoli_query.filter(categoria__iexact=categoria)
    
    # Ordina per data di pubblicazione
    articoli_list = articoli_query.order_by('-data_pubblicazione')

    # Paginazione: 10 articoli per pagina
    paginator = Paginator(articoli_list, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # LOGICA BANNER: 2 banner tra le card, mai contigui
    # Posizioni possibili: 1, 2, 3, 4 (tra gli articoli, mai prima o dopo)
    # Combina posizioni valide (non contigue)
    from admin_panel.models import Banner
    from admin_panel.templatetags.banner_tags import weighted_random_choice, reset_shown_users

    # Reset cache utenti mostrati per questa pagina
    reset_shown_users()

    # Con 12 posizioni (0-11): banner mai in pos 0 o 11, mai contigui
    valid_combinations = [
        [2, 6],   # Banner in pos 2 e 6
        [2, 7],   # Banner in pos 2 e 7
        [3, 7],   # Banner in pos 3 e 7
        [3, 8],   # Banner in pos 3 e 8
        [4, 8],   # Banner in pos 4 e 8
        [4, 9],   # Banner in pos 4 e 9
        [5, 9],   # Banner in pos 5 e 9
        [3, 9],   # Banner in pos 3 e 9
    ]
    banner_positions = random.choice(valid_combinations)

    # Ottieni tutti i banner attivi per la posizione 'between_articles'
    all_banners = list(Banner.objects.filter(
        position='between_articles',
        status='active',
        payment_status='completed',
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    ).select_related('user'))

    # Verifica che non sia un bot
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'wget', 'python-requests']
    is_bot = any(keyword in user_agent for keyword in bot_keywords)

    # Selezione randomica pesata dei 2 banner
    active_banners = []
    if all_banners:
        # Primo banner
        banner1 = weighted_random_choice(all_banners)
        if banner1:
            active_banners.append(banner1)
            # Incrementa impressions solo se non bot e non già mostrato in questa sessione
            session_key = f'banner_impression_{banner1.id}_{page_number}'
            if not is_bot and not request.session.get(session_key, False):
                banner1.impressions += 1
                banner1.save(update_fields=['impressions'])
                request.session[session_key] = True
                logger.debug(f"Impression unica banner: {banner1.title} (pag {page_number})")
            elif is_bot:
                logger.debug(f"Bot rilevato, impression non contata per banner: {banner1.title}")

        # Secondo banner (se ci sono abbastanza banner)
        if len(all_banners) >= 2:
            banner2 = weighted_random_choice(all_banners)
            if banner2:
                active_banners.append(banner2)
                # Incrementa impressions solo se non bot e non già mostrato in questa sessione
                session_key = f'banner_impression_{banner2.id}_{page_number}'
                if not is_bot and not request.session.get(session_key, False):
                    banner2.impressions += 1
                    banner2.save(update_fields=['impressions'])
                    request.session[session_key] = True
                    logger.debug(f"Impression unica banner: {banner2.title} (pag {page_number})")
                elif is_bot:
                    logger.debug(f"Bot rilevato, impression non contata per banner: {banner2.title}")
    
    # Log per debugging
    if categoria:
        logger.info(f"Caricati {len(page_obj)} articoli approvati categoria '{categoria}' (pagina {page_number})")
    else:
        logger.info(f"Caricati {len(page_obj)} articoli approvati per la home (pagina {page_number})")
    
    # Ottieni lista categorie disponibili per il menu (raggruppa Editoriale e L'Eco del Consiglio in Rubriche)
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
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
    # Posizioni 0-5: sempre 4 articoli + 2 slot banner
    grid_items = []
    article_index = 0
    banner_index = 0

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
                grid_items.append({
                    'type': 'article',
                    'data': page_obj[article_index]
                })
                article_index += 1

    context = {
        'articoli': page_obj,
        'grid_items': grid_items,  # Griglia con articoli e banner/placeholder
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

        articoli_data = []
        for articolo in page_obj:
            # Formatta data in italiano
            data_pub = articolo.data_pubblicazione
            data_italiana = f"{data_pub.day} {ITALIAN_MONTHS_SHORT[data_pub.month]} {data_pub.year}"

            articoli_data.append({
                'titolo': articolo.titolo,
                'sommario': articolo.sommario,
                'categoria': articolo.categoria,
                'data_pubblicazione': data_italiana,
                'slug': articolo.slug,
                'foto': articolo.get_image_url(),
            })
        
        return JsonResponse({
            'articoli': articoli_data,
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_prev': page_obj.has_previous(),
            'has_next': page_obj.has_next(),
            'categoria_attiva': categoria,
            'banner_positions': banner_positions,
            'num_banner_slots': num_banner_slots,
        })
    
    return render(request, "homepage.html", context)

def dettaglio_articolo(request, slug):
    articolo = get_object_or_404(Articolo, slug=slug, approvato=True)

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
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False
    
    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)
    
    # Articoli correlati: ultimi 6 della stessa categoria (escluso quello corrente)
    articoli_correlati = Articolo.objects.filter(
        approvato=True,
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
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
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

    template = loader.get_template('sitemap_index.xml')
    context = {
        'now': now,
        'has_archive': has_archive,
        'archive_lastmod': archive_lastmod
    }
    return HttpResponse(template.render(context, request), content_type='application/xml')

def sitemap(request):
    """Vista per la sitemap principale (ultimi 30 giorni)"""
    now = timezone.now()
    cutoff_date = now - timedelta(days=30)

    # Articoli ultimi 30 giorni
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_date
    ).order_by('-data_pubblicazione')

    # Aggiungi campo days_old per priorità dinamiche
    for article in articles:
        article.days_old = (now - article.data_pubblicazione).days

    # Categorie disponibili
    categorie = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()

    # Data ultimo aggiornamento
    last_update = articles.first().data_pubblicazione if articles else now

    logger.info(f"Generata sitemap principale con {len(articles)} articoli (ultimi 30 giorni)")

    template = loader.get_template('sitemap.xml')
    context = {
        'articles': articles,
        'categorie': categorie,
        'last_update': last_update
    }
    return HttpResponse(template.render(context, request), content_type='application/xml')

def sitemap_archive(request):
    """Vista per la sitemap archivio (articoli più vecchi di 30 giorni)"""
    cutoff_date = timezone.now() - timedelta(days=30)

    # Articoli più vecchi di 30 giorni, limitati a 10.000 per performance
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__lt=cutoff_date
    ).order_by('-data_pubblicazione')[:10000]

    logger.info(f"Generata sitemap archivio con {len(articles)} articoli")

    template = loader.get_template('sitemap_archive.xml')
    context = {'articles': articles}
    return HttpResponse(template.render(context, request), content_type='application/xml')

def news_sitemap(request):
    """Vista per la sitemap Google News (ultimi 2 giorni)"""
    # Solo articoli approvati degli ultimi 2 giorni
    cutoff_date = timezone.now() - timedelta(days=2)
    articles = Articolo.objects.filter(
        approvato=True,
        data_pubblicazione__gte=cutoff_date
    ).exclude(
        titolo__istartswith='test'  # Escludi articoli di test
    ).exclude(
        categoria__in=['Editoriale', 'Cosa fare oggi']  # Google News preferisce notizie, non editoriali o agende
    ).order_by('-data_pubblicazione')

    logger.info(f"Generata sitemap news con {len(articles)} articoli")

    template = loader.get_template('sitemap_news.xml')
    context = {'articles': articles}
    return HttpResponse(template.render(context, request), content_type='application/xml')

def fonti_articolo(request, slug):
    """Vista per mostrare tutte le fonti di un articolo"""
    articolo = get_object_or_404(Articolo, slug=slug, approvato=True)

    logger.info(f"Visualizzazione fonti articolo: {articolo.titolo}")

    # Ottieni liste categorie per il menu di navigazione
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
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
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
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
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
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
    categorie_raw = Articolo.objects.filter(approvato=True).values_list('categoria', flat=True).distinct()
    categorie_disponibili = []
    has_rubriche = False

    for cat in sorted(categorie_raw):
        if cat in ['Editoriale', "L'Eco del Consiglio"]:
            if not has_rubriche:
                categorie_disponibili.append('Rubriche')
                has_rubriche = True
        else:
            categorie_disponibili.append(cat)

    # Paginazione: 10 articoli per pagina (come homepage)
    # Con 2 banner in posizioni fisse, avremo 12 elementi totali
    paginator = Paginator(articles, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Posizioni fisse dei banner (stesse della homepage)
    banner_positions = [3, 8]  # Banner in posizioni non contigue, mai prima/ultima

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
