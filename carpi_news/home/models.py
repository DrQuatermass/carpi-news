from django.db import models
from django.utils import timezone
from django.templatetags.static import static
from django.conf import settings
from django.utils.html import strip_tags
from urllib.parse import quote
import html
import re
import json
import logging
import uuid
import warnings
from datetime import timedelta
logger = logging.getLogger(__name__)


# Annunci di eventi: 30 giorni dopo la data dell'evento la pagina e' scaduta per chi cerca
# ("sabato c'e' la mostra" letto mesi dopo) e passa in noindex, fuori dalle sitemap.
EVENTO_SCADUTO_GIORNI = 30


def soglia_evento_scaduto():
    """Eventi con data_evento precedente a questa data sono scaduti."""
    return timezone.localdate() - timedelta(days=EVENTO_SCADUTO_GIORNI)


class Articolo(models.Model):
    HEADLINE_MAX_LENGTH = 95

    # Mappa categoria -> slug URL (deve restare allineata a views.CATEGORIA_MAP)
    CATEGORIA_SLUG_MAP = {
        'Attualità': 'attualita',
        'Cronaca': 'cronaca',
        'Sport': 'sport',
        'Cultura & Eventi': 'cultura-eventi',
        'Politica': 'politica',
        'Cosa fare oggi': 'cosa-fare-oggi',
        'Editoriale': 'editoriale',
        "L'Eco del Consiglio": 'eco-del-consiglio',
    }

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
    spunto_social = models.CharField(
        max_length=280, blank=True, default='',
        help_text="Domanda finale per il post Facebook (genera commenti). Generata dall'AI, modificabile prima dell'approvazione. Se vuota, il post resta come prima."
    )
    categoria = models.CharField(max_length=100, choices=CATEGORIA_CHOICES, default='Attualità', db_index=True)
    tags = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Tag separati da virgola. Es: "Carpi calcio, Serie D, Carpi FC"'
    )
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    approvato = models.BooleanField(default=False, db_index=True)
    fonte = models.URLField(max_length=500, blank=True, null=True)
    foto = models.TextField(blank=True, null=True)
    foto_upload = models.ImageField(upload_to='images/uploaded/', blank=True, null=True, help_text="Upload di un'immagine per l'articolo")
    foto_valida = models.BooleanField(
        default=True,
        help_text="False se la verifica dell'URL esterno in foto e' fallita (validata all'ingest, non al render)",
    )
    image_16x9 = models.ImageField(upload_to='images/articles/', max_length=180, blank=True, null=True, help_text="Versione WebP 1200x675 per social e NewsArticle")
    image_4x3 = models.ImageField(upload_to='images/articles/', max_length=180, blank=True, null=True, help_text="Versione WebP 1200x900 per NewsArticle")
    image_1x1 = models.ImageField(upload_to='images/articles/', max_length=180, blank=True, null=True, help_text="Versione WebP 1200x1200 per NewsArticle")
    richieste_modifica = models.TextField(blank=True, null=True, help_text="Richieste specifiche per la rigenerazione AI dell'articolo")
    fonti_web = models.JSONField(blank=True, null=True, help_text="Fonti web utilizzate durante la generazione AI con ricerca web")
    tfidf_terms = models.JSONField(blank=True, null=True, help_text="Vettore TF-IDF (termine->peso) per il gate di rilevanza del linking interno")
    ai_model_used = models.CharField(max_length=50, blank=True, null=True, help_text="Modello AI utilizzato per generare l'articolo (es. claude-3-7-sonnet, gpt-4-turbo)")
    monitor_origine = models.ForeignKey(
        'MonitorConfig',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articoli',
        help_text="Monitor che ha prodotto l'articolo: le sue regole AI si usano per la rielaborazione",
    )
    da_rielaborare = models.BooleanField(
        "Da rielaborare",
        default=False,
        db_index=True,
        help_text="Notizia grezza di un monitor con generazione AI spenta: va rielaborata con l'AI prima di poterla approvare",
    )
    views = models.PositiveIntegerField(default=0, help_text="Numero di visualizzazioni dell'articolo")
    spotlight = models.BooleanField(default=False, db_index=True, help_text="Articolo in evidenza nella sezione spotlight (max 4)")
    data_creazione = models.DateTimeField(auto_now_add=True, db_index=True)
    data_pubblicazione = models.DateTimeField(blank=True, null=True, default=timezone.now, db_index=True)
    data_modifica = models.DateTimeField(auto_now=True, db_index=True, help_text="Data ultima modifica dell'articolo")
    data_evento = models.DateField(blank=True, null=True, help_text="Data dell'evento per articoli di categoria Cultura ed Eventi")
    telegram_notified = models.BooleanField(default=False, db_index=True, help_text="Indica se l'articolo è stato notificato su Telegram")
    escludi_newsletter = models.BooleanField(default=False, help_text="Se selezionato, questo articolo non verrà incluso nella newsletter")

    # LUOGO (home/localizzazione.py): comune per il filtro, luogo e coordinate per la mappa
    LUOGO_ORIGINE_CHOICES = [
        ('testo', 'Parole chiave (solo comune)'),
        ('ai', 'Estratto con AI'),
        ('manuale', 'Inserito a mano'),
    ]
    comune = models.CharField(max_length=60, blank=True, db_index=True, help_text="Comune in cui avviene il fatto (es. Carpi, Soliera)")
    luogo_nome = models.CharField("Luogo", max_length=200, blank=True, help_text="Posto preciso, se c'è (es. Teatro Comunale, frazione di Fossoli)")
    luogo_indirizzo = models.CharField("Indirizzo", max_length=250, blank=True)
    lat = models.FloatField(blank=True, null=True)
    lng = models.FloatField(blank=True, null=True)
    luogo_preciso = models.BooleanField(default=False, help_text="Coordinate del posto preciso; se falso sono quelle del comune")
    luogo_origine = models.CharField(max_length=10, choices=LUOGO_ORIGINE_CHOICES, blank=True,
                                     help_text="Con 'Inserito a mano' la localizzazione automatica non lo tocca più")
    luogo_aggiornato = models.DateTimeField(blank=True, null=True, db_index=True)

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

    @property
    def seo_title(self):
        """Title tag per Google: titolo_seo se presente, altrimenti il titolo editoriale."""
        return (self.titolo_seo or '').strip() or self.editorial_headline

    @property
    def escluso_da_google(self):
        """noindex: "Cosa fare oggi" (riepiloga eventi gia' pubblicati), eventi scaduti
        (EVENTO_SCADUTO_GIORNI dopo la data) e articoli dei monitor segnati "Fuori dall'indice Google". Letto dal DB a ogni render, non dalla cache
        dell'articolo, cosi' il selettore in admin vale subito."""
        if self.categoria == 'Cosa fare oggi':
            return True
        if self.data_evento and self.data_evento < soglia_evento_scaduto():
            return True
        return bool(self.monitor_origine_id) and MonitorConfig.objects.filter(
            pk=self.monitor_origine_id, noindex=True).exists()

    @property
    def categoria_slug(self):
        """Slug della categoria per URL /categoria/<slug>/ (breadcrumb, link interni)."""
        return self.CATEGORIA_SLUG_MAP.get(self.categoria, 'attualita')

    @property
    def n_fonti(self):
        """Numero di fonti consultabili: fonte principale + fonti web non nascoste.
        Usato dal badge "Verificato su N fonti" nel dettaglio articolo."""
        count = 1 if self.fonte else 0
        if isinstance(self.fonti_web, list):
            count += sum(
                1 for f in self.fonti_web
                if isinstance(f, dict) and f.get('url') and f.get('hidden') is not True
            )
        return count

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
    def sommario_apertura(self):
        """Sommario da mostrare in grassetto sotto il titolo, oppure ''.
        Vuoto quando il sommario e' quello automatico di save() (inizio del testo
        troncato a 200 caratteri): ripeterebbe il primo paragrafo.
        Vuoto anche per "Cosa fare oggi", il cui sommario e' una frase fissa per i motori di ricerca."""
        if self.categoria == 'Cosa fare oggi':
            return ''
        sommario = html.unescape(strip_tags(self.sommario or '')).strip()
        # Graffe = CSS finito nel sommario automatico da un <style> nel testo
        if not sommario or '{' in sommario:
            return ''
        # Confronto senza spazi: save() toglie i tag senza lasciare spazi, il testo li sostituisce con spazi
        inizio = re.sub(r'\s+', '', sommario.rstrip('.… '))
        testi = (
            self.article_plain_text,
            # come save(): solo tag tolti, compreso il testo di eventuali <style>
            html.unescape(re.sub(r'<[^>]+>', '', self.contenuto or '')),
        )
        if inizio and any(re.sub(r'\s+', '', t).startswith(inizio) for t in testi):
            return ''
        return sommario

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
        urls = [
            self._absolute_media_field_url(self.image_16x9),
            self._absolute_media_field_url(self.image_4x3),
            self._absolute_media_field_url(self.image_1x1),
        ]
        urls = [url for url in urls if url]
        if len(urls) == 3:
            return urls
        return [self.get_social_image_url()]

    @staticmethod
    def _normalize_image_url(image_url):
        normalized_url = image_url

        if '://' in normalized_url:
            protocol, rest = normalized_url.split('://', 1)
            rest = re.sub(r'/+', '/', rest)
            normalized_url = f"{protocol}://{rest}"

        if ' ' in normalized_url:
            if normalized_url.startswith('http'):
                parts = normalized_url.split('/', 3)
                if len(parts) > 3:
                    encoded_path = quote(parts[3], safe='/')
                    normalized_url = f"{parts[0]}//{parts[2]}/{encoded_path}"
            else:
                normalized_url = quote(normalized_url, safe='/:?#[]@!$&\'()*+,;=')

        return normalized_url

    @property
    def seo_location(self):
        from .seo_locations import detect_municipality

        location = detect_municipality(self).copy()
        # Luogo salvato (localizza_articoli o inserito a mano): ha la precedenza sulle parole chiave
        if self.comune and self.lat is not None and self.lng is not None:
            from .localizzazione import comune_noto
            noto = comune_noto(self.comune) or {}
            location = {
                "name": self.luogo_nome or self.comune,
                "addressLocality": self.comune,
                "cap": noto.get("cap", ""),
                "lat": f"{self.lat:.4f}",
                "lng": f"{self.lng:.4f}",
            }
        location["region"] = "Emilia-Romagna"
        location["country"] = "IT"
        location["geo_position"] = f"{location['lat']};{location['lng']}"
        location["icbm"] = f"{location['lat']}, {location['lng']}"
        return location

    def get_image_url(self):
        if not hasattr(self, '_image_url_cache'):
            self._image_url_cache = self._build_image_url()
        return self._image_url_cache

    def _build_image_url(self):
        """Restituisce l'URL dell'immagine o il fallback se non disponibile."""
        fallback_image = static('home/images/portico_logo_nopayoff.webp')
        site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')

        if self.foto_upload:
            try:
                if self.foto_upload.name:
                    return f"{site_url}{self.foto_upload.url}"
            except (ValueError, AttributeError):
                if not self.foto:
                    return fallback_image

        if not self.foto:
            return fallback_image

        if self.foto.startswith('/media/') or self.foto.startswith('/static/'):
            return f"{site_url}{self.foto}"

        validated_url = self._normalize_image_url(self.foto)
        trusted_domains = ['voce.it', 'ombradelportico.it']
        if any(domain in validated_url for domain in trusted_domains):
            return validated_url

        return validated_url if self.foto_valida else fallback_image

    def get_social_image_url(self):
        if not hasattr(self, '_social_image_url_cache'):
            self._social_image_url_cache = self._build_social_image_url()
        return self._social_image_url_cache

    def _build_social_image_url(self):
        """Restituisce un URL immagine assoluto per la condivisione social."""
        site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
        fallback_image = f"{site_url}{static('home/images/portico_logo_nopayoff.png')}"

        if self.image_16x9:
            # Preferisci la variante JPEG gemella se presente su disco: Facebook,
            # WhatsApp e LinkedIn non renderizzano in modo affidabile og:image WebP.
            try:
                webp_name = self.image_16x9.name
            except (ValueError, AttributeError):
                webp_name = ''
            if webp_name.endswith('.webp'):
                import os
                jpeg_name = webp_name[:-5] + '.jpg'
                if os.path.exists(os.path.join(settings.MEDIA_ROOT, jpeg_name)):
                    return f"{site_url}{self.image_16x9.url[:-5]}.jpg"
            image_16x9_url = self._absolute_media_field_url(self.image_16x9)
            if image_16x9_url:
                return image_16x9_url

        if self.foto_upload:
            try:
                if self.foto_upload.name:
                    return f"{site_url}{self.foto_upload.url}"
            except (ValueError, AttributeError):
                if not self.foto:
                    return fallback_image

        if not self.foto:
            return fallback_image

        image_url = self.foto
        if image_url.endswith('.svg'):
            if image_url.startswith('/media/') or image_url.startswith('/static/'):
                image_url = image_url[:-4] + '.png'
            else:
                logger.warning(f"SVG esterno non supportato per social: {image_url}")
                return fallback_image

        if image_url.startswith('/media/') or image_url.startswith('/static/'):
            return f"{site_url}{image_url}"

        validated_url = self._normalize_image_url(image_url)
        trusted_domains = ['voce.it', 'ombradelportico.it']
        if any(domain in validated_url for domain in trusted_domains):
            return validated_url

        return validated_url if self.foto_valida else fallback_image

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
            models.Index(fields=['is_pubbliredazionale', 'approvato', 'payment_status'], name='idx_articolo_publi_pub'),
            models.Index(fields=['spotlight', '-data_pubblicazione'], name='idx_articolo_spotlight', condition=models.Q(spotlight=True)),
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
            models.Index(fields=['platform', 'success', 'published_at'], name='idx_socialpub_published'),
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
        ('albo_italsoft', 'Albo pretorio Italsoft'),
    ]

    # Campi base
    name = models.CharField(max_length=200, unique=True, help_text="Nome identificativo del monitor")
    base_url = models.URLField(max_length=500, blank=True, help_text="URL base del sito (opzionale per email)")
    scraper_type = models.CharField(max_length=20, choices=SCRAPER_TYPES, help_text="Tipo di scraper da utilizzare")
    category = models.CharField(max_length=100, default='Generale', help_text="Categoria degli articoli")

    # Stato e controllo
    is_active = models.BooleanField(default=True, help_text="Monitor attivo/disattivo")
    auto_approve = models.BooleanField(default=False, help_text="Approva automaticamente gli articoli")
    noindex = models.BooleanField(
        "Fuori dall'indice Google", default=False,
        help_text="Gli articoli di questo monitor restano sul sito ma con noindex e fuori dalle sitemap "
                  "(es. riscritture di altre testate). Vale anche per gli articoli gia' pubblicati.",
    )

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
            'monitor_config_id': self.pk,
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
        ('openrouter', 'OpenRouter'),
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
    origine = models.CharField(
        max_length=20, blank=True,
        help_text="Modulo da cui e' arrivata l'iscrizione: barra (telefono, in basso), barra_pc (computer, in basso a sinistra), fine_articolo, pagina",
    )
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


