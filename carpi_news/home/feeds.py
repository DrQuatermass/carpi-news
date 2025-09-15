from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed
from django.conf import settings
from django.core.cache import cache
from .models import Articolo
from datetime import datetime
import requests
import logging

logger = logging.getLogger(__name__)


def validate_image_url(url):
    """
    Valida se un URL immagine è accessibile
    
    Args:
        url: URL dell'immagine da validare
        
    Returns:
        bool: True se l'immagine è accessibile, False altrimenti
    """
    if not url:
        return False
    
    # Usa la cache per evitare troppe richieste HTTP
    cache_key = f"image_validation_{url}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    
    try:
        # Usa gli stessi header del monitor universale per evitare blocchi
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Usa HEAD request per non scaricare l'immagine completa
        response = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
        is_valid = response.status_code == 200
        
        # Se HEAD non funziona, prova con GET (alcuni server non supportano HEAD)
        if not is_valid:
            response = requests.get(url, timeout=10, stream=True, headers=headers)
            is_valid = response.status_code == 200
            
        # Cache il risultato per 1 ora
        cache.set(cache_key, is_valid, 3600)
        
        if not is_valid:
            logger.warning(f"Immagine non accessibile per RSS feed: {url} (status: {response.status_code})")
            
        return is_valid
        
    except requests.RequestException as e:
        logger.warning(f"Errore validazione immagine RSS: {url} - {str(e)}")
        # Cache il risultato negativo per 30 minuti (meno tempo per retry)
        cache.set(cache_key, False, 1800)
        return False


class ArticoliFeedRSS(Feed):
    """Feed RSS per gli articoli approvati - utilizzato per IFTTT"""
    
    title = "Ombra del Portico - Notizie di Carpi"
    link = "https://ombradelportico.it/"
    description = "Le ultime notizie della città di Carpi - Feed RSS per condivisione automatica sui social"
    
    # Configurazioni RSS - ottimizzate per aggiornamenti immediati
    feed_type = Rss201rev2Feed
    ttl = 1  # Time to live ridotto a 1 minuto per aggiornamenti rapidi
    
    def items(self):
        """Restituisce gli ultimi 10 articoli approvati"""
        return Articolo.objects.filter(
            approvato=True
        ).order_by('-data_pubblicazione')[:10]
    
    def feed_extra_kwargs(self, obj):
        """Aggiungi metadati extra al feed basati sull'ultimo articolo approvato"""
        # Usa la data dell'ultimo articolo approvato come lastBuildDate
        # invece di datetime.now() per evitare falsi aggiornamenti
        latest_article = Articolo.objects.filter(approvato=True).order_by('-data_pubblicazione').first()
        last_build = latest_article.data_pubblicazione if latest_article else datetime.now()
        
        return {
            'lastBuildDate': last_build,
            'generator': 'Ombra del Portico RSS Generator v2.0'
        }
    
    def item_title(self, item):
        return item.titolo
    
    def item_description(self, item):
        """Descrizione dell'articolo con sommario"""
        description = item.sommario[:300]
        if len(item.sommario) > 300:
            description += "..."
        return description
    
    def item_link(self, item):
        """Link diretto all'articolo"""
        return f"https://ombradelportico.it/articolo/{item.slug}/"
    
    def item_guid(self, item):
        """GUID univoco per ogni articolo"""
        return f"ombradelportico-{item.id}-{item.slug}"
    
    def item_pubdate(self, item):
        """Data di pubblicazione"""
        return item.data_pubblicazione
    
    def item_author_name(self, item):
        """Autore dell'articolo"""
        return "Ombra del Portico"
    
    def item_categories(self, item):
        """Categorie dell'articolo"""
        categories = [item.categoria] if item.categoria else []
        return categories
    
    def item_enclosure_url(self, item):
        """URL dell'immagine associata (solo se presente)"""
        if not item.foto:
            return None

        # Se l'immagine è il logo fallback, non includerla nel feed
        if 'portico_logo_nopayoff.png' in item.foto:
            return None

        # Costruisci URL assoluto
        if item.foto.startswith('http://') or item.foto.startswith('https://'):
            image_url = item.foto
        elif item.foto.startswith('/media/'):
            image_url = f"https://ombradelportico.it{item.foto}"
        elif not item.foto.startswith('/'):
            image_url = f"https://ombradelportico.it/media/{item.foto}"
        else:
            image_url = f"https://ombradelportico.it{item.foto}"

        # Restituisci l'URL dell'immagine senza validazione per evitare fallback a logo_nopayoff
        # La validazione può bloccare immagini valide di siti esterni
        return image_url
    
    def item_enclosure_length(self, item):
        """Lunghezza del file (richiesto per enclosure, usiamo 0 come placeholder)"""
        return "0"
    
    def item_enclosure_mime_type(self, item):
        """Tipo MIME dell'immagine"""
        if item.foto:
            if item.foto.lower().endswith('.jpg') or item.foto.lower().endswith('.jpeg'):
                return "image/jpeg"
            elif item.foto.lower().endswith('.png'):
                return "image/png"
            elif item.foto.lower().endswith('.gif'):
                return "image/gif"
            elif item.foto.lower().endswith('.webp'):
                return "image/webp"
        return "image/jpeg"  # Default


