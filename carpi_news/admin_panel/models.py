from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError


class Banner(models.Model):
    """Modello per i banner pubblicitari"""

    HORIZONTAL_BANNER_SIZE = (728, 270)
    VERTICAL_BANNER_SIZE = (300, 600)
    ASPECT_RATIO_TOLERANCE = 0.08
    # Compatibilita con la validazione legacy nei signals.
    SIZE_TOLERANCE = ASPECT_RATIO_TOLERANCE

    POSITION_CHOICES = [
        ('both', 'Campagna completa (orizzontale + verticale) — header + tra gli articoli'),
        ('header', 'Solo orizzontale (728×270) — header su tutte le pagine'),
        ('between_articles', 'Solo verticale (300×600) — tra gli articoli in homepage'),
    ]

    RECOMMENDED_SIZES = {
        'header': HORIZONTAL_BANNER_SIZE,
        'between_articles': VERTICAL_BANNER_SIZE,
        'both': HORIZONTAL_BANNER_SIZE,
    }
    STATUS_CHOICES = [
        ('draft', 'Bozza'),
        ('pending_approval', 'In attesa di approvazione'),
        ('pending_payment', 'In attesa di pagamento'),
        ('active', 'Attivo'),
        ('paused', 'In pausa'),
        ('expired', 'Scaduto'),
        ('rejected', 'Rifiutato'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'In attesa'),
        ('saved', 'Salvato (senza pagamento)'),
        ('completed', 'Completato'),
        ('failed', 'Fallito'),
        ('refunded', 'Rimborsato'),
    ]

    # Relazione con utente
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='banners', verbose_name='Utente')

    # Informazioni banner
    title = models.CharField('Titolo', max_length=200, help_text='Nome identificativo del banner')
    image = models.ImageField('Banner orizzontale (728×270)', upload_to='banners/', blank=True, null=True, help_text='Leaderboard orizzontale — header su tutte le pagine (sarà convertita in WebP)')
    image_vertical = models.ImageField('Banner verticale (300×600)', upload_to='banners/', blank=True, null=True, help_text='Card verticale — tra gli articoli in homepage (sarà convertita in WebP)')
    link_url = models.URLField('URL di destinazione', help_text='Dove viene reindirizzato chi clicca sul banner')
    alt_text = models.CharField('Testo alternativo', max_length=200, help_text='Descrizione per accessibilità')

    # Posizionamento e durata
    position = models.CharField('Posizione', max_length=50, choices=POSITION_CHOICES)
    priority = models.IntegerField('Priorità', default=3, validators=[MinValueValidator(1)],
                                   help_text='Priorità di visualizzazione (1=massima, 5=minima)')

    # Date e durata
    start_date = models.DateTimeField('Data inizio', default=timezone.now)
    end_date = models.DateTimeField('Data fine')
    duration_days = models.IntegerField('Durata (giorni)', validators=[MinValueValidator(1)])

    # Pricing
    price_per_day = models.DecimalField('Prezzo al giorno (€)', max_digits=10, decimal_places=2,
                                        validators=[MinValueValidator(0)], default=1.70)
    total_price = models.DecimalField('Prezzo totale (€)', max_digits=10, decimal_places=2,
                                      validators=[MinValueValidator(0)], editable=False)

    # Stato e pagamento
    status = models.CharField('Stato', max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_status = models.CharField('Stato pagamento', max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField('Metodo di pagamento', max_length=50, blank=True, null=True)
    payment_transaction_id = models.CharField('ID transazione', max_length=200, blank=True, null=True)
    payment_date = models.DateTimeField('Data pagamento', blank=True, null=True)

    # Codice promozionale
    promo_code = models.ForeignKey(
        'PromotionalCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='banner_uses',
        verbose_name='Codice promozionale applicato'
    )
    discount_amount = models.DecimalField(
        'Sconto applicato (€)',
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Importo dello sconto applicato'
    )

    # Statistiche
    impressions = models.PositiveIntegerField('Visualizzazioni', default=0)
    clicks = models.PositiveIntegerField('Click', default=0)

    # Timestamp
    created_at = models.DateTimeField('Creato il', auto_now_add=True)
    updated_at = models.DateTimeField('Aggiornato il', auto_now=True)

    # Note amministrative
    admin_notes = models.TextField('Note amministrative', blank=True, help_text='Visibili solo agli admin')

    # Approvazione
    approved = models.BooleanField('Approvato', default=False, help_text='Il banner deve essere approvato da un amministratore prima di poter essere attivato')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_banners', verbose_name='Approvato da')
    approved_at = models.DateTimeField('Approvato il', null=True, blank=True)

    class Meta:
        verbose_name = 'Banner'
        verbose_name_plural = 'Banner'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.get_position_display()}"

    def save(self, *args, **kwargs):
        # Verifica se è un nuovo banner o se le immagini sono cambiate
        is_new = self.pk is None
        image_changed = False
        image_vertical_changed = False

        if not is_new:
            try:
                old_instance = Banner.objects.get(pk=self.pk)
                image_changed = old_instance.image != self.image
                image_vertical_changed = old_instance.image_vertical != self.image_vertical
            except Banner.DoesNotExist:
                pass

        # Calcola il prezzo totale automaticamente
        if self.duration_days and self.price_per_day:
            self.total_price = self.duration_days * self.price_per_day

        # Calcola end_date SOLO se non è già impostata
        if not self.end_date and self.start_date and self.duration_days:
            from datetime import timedelta
            self.end_date = self.start_date + timedelta(days=self.duration_days)

        # Imposta lo stato a 'pending_payment' per i nuovi banner (se non specificato)
        if is_new and self.status == 'draft':
            self.status = 'pending_payment'

        # Ottimizza immagini se nuove o cambiate
        if (is_new or image_changed) and self.image:
            self._optimize_image(field='image', target_size=self.HORIZONTAL_BANNER_SIZE)
        if (is_new or image_vertical_changed) and self.image_vertical:
            self._optimize_image(field='image_vertical', target_size=self.VERTICAL_BANNER_SIZE)

        super().save(*args, **kwargs)

        # Email verrà inviata dopo il pagamento, non alla creazione

    def _optimize_image(self, field='image', target_size=None):
        """Ottimizza automaticamente l'immagine banner in WebP"""
        try:
            from PIL import Image
            from django.core.files.base import ContentFile
            import io
            import os

            if target_size is None:
                target_size = self.HORIZONTAL_BANNER_SIZE

            image_field = getattr(self, field)
            img = Image.open(image_field)
            img.load()  # Carica i dati immagine prima che il file venga chiuso

            target_width, target_height = target_size
            expected_ratio = target_width / target_height
            actual_ratio = img.width / img.height if img.height else 0
            ratio_delta = abs(actual_ratio - expected_ratio) / expected_ratio

            if ratio_delta > self.ASPECT_RATIO_TOLERANCE:
                field_label = 'orizzontale' if field == 'image' else 'verticale'
                raise ValidationError(
                    f"Banner {field_label} non valido: dimensioni {img.width}x{img.height}. "
                    f"Usa proporzioni {target_width}x{target_height}; sono accettate "
                    f"dimensioni equivalenti, ad esempio 600x222 per l'orizzontale."
                )

            # Converti sempre in RGB (i banner non usano trasparenza)
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img.convert('RGB'), mask=img.split()[-1])
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Ridimensiona solo se necessario (troppo grande), senza fare upscale.
            if img.width > target_width:
                ratio = target_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

            # Salva come WebP ottimizzato
            output = io.BytesIO()
            img.save(output, format='WEBP', quality=70, method=6)
            output.seek(0)

            original_name = os.path.splitext(os.path.basename(image_field.name))[0]
            webp_name = f"{original_name}.webp"
            image_field.save(webp_name, ContentFile(output.read()), save=False)

        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Errore ottimizzazione immagine banner {self.pk}: {str(e)}")
            # Non bloccare il salvataggio se l'ottimizzazione fallisce

    def send_admin_notification(self):
        """Invia email di notifica all'amministratore per nuovo banner"""
        from django.core.mail import send_mail
        from django.conf import settings
        from django.contrib.auth.models import User

        try:
            # Ottieni gli amministratori
            admin_emails = User.objects.filter(is_superuser=True).values_list('email', flat=True)
            admin_emails = [email for email in admin_emails if email]  # Filtra email vuote

            if not admin_emails:
                return

            subject = f'🔔 Nuovo banner da approvare: {self.title}'
            message = f"""
Ciao,

Un nuovo banner è stato creato e richiede la tua approvazione.

Dettagli del banner:
- Titolo: {self.title}
- Utente: {self.user.username} ({self.user.email})
- Posizione: {self.get_position_display()}
- Durata: {self.duration_days} giorni
- Prezzo totale: €{self.total_price}
- Data inizio: {self.start_date.strftime('%d/%m/%Y')}
- Data fine: {self.end_date.strftime('%d/%m/%Y')}
- Stato: {self.get_status_display()}

Vai al pannello di amministrazione per approvare o rifiutare questo banner:
{settings.SITE_URL}/admin/admin_panel/banner/{self.pk}/change/

---
Ombra del Portico - Sistema di gestione banner
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                admin_emails,
                fail_silently=True,
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Errore nell'invio email notifica banner {self.pk}: {str(e)}")

    def is_active(self):
        """Verifica se il banner è attualmente attivo"""
        now = timezone.now()
        return (
            self.status == 'active' and
            self.payment_status == 'completed' and
            self.start_date <= now <= self.end_date
        )

    def is_expired(self):
        """Verifica se il banner è scaduto"""
        return timezone.now() > self.end_date

    @property
    def ctr(self):
        """Calcola il Click-Through Rate (CTR)"""
        if self.impressions > 0:
            return (self.clicks / self.impressions) * 100
        return 0

    @property
    def days_remaining(self):
        """Calcola i giorni rimanenti"""
        if self.is_expired():
            return 0
        delta = self.end_date - timezone.now()
        return max(0, delta.days)

    @classmethod
    def get_recommended_size(cls, position):
        """Restituisce le dimensioni consigliate per una posizione"""
        return cls.RECOMMENDED_SIZES.get(position, (728, 90))

    def get_recommended_size_text(self):
        """Restituisce il testo con le dimensioni consigliate per la posizione del banner"""
        if self.position:
            width, height = self.get_recommended_size(self.position)
            return f"{width}x{height} pixel"
        return "Seleziona prima una posizione"


class PromotionalCode(models.Model):
    """Modello per codici promozionali/sconto"""

    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentuale (%)'),
        ('fixed', 'Importo fisso (€)'),
        ('free_banner', 'Banner gratuito'),
        ('free_pubbliredazionale', 'Pubbliredazionale gratuito'),
    ]

    APPLIES_TO_CHOICES = [
        ('banner', 'Solo Banner'),
        ('pubbliredazionale', 'Solo Pubbliredazionali'),
        ('both', 'Entrambi'),
    ]

    # Codice promozionale
    code = models.CharField(
        'Codice',
        max_length=50,
        unique=True,
        help_text='Codice univoco (es: ESTATE2024, PROMO50)'
    )

    # Descrizione
    description = models.CharField(
        'Descrizione',
        max_length=200,
        help_text='Descrizione interna del codice'
    )

    # Tipo sconto
    discount_type = models.CharField(
        'Tipo sconto',
        max_length=30,
        choices=DISCOUNT_TYPE_CHOICES,
        default='percentage'
    )

    # Valore sconto
    discount_value = models.DecimalField(
        'Valore sconto',
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text='Percentuale (0-100) o importo fisso in €'
    )

    # A cosa si applica
    applies_to = models.CharField(
        'Si applica a',
        max_length=20,
        choices=APPLIES_TO_CHOICES,
        default='both'
    )

    # Validità
    valid_from = models.DateTimeField(
        'Valido da',
        default=timezone.now
    )

    valid_until = models.DateTimeField(
        'Valido fino a',
        null=True,
        blank=True,
        help_text='Lascia vuoto per nessuna scadenza'
    )

    # Limiti utilizzo
    max_uses = models.PositiveIntegerField(
        'Utilizzi massimi',
        null=True,
        blank=True,
        help_text='Numero massimo di volte che può essere usato (lascia vuoto per illimitato)'
    )

    current_uses = models.PositiveIntegerField(
        'Utilizzi correnti',
        default=0,
        editable=False
    )

    # Importo minimo
    min_amount = models.DecimalField(
        'Importo minimo',
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text='Importo minimo per applicare lo sconto (0 = nessun minimo)'
    )

    # Stato
    is_active = models.BooleanField(
        'Attivo',
        default=True,
        help_text='Il codice può essere utilizzato'
    )

    # Metadati
    created_at = models.DateTimeField('Creato il', auto_now_add=True)
    updated_at = models.DateTimeField('Aggiornato il', auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_promo_codes',
        verbose_name='Creato da'
    )

    class Meta:
        verbose_name = 'Codice Promozionale'
        verbose_name_plural = 'Codici Promozionali'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} - {self.get_discount_display()}"

    def get_discount_display(self):
        """Restituisce la descrizione dello sconto"""
        if self.discount_type == 'percentage':
            return f"{self.discount_value}% di sconto"
        elif self.discount_type == 'fixed':
            return f"€{self.discount_value} di sconto"
        elif self.discount_type == 'free_banner':
            return "Banner gratuito"
        elif self.discount_type == 'free_pubbliredazionale':
            return "Pubbliredazionale gratuito"
        return "Sconto"

    def is_valid(self):
        """Verifica se il codice è valido"""
        if not self.is_active:
            return False, "Codice non attivo"

        # Verifica validità temporale
        now = timezone.now()
        if now < self.valid_from:
            return False, "Codice non ancora valido"

        if self.valid_until and now > self.valid_until:
            return False, "Codice scaduto"

        # Verifica utilizzi
        if self.max_uses and self.current_uses >= self.max_uses:
            return False, "Codice esaurito (raggiunto limite utilizzi)"

        return True, "OK"

    def can_apply_to(self, item_type):
        """Verifica se può essere applicato al tipo di item"""
        if self.applies_to == 'both':
            return True
        return self.applies_to == item_type

    def calculate_discount(self, original_price):
        """Calcola lo sconto da applicare"""
        if self.discount_type == 'free_banner' or self.discount_type == 'free_pubbliredazionale':
            return original_price  # Sconto totale
        elif self.discount_type == 'percentage':
            return (original_price * self.discount_value) / 100
        elif self.discount_type == 'fixed':
            return min(self.discount_value, original_price)  # Non può essere maggiore del prezzo
        return 0

    def increment_uses(self):
        """Incrementa il contatore utilizzi"""
        self.current_uses += 1
        self.save(update_fields=['current_uses'])
