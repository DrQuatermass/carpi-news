from django.db import models
from django.utils import timezone
from django.templatetags.static import static
from django.core.cache import cache
from django.conf import settings
from django.utils.html import strip_tags
from urllib.parse import quote
import html
import re
import requests
import json
import logging
import uuid
import warnings
logger = logging.getLogger(__name__)


class Articolo(models.Model):
    HEADLINE_MAX_LENGTH = 95

    CATEGORIA_CHOICES = [
        ('Attualità', 'Attualità'),
        ('Cronaca', 'Cronaca'),
        ('Cultura & Eventi', 'Cultura & Eventi'),
        ('Politica', 'Politica'),
        ('Sport', 'Sport'),
        ("L'Eco del Consiglio", "L'Eco del Consiglio"),
        ('Cosa fare oggi', 'Cosa fare oggi'),
        ('Editoriale', 'Editoriale'),
    ]

    titolo = models.CharField(max_length=200)
    titolo_seo = models.CharField(
        max_length=70,
        blank=True,
        default='',
        help_text=(
            'Title tag SEO per Google (max 60 char, keyword-first). '
            'Se vuoto usa il titolo principale.'
        )
    )
    contenuto = models.TextField()
    sommario = models.TextField(max_length=5000, blank=True)
    categoria = models.CharField(max_length=100, choices=CATEGORIA_CHOICES, default='Attualità', db_index=True)
    tags = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Tag separati da virgola. Es: "Carpi calcio, Serie D, Carpi FC"'
    )
    autore = models.CharField(
        max_length=120,
        default="Redazione Ombra del Portico",
        db_index=True,
        help_text=(
            "Autore dell'articolo. Default 'Redazione Ombra del Portico'. "
            "Usa nome persona reale per editoriali firmati o pubbliredazionali "
            "con firma dell'autore."
        )
    )
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    approvato = models.BooleanField(default=False, db_index=True)
    fonte = models.URLField(max_length=500, blank=True, null=True)
    foto = models.TextField(blank=True, null=True)
    foto_upload = models.ImageField(upload_to='images/uploaded/', blank=True, null=True, help_text="Upload di un'immagine per l'articolo")
    image_16x9 = models.ImageField(upload_to='images/articles/', max_length=180, blank=True, null=True, help_text="Versione WebP 1200x675 per social e NewsArticle")
    image_4x3 = models.ImageField(upload_to='images/articles/', max_length=180, blank=True, null=True, help_text="Versione WebP 1200x900 per NewsArticle")
    image_1x1 = models.ImageField(upload_to='images/articles/', max_length=180, blank=True, null=True, help_text="Versione WebP 1200x1200 per NewsArticle")
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
    escludi_newsletter = models.BooleanField(default=False, help_text="Se selezionato, questo articolo non verrà incluso nella newsletter")

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
    intervistato_ruolo = models.CharField('Ruolo in azienda', max_length=100, blank=True, help_text='Ruolo o carica dell\'intervistato in azienda (es: Titolare, Direttore)')

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
    total_price = models.DecimalField('Prezzo totale (€)', max_digits=10, decimal_places=2, default=200.00)

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

    # Note amministrative
    admin_notes = models.TextField('Note amministrative', blank=True, help_text='Visibili solo agli admin')

    @property
    def editorial_headline(self):
        """Fonte unica per H1, title social e headline NewsArticle."""
        return (self.titolo or '').strip()

    def _warn_if_headline_too_long(self):
        headline = self.editorial_headline
        if len(headline) <= self.HEADLINE_MAX_LENGTH:
            return

        message = (
            f"Headline oltre {self.HEADLINE_MAX_LENGTH} caratteri "
            f"({len(headline)}): slug={self.slug or '<senza-slug>'} titolo={headline!r}"
        )
        logger.warning(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    def clean(self):
        super().clean()
        self._warn_if_headline_too_long()

    @staticmethod
    def normalize_category(categoria):
        """
        Normalizza automaticamente le categorie legacy/varianti alle categorie fisse.
        Chiamato automaticamente nel save() per garantire coerenza.
        """
        if not categoria:
            return 'Attualità'

        # Mappa delle categorie legacy -> categoria fissa
        category_map = {
            # Legacy/varianti -> Nuova categoria
            'generale': 'Attualità',
            'comunicazioni': 'Attualità',
            'attualita': 'Attualità',
            'notizie': 'Attualità',
            'comunicati stampa': 'Attualità',
            'test': 'Attualità',

            'cronaca': 'Cronaca',
            'cronaca social': 'Cronaca',

            'cultura': 'Cultura & Eventi',
            'eventi': 'Cultura & Eventi',
            'cultura & eventi': 'Cultura & Eventi',
            'cultura ed eventi': 'Cultura & Eventi',
            'spettacoli': 'Cultura & Eventi',

            'politica': 'Politica',
            'amministrazione': 'Politica',

            'sport': 'Sport',
            'calcio': 'Sport',

            "l'eco del consiglio": "L'Eco del Consiglio",
            'eco del consiglio': "L'Eco del Consiglio",
            'consiglio comunale': "L'Eco del Consiglio",

            'cosa fare oggi': 'Cosa fare oggi',
            'cosa fare oggi?': 'Cosa fare oggi',

            'editoriale': 'Editoriale',
        }

        # Normalizza: lowercase e trim
        categoria_norm = categoria.strip().lower()

        # Se c'è un mapping, usalo
        if categoria_norm in category_map:
            return category_map[categoria_norm]

        # Altrimenti verifica se è già una categoria valida (case-insensitive)
        valid_categories = [cat[0] for cat in Articolo.CATEGORIA_CHOICES]
        for valid_cat in valid_categories:
            if categoria.strip().lower() == valid_cat.lower():
                return valid_cat

        # Fallback: Attualità
        logger.warning(f"Categoria sconosciuta '{categoria}' normalizzata a 'Attualità'")
        return 'Attualità'

    def save(self, *args, **kwargs):
        self._warn_if_headline_too_long()

        # Normalizza categoria prima del salvataggio
        self.categoria = self.normalize_category(self.categoria)

        if not self.slug:
            from .utils import is_slug_malformed, safe_slugify

            # Priorita': titolo_seo (gia' ottimizzato max 70 char) -> titolo.
            source = (self.titolo_seo or '').strip() or self.titolo
            base_slug = safe_slugify(source, max_length=75)

            bad, _reason = is_slug_malformed(base_slug)
            if bad and self.titolo_seo:
                base_slug = safe_slugify(self.titolo, max_length=75)

            slug = base_slug
            n = 1
            while Articolo.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                suffix = f"-{n}"
                slug = base_slug[:75 - len(suffix)] + suffix
                last_dash_before_suffix = slug[:-len(suffix)].rfind('-')
                if last_dash_before_suffix > 10:
                    slug = slug[:last_dash_before_suffix] + suffix

            self.slug = slug[:100]

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

    @property
    def tag_list(self):
        """Tag separati da virgola, ripuliti e deduplicati preservando l'ordine."""
        tags = [tag.strip() for tag in (self.tags or '').split(',') if tag.strip()]
        return list(dict.fromkeys(tags))

    @property
    def meta_keywords(self):
        keywords = self.tag_list or [self.categoria]
        keywords = keywords + [self.categoria, 'Carpi', 'Emilia-Romagna']
        return ', '.join(dict.fromkeys(keywords))

    @property
    def article_plain_text(self):
        text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', self.contenuto or '', flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = strip_tags(text)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    @property
    def article_word_count(self):
        return len(re.findall(r'\b[\wÀ-ÿ]+\b', self.article_plain_text))

    @property
    def has_shareable_image(self) -> bool:
        """True se l'articolo ha un'immagine per story/reel/IG (campo foto o upload)."""
        if self.foto_upload:
            try:
                return bool(self.foto_upload.name)
            except (ValueError, AttributeError):
                pass
        return bool(self.foto and str(self.foto).strip())

    @property
    def social_image_mime_type(self):
        image_url = self.get_social_image_url().split('?', 1)[0].lower()
        if image_url.endswith('.webp'):
            return 'image/webp'
        if image_url.endswith('.png'):
            return 'image/png'
        return 'image/jpeg'

    def _absolute_media_field_url(self, field):
        if not field:
            return ''
        try:
            if not field.name:
                return ''
            site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
            return f"{site_url}{field.url}"
        except (ValueError, AttributeError):
            return ''

    def get_newsarticle_image_urls(self):
        if self.pk:
            try:
                from .image_variants import ensure_article_image_variants, has_all_article_image_variants

                if not has_all_article_image_variants(self):
                    ensure_article_image_variants(self, force=True)
            except Exception as exc:
                logger.warning("Generazione lazy varianti NewsArticle fallita per articolo %s: %s", self.pk, exc)

        urls = [
            self._absolute_media_field_url(self.image_16x9),
            self._absolute_media_field_url(self.image_4x3),
            self._absolute_media_field_url(self.image_1x1),
        ]
        urls = [url for url in urls if url]
        if len(urls) == 3:
            return urls
        return [self.get_social_image_url()]

    @property
    def seo_location(self):
        from .seo_locations import detect_municipality

        location = detect_municipality(self).copy()
        location["region"] = "Emilia-Romagna"
        location["country"] = "IT"
        location["geo_position"] = f"{location['lat']};{location['lng']}"
        location["icbm"] = f"{location['lat']}, {location['lng']}"
        return location

    def get_image_url(self):
        """Restituisce l'URL dell'immagine o il fallback se non disponibile/raggiungibile"""
        fallback_image = static('home/images/portico_logo_nopayoff.webp')

        # Priorità: foto_upload prima di foto URL
        if self.foto_upload:
            # Verifica se il file esiste fisicamente
            import os
            from pathlib import Path

            file_path = Path(settings.MEDIA_ROOT) / str(self.foto_upload)
            if not file_path.exists():
                logger.warning(f"Immagine caricata non trovata: {self.foto_upload} (articolo: {self.titolo})")
                # Fallback sul campo foto se disponibile
                if self.foto:
                    # Continua con la logica del campo foto
                    pass
                else:
                    return fallback_image
            else:
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

        if self.pk:
            try:
                from .image_variants import ensure_article_image_variants, has_all_article_image_variants

                if not has_all_article_image_variants(self):
                    ensure_article_image_variants(self, force=True)
            except Exception as exc:
                logger.warning("Generazione lazy immagine social fallita per articolo %s: %s", self.pk, exc)

        if self.image_16x9:
            image_16x9_url = self._absolute_media_field_url(self.image_16x9)
            if image_16x9_url:
                return image_16x9_url

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
        """
        Verifica se il pubbliredazionale può procedere al pagamento.
        Richiede approvazione admin prima del pagamento.
        """
        return (
            self.is_pubbliredazionale and
            self.titolo and
            self.contenuto and
            self.interview_data and  # Intervista completata se ci sono dati
            self.approvato and  # DEVE essere approvato dall'admin
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


class ArticoloRedirect(models.Model):
    """Redirect 301 da vecchio slug articolo a nuovo slug."""
    old_slug = models.SlugField(max_length=100, unique=True, db_index=True)
    new_slug = models.SlugField(max_length=100, db_index=True)
    articolo = models.ForeignKey(
        'Articolo', on_delete=models.CASCADE, related_name='redirects'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(
        max_length=120, default='slug-malformato',
        help_text='Motivo del rename'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.old_slug} -> {self.new_slug}"


class SocialPublicationLog(models.Model):
    """Log delle pubblicazioni social per evitare duplicati"""
    PLATFORM_CHOICES = [
        ('telegram', 'Telegram'),
        ('facebook', 'Facebook'),
        ('facebook_reel', 'Facebook Reel'),       # legacy: mantenuto per dati storici
        ('facebook_story', 'Facebook Story'),
        ('instagram', 'Instagram'),
        ('instagram_story', 'Instagram Story'),
        ('instagram_reel', 'Instagram Reel'),
    ]

    articolo = models.ForeignKey(Articolo, on_delete=models.CASCADE, related_name='social_publications')
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, db_index=True)
    success = models.BooleanField(help_text="Pubblicazione riuscita")
    published_at = models.DateTimeField(auto_now_add=True)
    error_message = models.TextField(blank=True, null=True, help_text="Messaggio di errore se fallita")
    shared_url = models.URLField(max_length=500, blank=True, help_text="URL pubblicato effettivamente")
    short_link = models.ForeignKey(
        'ShortLink',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='social_publications',
    )
    instagram_media_id = models.CharField(max_length=100, blank=True, db_index=True)
    instagram_media_ids = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Log Pubblicazione Social"
        verbose_name_plural = "Log Pubblicazioni Social"
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['articolo', 'platform', 'success']),
            models.Index(fields=['platform', 'success', '-updated_at'], name='home_soc_plat_succ_upd_idx'),
        ]

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} {self.platform} - {self.articolo.titolo[:50]} ({self.published_at.strftime('%Y-%m-%d %H:%M')})"


