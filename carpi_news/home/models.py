from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from django.templatetags.static import static
from django.core.cache import cache
from django.conf import settings
from urllib.parse import quote
from django.db.models.signals import post_save
from django.dispatch import receiver
import re
import requests
import json
import logging
logger = logging.getLogger(__name__)


class Articolo(models.Model):
    titolo = models.CharField(max_length=200)
    contenuto = models.TextField()
    sommario = models.TextField(max_length=5000, blank=True)
    categoria = models.CharField(max_length=100, default='Generale', db_index=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    approvato = models.BooleanField(default=False, db_index=True)
    fonte = models.URLField(max_length=500, blank=True, null=True)
    foto = models.TextField(blank=True, null=True)
    foto_upload = models.ImageField(upload_to='images/uploaded/', blank=True, null=True, help_text="Upload di un'immagine per l'articolo")
    richieste_modifica = models.TextField(blank=True, null=True, help_text="Richieste specifiche per la rigenerazione AI dell'articolo")
    fonti_web = models.JSONField(blank=True, null=True, help_text="Fonti web utilizzate durante la generazione AI con ricerca web")
    ai_model_used = models.CharField(max_length=50, blank=True, null=True, help_text="Modello AI utilizzato per generare l'articolo (es. claude-3-7-sonnet, gpt-4-turbo)")
    views = models.PositiveIntegerField(default=0, help_text="Numero di visualizzazioni dell'articolo")
    spotlight = models.BooleanField(default=False, db_index=True, help_text="Articolo in evidenza nella sezione spotlight (max 4)")
    data_creazione = models.DateTimeField(auto_now_add=True, db_index=True)
    data_pubblicazione = models.DateTimeField(blank=True, null=True, default=timezone.now, db_index=True)
    data_modifica = models.DateTimeField(auto_now=True, db_index=True, help_text="Data ultima modifica dell'articolo")
    data_evento = models.DateField(blank=True, null=True, help_text="Data dell'evento per articoli di categoria Cultura ed Eventi")
    telegram_notified = models.BooleanField(default=False, db_index=True, help_text="Indica se l'articolo è stato notificato su Telegram")

    # CAMPI PUBBLIREDAZIONALE
    is_pubbliredazionale = models.BooleanField(default=False, help_text="È un articolo pubbliredazionale", db_index=True)

    # Utente che ha richiesto il pubbliredazionale
    pubbliredazionale_user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pubbliredazionali',
        verbose_name='Utente richiedente'
    )

    # Informazioni azienda
    nome_azienda = models.CharField('Nome azienda', max_length=200, blank=True, help_text='Nome dell\'azienda per il pubbliredazionale')
    sito_web = models.URLField('Sito web azienda', max_length=500, blank=True, help_text='URL del sito web dell\'azienda')
    intervistato_nome = models.CharField('Nome intervistato', max_length=100, blank=True, help_text='Nome della persona intervistata')
    intervistato_cognome = models.CharField('Cognome intervistato', max_length=100, blank=True, help_text='Cognome della persona intervistata')

    # Conversazione AI (salvata come JSON)
    interview_data = models.JSONField(
        'Dati intervista',
        default=dict,
        blank=True,
        help_text='Conversazione AI e informazioni raccolte'
    )

    # Pagamento (prezzo fisso €5)
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'In attesa'),
        ('saved', 'Salvato (senza pagamento)'),
        ('completed', 'Completato'),
        ('failed', 'Fallito'),
        ('refunded', 'Rimborsato'),
    ]

    payment_status = models.CharField('Stato pagamento', max_length=20, blank=True, choices=PAYMENT_STATUS_CHOICES, default='')
    payment_method = models.CharField('Metodo di pagamento', max_length=50, blank=True)
    payment_transaction_id = models.CharField('ID transazione', max_length=200, blank=True)
    payment_date = models.DateTimeField('Data pagamento', blank=True, null=True)
    total_price = models.DecimalField('Prezzo totale (€)', max_digits=10, decimal_places=2, default=150.00)

    # Codice promozionale
    promo_code = models.ForeignKey(
        'admin_panel.PromotionalCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pubbliredazionale_uses',
        verbose_name='Codice promozionale applicato'
    )
    discount_amount = models.DecimalField(
        'Sconto applicato (€)',
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Importo dello sconto applicato'
    )

    # Approvazione pubbliredazionale
    approved_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pubbliredazionali_approvati',
        verbose_name='Approvato da'
    )
    approved_at = models.DateTimeField('Approvato il', null=True, blank=True)
    admin_notes = models.TextField('Note amministrative', blank=True, help_text='Visibili solo agli admin')

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.titolo)
            slug = base_slug
            counter = 1

            # Se lo slug esiste già, aggiungi un suffisso numerico
            while Articolo.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        if not self.sommario:
            # Rimuovi tag HTML dal contenuto per il sommario
            contenuto_pulito = re.sub(r'<[^>]+>', '', self.contenuto)
            # Pulisci spazi multipli e normalizza
            contenuto_pulito = re.sub(r'\s+', ' ', contenuto_pulito).strip()
            self.sommario = contenuto_pulito[:200] + '...' if len(contenuto_pulito) > 200 else contenuto_pulito

        # Se è un pubbliredazionale approvato senza data di pubblicazione, impostala
        if self.is_pubbliredazionale and self.approvato and not self.data_pubblicazione:
            self.data_pubblicazione = timezone.now()

        super().save(*args, **kwargs)

    def get_image_url(self):
        """Restituisce l'URL dell'immagine o il fallback se non disponibile/raggiungibile"""
        fallback_image = static('home/images/portico_logo_nopayoff.webp')

        # Priorità: foto_upload prima di foto URL
        if self.foto_upload:
            # Per le immagini caricate, aggiungi sempre il dominio completo per IFTTT
            site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
            return f"{site_url}{self.foto_upload.url}"

        if not self.foto:
            return fallback_image

        # Se l'immagine è locale (inizia con /media/ o /static/), aggiungi il dominio
        if self.foto.startswith('/media/') or self.foto.startswith('/static/'):
            # Controlla se il file esiste fisicamente prima di restituirlo
            import os
            from pathlib import Path

            # Converti path relativo in assoluto
            if self.foto.startswith('/media/'):
                file_path = Path(settings.MEDIA_ROOT) / self.foto.replace('/media/', '')
            else:  # /static/
                file_path = Path(settings.BASE_DIR) / 'home' / 'static' / self.foto.replace('/static/', '')

            # Se il file non esiste, usa fallback
            if not file_path.exists():
                logger.warning(f"Immagine locale non trovata: {self.foto} (articolo: {self.titolo})")
                return fallback_image

            # File esiste, restituisci URL completo
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
            # Controlla se l'URL è raggiungibile (timeout ridotto a 1 sec per produzione)
            response = requests.head(validated_url, timeout=1, allow_redirects=True)
            is_valid = response.status_code == 200

            # Cache il risultato per 24 ore (riduce carico DB)
            cache.set(cache_key, is_valid, 86400)

            return validated_url if is_valid else fallback_image
        except:
            # Se c'è qualsiasi errore, usa fallback senza bloccare (assume valido)
            # Cache errori per 6 ore invece di 30min
            cache.set(cache_key, True, 21600)
            return validated_url  # Restituisci comunque l'URL, il browser gestirà errori

    def get_social_image_url(self):
        """
        Restituisce l'URL dell'immagine ottimizzato per la condivisione sui social.
        - Usa sempre PNG/JPG (no WebP) per massima compatibilità
        - Restituisce sempre URL assoluti con dominio completo
        - Fallback intelligente se l'immagine WebP non ha equivalente PNG/JPG
        """
        from pathlib import Path

        site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
        fallback_image = f"{site_url}{static('home/images/portico_logo_nopayoff.png')}"

        # Priorità: foto_upload prima di foto URL
        if self.foto_upload:
            return f"{site_url}{self.foto_upload.url}"

        if not self.foto:
            return fallback_image

        image_url = self.foto

        # Se l'immagine è SVG, usa la versione PNG (i social non supportano SVG)
        if image_url.endswith('.svg'):
            # Sostituisci .svg con .png
            png_url = image_url[:-4] + '.png'

            # Verifica che esista la versione PNG
            if png_url.startswith('/media/') or png_url.startswith('/static/'):
                if png_url.startswith('/media/'):
                    file_path = Path(settings.MEDIA_ROOT) / png_url.replace('/media/', '')
                else:
                    file_path = Path(settings.BASE_DIR) / 'home' / 'static' / png_url.replace('/static/', '')

                if file_path.exists():
                    logger.info(f"SVG convertito in PNG per social: {image_url} -> {png_url}")
                    image_url = png_url
                else:
                    logger.warning(f"Versione PNG non trovata per SVG: {image_url}, uso fallback")
                    return fallback_image
            else:
                # SVG esterno, usa fallback
                logger.warning(f"SVG esterno non supportato per social: {image_url}")
                return fallback_image

        # Se l'immagine è WebP, prova a trovare l'originale PNG/JPG
        if image_url.endswith('.webp'):
            # Prova tutti i possibili formati originali
            for ext in ['.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG']:
                original_url = image_url[:-5] + ext  # Rimuovi .webp e aggiungi estensione

                # Se è locale, controlla che esista
                if original_url.startswith('/media/') or original_url.startswith('/static/'):
                    if original_url.startswith('/media/'):
                        file_path = Path(settings.MEDIA_ROOT) / original_url.replace('/media/', '')
                    else:
                        file_path = Path(settings.BASE_DIR) / 'home' / 'static' / original_url.replace('/static/', '')

                    if file_path.exists():
                        image_url = original_url
                        break
            else:
                # Nessun originale trovato, usa l'immagine WebP comunque (alcuni social la supportano)
                logger.warning(f"Immagine originale non trovata per WebP: {self.foto} (articolo: {self.titolo})")

        # Gestisci URL locali
        if image_url.startswith('/media/') or image_url.startswith('/static/'):
            # Verifica che il file esista
            if image_url.startswith('/media/'):
                file_path = Path(settings.MEDIA_ROOT) / image_url.replace('/media/', '')
            else:
                file_path = Path(settings.BASE_DIR) / 'home' / 'static' / image_url.replace('/static/', '')

            if not file_path.exists():
                logger.warning(f"Immagine social non trovata: {image_url} (articolo: {self.titolo})")
                return fallback_image

            return f"{site_url}{image_url}"

        # Per URL esterni, assicurati che siano validi
        # Fix per URL con spazi e doppi slash
        validated_url = image_url

        if '://' in validated_url:
            protocol, rest = validated_url.split('://', 1)
            rest = re.sub(r'/+', '/', rest)
            validated_url = f"{protocol}://{rest}"

        if ' ' in validated_url:
            if validated_url.startswith('http'):
                parts = validated_url.split('/', 3)
                if len(parts) > 3:
                    encoded_path = quote(parts[3], safe='/')
                    validated_url = f"{parts[0]}//{parts[2]}/{encoded_path}"
            else:
                validated_url = quote(validated_url, safe='/:?#[]@!$&\'()*+,;=')

        # Per URL esterni, usa validazione con cache (come get_image_url)
        trusted_domains = ['voce.it', 'ombradelportico.it']
        if any(domain in validated_url for domain in trusted_domains):
            return validated_url

        cache_key = f"social_image_valid_{hash(validated_url)}"
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return validated_url if cached_result else fallback_image

        try:
            response = requests.head(validated_url, timeout=1, allow_redirects=True)
            is_valid = response.status_code == 200
            cache.set(cache_key, is_valid, 86400)
            return validated_url if is_valid else fallback_image
        except:
            cache.set(cache_key, True, 21600)
            return validated_url

    def can_proceed_to_payment(self):
        """Verifica se il pubbliredazionale può procedere al pagamento"""
        return (
            self.is_pubbliredazionale and
            self.titolo and
            self.contenuto and
            self.interview_data and  # Intervista completata se ci sono dati
            self.payment_status != 'completed'  # Non ancora pagato
        )

    def send_admin_notification(self):
        """Invia email di notifica all'amministratore per nuovo pubbliredazionale"""
        if not self.is_pubbliredazionale:
            return

        from django.core.mail import send_mail
        from django.contrib.auth.models import User

        try:
            admin_emails = User.objects.filter(is_superuser=True).values_list('email', flat=True)
            admin_emails = [email for email in admin_emails if email]

            if not admin_emails:
                return

            subject = f'🔔 Nuovo pubbliredazionale pagato: {self.nome_azienda}'
            message = f"""
Ciao,

Un nuovo pubbliredazionale è stato pagato e richiede approvazione.

Dettagli:
- Azienda: {self.nome_azienda}
- Sito web: {self.sito_web}
- Utente: {self.pubbliredazionale_user.username if self.pubbliredazionale_user else 'N/A'} ({self.pubbliredazionale_user.email if self.pubbliredazionale_user else 'N/A'})
- Categoria: {self.categoria}
- Pagamento: {self.get_payment_status_display() if self.payment_status else 'In attesa'}
- Approvato: {'Sì' if self.approvato else 'No - richiede approvazione'}

Vai al pannello di amministrazione:
{settings.SITE_URL}/admin/home/articolo/{self.pk}/change/

---
Ombra del Portico - Sistema pubbliredazionali
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                admin_emails,
                fail_silently=True,
            )
        except Exception as e:
            logger.error(f"Errore invio email notifica pubbliredazionale {self.pk}: {str(e)}")

    class Meta:
        indexes = [
            models.Index(fields=['approvato', '-data_pubblicazione']),  # Query homepage
            models.Index(fields=['categoria', 'approvato', '-data_pubblicazione']),  # Filtro categoria
            models.Index(fields=['slug']),  # Detail view (già unique, ma esplicito)
        ]
        verbose_name = "Articolo"
        verbose_name_plural = "Articoli"

    def __str__(self):
        if self.is_pubbliredazionale:
            return f"[PUBB] {self.nome_azienda} - {self.titolo}"
        return self.titolo


class SocialPublicationLog(models.Model):
    """Log delle pubblicazioni social per evitare duplicati"""
    PLATFORM_CHOICES = [
        ('telegram', 'Telegram'),
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
    ]

    articolo = models.ForeignKey(Articolo, on_delete=models.CASCADE, related_name='social_publications')
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, db_index=True)
    success = models.BooleanField(help_text="Pubblicazione riuscita")
    published_at = models.DateTimeField(auto_now_add=True)
    error_message = models.TextField(blank=True, null=True, help_text="Messaggio di errore se fallita")

    class Meta:
        verbose_name = "Log Pubblicazione Social"
        verbose_name_plural = "Log Pubblicazioni Social"
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['articolo', 'platform', 'success']),
        ]

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} {self.platform} - {self.articolo.titolo[:50]} ({self.published_at.strftime('%Y-%m-%d %H:%M')})"


class MonitorConfig(models.Model):
    """Configurazione per i monitor di notizie"""

    SCRAPER_TYPES = [
        ('html', 'HTML Scraping'),
        ('wordpress_api', 'WordPress API'),
        ('youtube_api', 'YouTube API'),
        ('graphql', 'GraphQL API'),
        ('email', 'Email IMAP'),
    ]

    # Campi base
    name = models.CharField(max_length=200, unique=True, help_text="Nome identificativo del monitor")
    base_url = models.URLField(max_length=500, blank=True, help_text="URL base del sito (opzionale per email)")
    scraper_type = models.CharField(max_length=20, choices=SCRAPER_TYPES, help_text="Tipo di scraper da utilizzare")
    category = models.CharField(max_length=100, default='Generale', help_text="Categoria degli articoli")

    # Stato e controllo
    is_active = models.BooleanField(default=True, help_text="Monitor attivo/disattivo")
    auto_approve = models.BooleanField(default=False, help_text="Approva automaticamente gli articoli")

    # Configurazioni specifiche (JSON)
    config_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Configurazioni specifiche del monitor (selectors, API keys, etc.)"
    )

    # AI Generation
    use_ai_generation = models.BooleanField(default=False, help_text="Usa generazione AI")
    enable_web_search = models.BooleanField(default=False, help_text="Abilita ricerca web durante generazione AI")
    ai_system_prompt = models.TextField(blank=True, help_text="System prompt per l'AI")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run = models.DateTimeField(null=True, blank=True, help_text="Ultima esecuzione del monitor")

    class Meta:
        verbose_name = "Configurazione Monitor"
        verbose_name_plural = "Configurazioni Monitor"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({'Attivo' if self.is_active else 'Disattivo'})"

    @property
    def config(self):
        """Alias per config_data per compatibilità con universal_news_monitor"""
        return self.config_data

    def to_site_config(self):
        """Converte il modello in SiteConfig per l'uso con universal_news_monitor"""
        from home.universal_news_monitor import SiteConfig
        from django.conf import settings

        # Prima aggiungi configurazioni specifiche dal JSON
        config_dict = self.config_data.copy() if self.config_data else {}

        # Rimuovi use_ai_generation e enable_web_search dal JSON se presenti
        # (saranno sovrascritti dai campi del modello che hanno precedenza)
        config_dict.pop('use_ai_generation', None)
        config_dict.pop('enable_web_search', None)

        # Poi aggiungi i valori specifici AI/auto-approve nel config_dict
        config_dict.update({
            'auto_approve': self.auto_approve,
            'use_ai_generation': self.use_ai_generation,
            'enable_web_search': self.enable_web_search,
            'ai_system_prompt': self.ai_system_prompt,
            'ai_api_key': settings.ANTHROPIC_API_KEY if self.use_ai_generation else None,
        })

        # Crea SiteConfig con parametri posizionali corretti
        return SiteConfig(
            name=self.name,
            base_url=self.base_url,
            scraper_type=self.scraper_type,
            category=self.category,
            **config_dict  # Resto della config va in kwargs
        )