class ArticoliFeedAtom(Feed):
    """Feed Atom alternativo"""
    
    title = "Ombra del Portico - Notizie di Carpi"
    link = "https://ombradelportico.it/"
    description = "Le ultime notizie della città di Carpi - Feed Atom per condivisione automatica sui social"
    
    feed_type = 'atom'
    
    def items(self):
        return Articolo.objects.filter(
            approvato=True
        ).order_by('-data_pubblicazione')[:10]
    
    def item_title(self, item):
        return item.titolo
    
    def item_description(self, item):
        return item.sommario[:300] + ("..." if len(item.sommario) > 300 else "")
    
    def item_link(self, item):
        return f"https://ombradelportico.it/articolo/{item.slug}/"
    
    def item_pubdate(self, item):
        return item.data_pubblicazione


class ArticoliRecentiFeed(Feed):
    """Feed RSS solo per gli articoli delle ultime 24 ore (utile per IFTTT)"""
    
    title = "Ombra del Portico - Ultime 24 ore"
    link = "https://ombradelportico.it/"
    description = "Articoli pubblicati nelle ultime 24 ore - Feed ottimizzato per IFTTT"
    
    # Ottimizzazioni per IFTTT
    ttl = 1  # Aggiornamento ogni minuto
    
    def items(self):
        from datetime import datetime, timedelta
        ieri = datetime.now() - timedelta(days=1)
        
        return Articolo.objects.filter(
            approvato=True,
            data_pubblicazione__gte=ieri
        ).order_by('-data_pubblicazione')
    
    def feed_extra_kwargs(self, obj):
        """Forza aggiornamento solo quando ci sono nuovi articoli nelle ultime 24 ore"""
        from datetime import datetime, timedelta
        ieri = datetime.now() - timedelta(days=1)
        
        # Usa la data dell'ultimo articolo nelle ultime 24 ore
        latest_article = Articolo.objects.filter(
            approvato=True,
            data_pubblicazione__gte=ieri
        ).order_by('-data_pubblicazione').first()
        
        last_build = latest_article.data_pubblicazione if latest_article else datetime.now() - timedelta(days=2)
        
        return {
            'lastBuildDate': last_build,
            'generator': 'Ombra del Portico IFTTT Feed v2.0'
        }
    
    def item_title(self, item):
        # Aggiungi emoji per categoria per migliorare la condivisione social
        emoji = "📰"
        if item.categoria:
            if "sport" in item.categoria.lower() or "calcio" in item.categoria.lower():
                emoji = "⚽"
            elif "cultura" in item.categoria.lower() or "evento" in item.categoria.lower():
                emoji = "🎭"
            elif "politica" in item.categoria.lower() or "amministrazione" in item.categoria.lower():
                emoji = "🏛️"
            elif "economia" in item.categoria.lower() or "lavoro" in item.categoria.lower():
                emoji = "💼"
        
        return f"{emoji} {item.titolo}"
    
    def item_description(self, item):
        # Descrizione ottimizzata per social con hashtag
        description = item.sommario[:250]
        if len(item.sommario) > 250:
            description += "..."
        
        hashtags = "\n\n#CarpiNews #OmbraDelPortico"
        if item.categoria:
            category_tag = f"#{item.categoria.replace(' ', '')}"
            hashtags = f"\n\n{category_tag} {hashtags.strip()}"
            
        return description + hashtags
    
    def item_link(self, item):
        return f"https://ombradelportico.it/articolo/{item.slug}/"
    
    def item_pubdate(self, item):
        return item.data_pubblicazione
    
    def item_enclosure_url(self, item):
        """URL dell'immagine per feed IFTTT (solo se presente e valida)"""
        if not item.foto:
            return None
        
        # Se l'immagine è il logo fallback, non includerla nel feed IFTTT
        if 'portico_logo_nopayoff.png' in item.foto:
            return None
        
        # Costruisci URL assoluto
        if item.foto.startswith('http://') or item.foto.startswith('https://'):
            image_url = item.foto
        elif item.foto.startswith('/media/'):
            image_url = f"https://ombradelportico.it{item.foto}"
        elif not item.foto.startswith('/'):
            image_url = f"https://ombradelportico.it/media/{item.foto}"
        else:
            image_url = f"https://ombradelportico.it{item.foto}"
        
        # Restituisci l'URL dell'immagine senza validazione per IFTTT
        # La validazione può bloccare immagini valide di siti esterni
        return image_url
    
    def item_enclosure_length(self, item):
        return "0"
    
    def item_enclosure_mime_type(self, item):
        if item.foto:
            if item.foto.lower().endswith(('.jpg', '.jpeg')):
                return "image/jpeg"
            elif item.foto.lower().endswith('.png'):
                return "image/png"
            elif item.foto.lower().endswith('.gif'):
                return "image/gif"
            elif item.foto.lower().endswith('.webp'):
                return "image/webp"
        return "image/jpeg"