from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed
from django.conf import settings
from .models import Articolo
from datetime import datetime


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
        """Aggiungi metadati extra al feed per forzare aggiornamenti"""
        from datetime import datetime
        return {
            'lastBuildDate': datetime.now(),
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
        """URL dell'immagine associata (se presente)"""
        if item.foto:
            # Se è già un URL assoluto
            if item.foto.startswith('http://') or item.foto.startswith('https://'):
                return item.foto
            # Se è un percorso locale
            elif item.foto.startswith('/media/'):
                return f"https://ombradelportico.it{item.foto}"
            else:
                return f"https://ombradelportico.it/media/{item.foto}"
        return None
    
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
        """Forza aggiornamento immediato per IFTTT"""
        from datetime import datetime
        return {
            'lastBuildDate': datetime.now(),
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
        if item.foto:
            if item.foto.startswith('http://') or item.foto.startswith('https://'):
                return item.foto
            elif item.foto.startswith('/media/'):
                return f"https://ombradelportico.it{item.foto}"
            else:
                return f"https://ombradelportico.it/media/{item.foto}"
        return None
    
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