class ShortLink(models.Model):
    """Short link tracciato per articolo/piattaforma/medium."""

    articolo = models.ForeignKey(Articolo, on_delete=models.CASCADE, related_name='short_links')
    platform = models.CharField(max_length=50, db_index=True)
    medium = models.CharField(max_length=50, db_index=True)
    token = models.CharField(max_length=12, unique=True, db_index=True)
    clicks_count = models.PositiveIntegerField(default=0)
    last_referer = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Short Link"
        verbose_name_plural = "Short Link"
        unique_together = [('articolo', 'platform', 'medium')]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['articolo', 'platform', 'medium']),
        ]

    def __str__(self):
        return f"/s/{self.token}/ - {self.articolo.titolo[:50]}"


class InstagramAutoDMLog(models.Model):
    TRIGGER_CHOICES = [
        ('story_reaction', 'Reazione Story'),
        ('story_reply', 'Risposta Story'),
        ('reel_comment', 'Commento Reel'),
    ]

    articolo = models.ForeignKey(Articolo, on_delete=models.SET_NULL, null=True, blank=True, related_name='instagram_dm_logs')
    ig_user_id = models.CharField(max_length=100, db_index=True)
    trigger_type = models.CharField(max_length=30, choices=TRIGGER_CHOICES)
    trigger_value = models.CharField(max_length=255, blank=True)
    media_id = models.CharField(max_length=100, blank=True, db_index=True)
    short_link = models.ForeignKey(ShortLink, on_delete=models.SET_NULL, null=True, blank=True, related_name='instagram_dm_logs')
    dm_sent = models.BooleanField(default=False)
    dm_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log Instagram Auto-DM"
        verbose_name_plural = "Log Instagram Auto-DM"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ig_user_id', '-created_at']),
            models.Index(fields=['media_id', '-created_at']),
        ]

    def __str__(self):
        return f"{self.ig_user_id} - {self.trigger_type} - {self.created_at:%Y-%m-%d %H:%M}"


