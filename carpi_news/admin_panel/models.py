from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone


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

    STATUS_CHOICES = [
        ('draft', 'Bozza'),
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
    image = models.ImageField('Immagine', upload_to='banners/', help_text='Formato consigliato: 728x90 o 300x250')
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

    class Meta:
        verbose_name = 'Banner'
        verbose_name_plural = 'Banner'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.get_position_display()}"

    def save(self, *args, **kwargs):
        # Calcola il prezzo totale automaticamente
        if self.duration_days and self.price_per_day:
            self.total_price = self.duration_days * self.price_per_day

        # Calcola end_date se non impostata
        if self.start_date and self.duration_days and not self.end_date:
            from datetime import timedelta
            self.end_date = self.start_date + timedelta(days=self.duration_days)

        super().save(*args, **kwargs)

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