class GeocodeCache(models.Model):
    """Risposte di Nominatim (OpenStreetMap) gia' ottenute: i luoghi si ripetono molto
    (Teatro Comunale, Palazzo dei Pio...) e il servizio chiede al massimo una richiesta al secondo."""
    query = models.CharField(max_length=255, unique=True)
    lat = models.FloatField(blank=True, null=True)
    lng = models.FloatField(blank=True, null=True)
    display_name = models.CharField(max_length=500, blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Coordinate in cache'
        verbose_name_plural = 'Coordinate in cache'

    def __str__(self):
        return self.query


class ArticoloEliminato(models.Model):
    """Registro degli articoli cancellati (home/eliminazione.py).

    Serve a due cose: i monitor non reimportano una notizia la cui fonte e' qui (prima
    il controllo dei doppioni guardava solo gli articoli esistenti), e resta il conto
    di quanto si e' scartato, per mese e per monitor."""
    MOTIVO_CHOICES = [
        ('pulizia', 'Pulizia non approvati'),
        ('email', 'Tasto Elimina nella mail'),
        ('admin', 'Cancellato dall\'admin'),
    ]
    articolo_id = models.PositiveIntegerField(db_index=True)
    fonte = models.CharField(max_length=500, blank=True, db_index=True)
    titolo = models.CharField(max_length=200, blank=True)
    categoria = models.CharField(max_length=100, blank=True)
    monitor = models.CharField(max_length=100, blank=True, db_index=True)
    data_creazione = models.DateTimeField(blank=True, null=True)
    data_eliminazione = models.DateTimeField(auto_now_add=True, db_index=True)
    motivo = models.CharField(max_length=10, choices=MOTIVO_CHOICES, default='admin', db_index=True)

    class Meta:
        verbose_name = 'Articolo eliminato'
        verbose_name_plural = 'Articoli eliminati'
        ordering = ['-data_eliminazione']

    def __str__(self):
        return self.titolo or self.fonte


class GruppoFacebook(models.Model):
    """Gruppo Facebook in cui si condividono a mano gli articoli.

    Meta non permette piu' alle app di pubblicare nei gruppi (aprile 2024): la pagina
    admin "Condividi nei gruppi" prepara testo e link tracciato, la pubblicazione e' a mano.
    """
    nome = models.CharField(max_length=120)
    url = models.URLField("Link del gruppo", max_length=300)
    slug = models.SlugField(max_length=60, unique=True, blank=True,
                            help_text="Usato nel link tracciato (utm_medium); si crea dal nome")
    comune = models.CharField(max_length=60, blank=True,
                              help_text="Comune del gruppo (es. Carpi, Soliera). Vuoto = gruppo di tutta la zona")
    parole_chiave = models.CharField(max_length=200, blank=True,
                                     help_text="Frazioni o quartieri separati da virgola (es. Fossoli, Gargallo): "
                                               "gli articoli che li nominano vengono proposti per primi")
    come_pagina = models.BooleanField("Accetta la Pagina", default=True,
                                      help_text="Spunta se nel gruppo si posta come Pagina Ombra del Portico; "
                                                "altrimenti si posta dal profilo personale")
    note = models.TextField(blank=True, help_text="Regole del gruppo (es. niente link nel weekend, max 1 post al giorno)")
    attivo = models.BooleanField(default=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gruppo Facebook"
        verbose_name_plural = "Gruppi Facebook"
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.nome)[:50] or 'gruppo'
            slug, n = base, 2
            while GruppoFacebook.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def lista_parole(self):
        return [p.strip() for p in self.parole_chiave.split(',') if p.strip()]


class CondivisioneGruppo(models.Model):
    """Un articolo condiviso a mano in un gruppo Facebook."""
    gruppo = models.ForeignKey(GruppoFacebook, on_delete=models.CASCADE, related_name='condivisioni')
    articolo = models.ForeignKey(Articolo, on_delete=models.CASCADE, related_name='condivisioni_gruppi')
    data = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Condivisione in un gruppo"
        verbose_name_plural = "Condivisioni nei gruppi"
        unique_together = [('gruppo', 'articolo')]
        ordering = ['-data']

    def __str__(self):
        return f"{self.articolo.titolo[:50]} -> {self.gruppo.nome}"
