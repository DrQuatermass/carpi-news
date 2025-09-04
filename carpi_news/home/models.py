from django.db import models
from django.utils.text import slugify
from django.utils import timezone
import re

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

    def __str__(self):
        return self.titolo
# Create your models here.