class APIUsage(models.Model):
    """Traccia l'utilizzo e i costi delle API esterne (Anthropic, Google Search)"""

    API_TYPES = [
        ('anthropic', 'Anthropic Claude'),
        ('google_search', 'Google Search'),
    ]

    # Identificazione
    api_type = models.CharField(max_length=20, choices=API_TYPES, help_text="Tipo di API utilizzata")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, help_text="Data e ora della chiamata")

    # Dettagli chiamata
    operation = models.CharField(max_length=100, help_text="Operazione eseguita (es. 'generate_article', 'polish_content')")
    model = models.CharField(max_length=100, blank=True, help_text="Modello utilizzato (es. 'claude-sonnet-4-20250514')")

    # Token usage (per Anthropic)
    input_tokens = models.IntegerField(default=0, help_text="Token di input (prompt)")
    output_tokens = models.IntegerField(default=0, help_text="Token di output (risposta)")

    # Search usage (per Google)
    search_queries = models.IntegerField(default=0, help_text="Numero di query di ricerca")

    # Costi (in USD)
    input_cost = models.DecimalField(max_digits=10, decimal_places=6, default=0, help_text="Costo input in USD")
    output_cost = models.DecimalField(max_digits=10, decimal_places=6, default=0, help_text="Costo output in USD")
    cost_total = models.DecimalField(max_digits=10, decimal_places=6, default=0, help_text="Costo totale in USD", db_column='total_cost')

    # Metadata
    success = models.BooleanField(default=True, help_text="Chiamata riuscita")
    error_message = models.TextField(blank=True, help_text="Messaggio di errore se fallita")
    related_article = models.ForeignKey(Articolo, null=True, blank=True, on_delete=models.SET_NULL, help_text="Articolo correlato")

    class Meta:
        verbose_name = "Utilizzo API"
        verbose_name_plural = "Utilizzo API"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'api_type']),
            models.Index(fields=['api_type', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.get_api_type_display()} - {self.operation} - {self.timestamp.strftime('%Y-%m-%d %H:%M')} - ${self.cost_total}"

    def save(self, *args, **kwargs):
        """Calcola automaticamente il costo totale se non specificato"""
        if self.cost_total == 0:
            self.cost_total = self.input_cost + self.output_cost
        super().save(*args, **kwargs)


class ChatbotConversation(models.Model):
    """Traccia le conversazioni del chatbot per analisi e debugging"""

    # Identificazione sessione
    session_id = models.CharField(max_length=100, db_index=True, help_text="ID univoco della sessione chat")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, help_text="Data e ora del messaggio")

    # Contenuto conversazione
    user_message = models.TextField(help_text="Messaggio dell'utente")
    bot_response = models.TextField(help_text="Risposta del bot")

    # Intent analizzato
    intent_data = models.JSONField(default=dict, help_text="Dati intent estratti (keywords, timeframe, ecc.)")

    # Risultati
    articles_found = models.IntegerField(default=0, help_text="Numero di articoli trovati")
    articles_ids = models.JSONField(default=list, help_text="IDs degli articoli restituiti")

    # Metadata
    user_ip = models.GenericIPAddressField(null=True, blank=True, help_text="IP dell'utente")
    user_agent = models.TextField(blank=True, help_text="User agent del browser")

    # Performance
    response_time_ms = models.IntegerField(null=True, blank=True, help_text="Tempo di risposta in millisecondi")

    class Meta:
        verbose_name = "Conversazione Chatbot"
        verbose_name_plural = "Conversazioni Chatbot"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['session_id', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M')} - {self.user_message[:50]}..."


# WebSub Notification Signal
@receiver(post_save, sender=Articolo)
def notify_websub_on_approval(sender, instance, created, **kwargs):
    """
    Invia notifica WebSub a Google quando un articolo viene approvato

    NOTA: Invia SOLO notifiche push, non modifica il feed RSS.
    Invia notifica per ogni articolo approvato (sia nuovi che aggiornati).
    """
    # Invia notifica solo se l'articolo è approvato
    if instance.approvato:
        # Importa la funzione WebSub e invia notifica in modo asincrono
        try:
            from home.websub import notify_google_websub
            import threading

            # Esegui in thread separato per non bloccare il salvataggio
            thread = threading.Thread(target=notify_google_websub)
            thread.daemon = True
            thread.start()

            logger.info(f"WebSub: avviata notifica per articolo '{instance.titolo}'")
        except Exception as e:
            logger.error(f"WebSub: errore nell'avvio notifica per articolo '{instance.titolo}': {str(e)}")


# Create your models here.
