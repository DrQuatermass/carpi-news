from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from django.templatetags.static import static
from django.core.cache import cache
from django.conf import settings
from urllib.parse import quote
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
    foto = models.TextField(blank=True, null=True)
    foto_upload = models.ImageField(upload_to='images/uploaded/', blank=True, null=True, help_text="Upload di un'immagine per l'articolo")
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
        fallback_image = static('home/images/portico_logo_nopayoff.png')

        # Priorità: foto_upload prima di foto URL
        if self.foto_upload:
            # Per le immagini caricate, aggiungi sempre il dominio completo per IFTTT
            site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
            return f"{site_url}{self.foto_upload.url}"

        if not self.foto:
            return fallback_image
        
        # Se l'immagine è locale (inizia con /media/ o /static/), aggiungi il dominio
        if self.foto.startswith('/media/') or self.foto.startswith('/static/'):
            # Usa SITE_URL dal .env, fallback a https://ombradelportico.it
            site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
            return f"{site_url}{self.foto}"
        
        # Fix per URL con spazi e doppi slash prima della validazione
        validated_url = self.foto

        # Fix per doppi slash negli URL (es. voce.it/upload//articolo)
        if '://' in validated_url:
            protocol, rest = validated_url.split('://', 1)
            # Rimuovi doppi slash nel path ma mantieni quelli dopo il protocollo
            rest = re.sub(r'/+', '/', rest)
            validated_url = f"{protocol}://{rest}"

        if ' ' in validated_url:
            # Codifica solo la parte del path, mantenendo lo schema e host
            if validated_url.startswith('http'):
                parts = validated_url.split('/', 3)  # ['http:', '', 'domain.com', 'path/with spaces.jpg']
                if len(parts) > 3:
                    # Codifica solo il path mantenendo il resto
                    encoded_path = quote(parts[3], safe='/')
                    validated_url = f"{parts[0]}//{parts[2]}/{encoded_path}"
            else:
                validated_url = quote(validated_url, safe='/:?#[]@!$&\'()*+,;=')
        
        # Per alcuni domini noti che hanno problemi di connessione, salta la validazione
        trusted_domains = ['voce.it', 'ombradelportico.it']
        if any(domain in validated_url for domain in trusted_domains):
            return validated_url
        
        # Per URL esterni, mantieni la validazione con cache
        cache_key = f"image_valid_{hash(validated_url)}"
        cached_result = cache.get(cache_key)
        
        if cached_result is not None:
            return validated_url if cached_result else fallback_image
        
        try:
            # Controlla se l'URL è raggiungibile
            response = requests.head(validated_url, timeout=3, allow_redirects=True)
            is_valid = response.status_code == 200
            
            # Cache il risultato per 1 ora
            cache.set(cache_key, is_valid, 3600)
            
            return validated_url if is_valid else fallback_image
        except:
            # Se c'è qualsiasi errore, cache fallimento e usa il fallback
            cache.set(cache_key, False, 1800)  # Cache errori per 30 min
            return fallback_image

    def __str__(self):
        return self.titolo
# Create your models here.
