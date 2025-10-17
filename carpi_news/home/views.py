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
from datetime import datetime, timedelta
from .models import Articolo


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
    
    # Paginazione: 6 articoli per pagina
    paginator = Paginator(articoli_list, 6)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
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
    
    context = {
        'articoli': page_obj,
        'current_page': page_obj.number,
        'total_pages': paginator.num_pages,
        'has_prev': page_obj.has_previous(),
        'has_next': page_obj.has_next(),
        'categoria_attiva': categoria,
        'categorie_disponibili': list(categorie_disponibili),
        'current_year': 2025,
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
        })
    
    return render(request, "homepage.html", context)

def dettaglio_articolo(request, slug):
    articolo = get_object_or_404(Articolo, slug=slug, approvato=True)
    
    # Incrementa il contatore delle views
    from django.db.models import F
    Articolo.objects.filter(pk=articolo.pk).update(views=F('views') + 1)
    
    # Ricarica l'oggetto per avere il valore aggiornato
    articolo.refresh_from_db()
    
    logger.info(f"Visualizzazione dettaglio articolo: {articolo.titolo} (views: {articolo.views})")
    
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
