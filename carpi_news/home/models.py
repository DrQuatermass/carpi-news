from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from django.templatetags.static import static
from django.core.cache import cache
import re
import requests

class Articolo(models.Model):
    titolo = models.CharField(max_length=200)
    contenuto = models.TextField()
    sommario = models.TextField(max_length=5000, blank=True)
    categoria = models.CharField(max_length=100, default='Generale')
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    approvato = models.BooleanField(default=False)
    fonte = models.URLField(blank=True, null=True)
    foto = models.URLField(blank=True, null=True)
    richieste_modifica = models.TextField(blank=True, null=True, help_text="Richieste specifiche per la rigenerazione AI dell'articolo")
    views = models.PositiveIntegerField(default=0, help_text="Numero di visualizzazioni dell'articolo")
    data_creazione = models.DateTimeField(auto_now_add=True)
    data_pubblicazione = models.DateTimeField(blank=True, null=True,default=timezone.now)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.titolo)
        if not self.sommario:
            # Rimuovi tag HTML dal contenuto per il sommario
            contenuto_pulito = re.sub(r'<[^>]+>', '', self.contenuto)
            # Pulisci spazi multipli e normalizza
            contenuto_pulito = re.sub(r'\s+', ' ', contenuto_pulito).strip()
            self.sommario = contenuto_pulito[:200] + '...' if len(contenuto_pulito) > 200 else contenuto_pulito
        super().save(*args, **kwargs)

    def get_image_url(self):
        """Restituisce l'URL dell'immagine o il fallback se non disponibile/raggiungibile"""
        fallback_image = static('home/images/portico_logo_nopayoff.svg')
        
        if not self.foto:
            return fallback_image
        
        # Controlla cache per URL già verificati
        cache_key = f"image_valid_{hash(self.foto)}"
        cached_result = cache.get(cache_key)
        
        if cached_result is not None:
            return self.foto if cached_result else fallback_image
        
        try:
            # Controlla se l'URL è raggiungibile
            response = requests.head(self.foto, timeout=3, allow_redirects=True)
            is_valid = response.status_code == 200
            
            # Cache il risultato per 1 ora
            cache.set(cache_key, is_valid, 3600)
            
            return self.foto if is_valid else fallback_image
        except:
            # Se c'è qualsiasi errore, cache fallimento e usa il fallback
            cache.set(cache_key, False, 1800)  # Cache errori per 30 min
            return fallback_image

    def __str__(self):
        return self.titolo
# Create your models here.
