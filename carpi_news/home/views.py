import logging
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse
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
        articoli_data = []
        for articolo in page_obj:
            articoli_data.append({
                'titolo': articolo.titolo,
                'sommario': articolo.sommario,
                'categoria': articolo.categoria,
                'data_pubblicazione': articolo.data_pubblicazione.strftime('%d %b %Y'),
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