class InstagramOptOut(models.Model):
    ig_user_id = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Opt-out Instagram"
        verbose_name_plural = "Opt-out Instagram"
        ordering = ['-created_at']

    def __str__(self):
        return self.ig_user_id


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
        ('openai', 'OpenAI'),
        ('google_search', 'Google Search'),
    ]

    # Identificazione
    api_type = models.CharField(max_length=20, choices=API_TYPES, help_text="Tipo di API utilizzata")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, help_text="Data e ora della chiamata")

    # Dettagli chiamata
    operation = models.CharField(max_length=100, help_text="Operazione eseguita (es. 'generate_article', 'polish_content')")
    model = models.CharField(max_length=100, blank=True, help_text="Modello utilizzato (es. 'claude-sonnet-4-6')")

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


# ---------------------------------------------------------------------------
# NEWSLETTER
# ---------------------------------------------------------------------------

class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    nome = models.CharField(max_length=100, blank=True)
    attivo = models.BooleanField(default=True)
    data_iscrizione = models.DateTimeField(auto_now_add=True)
    token_disiscrizione = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = 'Iscritto Newsletter'
        verbose_name_plural = 'Iscritti Newsletter'
        ordering = ['-data_iscrizione']


class NewsletterLog(models.Model):
    STATO_CHOICES = [
        ('success', 'Completato'),
        ('partial', 'Parziale'),
        ('failed', 'Fallito'),
        ('skipped', 'Saltato (nessun articolo)'),
    ]
    data_invio = models.DateTimeField(auto_now_add=True)
    oggetto = models.CharField(max_length=200)
    num_destinatari = models.IntegerField(default=0)
    num_articoli = models.IntegerField(default=0)
    stato = models.CharField(max_length=20, choices=STATO_CHOICES)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"Newsletter {self.data_invio:%d/%m/%Y} — {self.num_destinatari} destinatari"

    class Meta:
        verbose_name = 'Log Newsletter'
        verbose_name_plural = 'Log Newsletter'
        ordering = ['-data_invio']

# Create your models here.
