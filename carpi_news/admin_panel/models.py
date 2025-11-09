from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError


class Banner(models.Model):
    """Modello per i banner pubblicitari"""

    POSITION_CHOICES = [
        ('header', 'Header (Sopra il titolo)'),
        ('sidebar_top', 'Sidebar Alto'),
        ('sidebar_middle', 'Sidebar Centro'),
        ('sidebar_bottom', 'Sidebar Basso'),
        ('between_articles', 'Tra gli articoli (Homepage)'),
        ('article_top', 'Inizio articolo'),
        ('article_middle', 'Centro articolo'),
        ('article_bottom', 'Fine articolo'),
        ('footer', 'Footer'),
    ]

    # Dimensioni consigliate per posizione (width x height in pixel)
    # ORIZZONTALI (728×90 Leaderboard): header, footer, article_top, article_bottom
    # VERTICALI (300×250 Medium Rectangle): between_articles, sidebar_*, article_middle
    RECOMMENDED_SIZES = {
        'header': (728, 90),  # Leaderboard - Header sito
        'footer': (728, 90),  # Leaderboard - Footer sito
        'article_top': (728, 90),  # Leaderboard - Inizio articolo
        'article_bottom': (728, 90),  # Leaderboard - Fine articolo
        'between_articles': (300, 250),  # Medium Rectangle - Tra le card homepage
        'article_middle': (300, 250),  # Medium Rectangle - Centro articolo
        'sidebar_top': (300, 250),  # Medium Rectangle - Sidebar alto (non implementato)
        'sidebar_middle': (300, 250),  # Medium Rectangle - Sidebar centro (non implementato)
        'sidebar_bottom': (300, 250),  # Medium Rectangle - Sidebar basso (non implementato)
    }

    # Tolleranza per le dimensioni (±10%)
    SIZE_TOLERANCE = 0.10

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
        ('completed', 'Completato'),
        ('failed', 'Fallito'),
        ('refunded', 'Rimborsato'),
    ]

    # Relazione con utente
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='banners', verbose_name='Utente')

    # Informazioni banner
    title = models.CharField('Titolo', max_length=200, help_text='Nome identificativo del banner')
    image = models.ImageField('Immagine', upload_to='banners/', help_text='Immagine del banner (sarà convertita automaticamente in WebP)')
    link_url = models.URLField('URL di destinazione', help_text='Dove viene reindirizzato chi clicca sul banner')
    alt_text = models.CharField('Testo alternativo', max_length=200, help_text='Descrizione per accessibilità')

    # Posizionamento e durata
    position = models.CharField('Posizione', max_length=50, choices=POSITION_CHOICES)
    priority = models.IntegerField('Priorità', default=1, validators=[MinValueValidator(1)],
                                   help_text='Priorità di visualizzazione (1=bassa, 10=alta)')

    # Date e durata
    start_date = models.DateTimeField('Data inizio', default=timezone.now)
    end_date = models.DateTimeField('Data fine')
    duration_days = models.IntegerField('Durata (giorni)', validators=[MinValueValidator(1)])

    # Pricing
    price_per_day = models.DecimalField('Prezzo al giorno (€)', max_digits=10, decimal_places=2,
                                        validators=[MinValueValidator(0.01)], default=5.00)
    total_price = models.DecimalField('Prezzo totale (€)', max_digits=10, decimal_places=2,
                                      validators=[MinValueValidator(0)], editable=False)

    # Stato e pagamento
    status = models.CharField('Stato', max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_status = models.CharField('Stato pagamento', max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField('Metodo di pagamento', max_length=50, blank=True, null=True)
    payment_transaction_id = models.CharField('ID transazione', max_length=200, blank=True, null=True)
    payment_date = models.DateTimeField('Data pagamento', blank=True, null=True)

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
        # Verifica se è un nuovo banner
        is_new = self.pk is None

        # Calcola il prezzo totale automaticamente
        if self.duration_days and self.price_per_day:
            self.total_price = self.duration_days * self.price_per_day

        # Calcola end_date SOLO se non è già impostata
        if not self.end_date and self.start_date and self.duration_days:
            from datetime import timedelta
            self.end_date = self.start_date + timedelta(days=self.duration_days)

        # Imposta lo stato a 'pending_payment' per i nuovi banner (se non specificato)
        # Il banner parte da pending_payment, poi dopo il pagamento va in pending_approval
        if is_new and self.status == 'draft':
            self.status = 'pending_payment'

        super().save(*args, **kwargs)

        # Invia email all'amministratore per nuovi banner
        if is_new:
            self.send_admin_notification()

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
