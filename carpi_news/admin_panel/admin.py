from django.contrib import admin
from .models import Banner, PromotionalCode
from home.models import Articolo


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'position', 'approved', 'status', 'payment_status', 'total_price', 'impressions', 'clicks', 'ctr_display', 'start_date', 'end_date']
    list_filter = ['approved', 'status', 'payment_status', 'position', 'created_at']
    search_fields = ['title', 'user__username', 'link_url']
    readonly_fields = ['total_price', 'impressions', 'clicks', 'ctr_display', 'created_at', 'updated_at', 'approved_by', 'approved_at']

    fieldsets = (
        ('Informazioni Base', {
            'fields': ('user', 'title', 'image', 'link_url', 'alt_text')
        }),
        ('Posizionamento', {
            'fields': ('position', 'priority')
        }),
        ('Durata e Prezzi', {
            'fields': ('start_date', 'end_date', 'duration_days', 'price_per_day', 'total_price')
        }),
        ('Stato e Pagamento', {
            'fields': ('status', 'payment_status', 'payment_method', 'payment_transaction_id', 'payment_date')
        }),
        ('Approvazione', {
            'fields': ('approved', 'approved_by', 'approved_at'),
            'description': 'Il banner deve essere approvato da un amministratore prima di poter essere attivato'
        }),
        ('Statistiche', {
            'fields': ('impressions', 'clicks', 'ctr_display')
        }),
        ('Note', {
            'fields': ('admin_notes',),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def ctr_display(self, obj):
        """Mostra il CTR formattato"""
        return f"{obj.ctr:.2f}%"
    ctr_display.short_description = 'CTR'

    actions = ['approve_banners', 'reject_banners', 'activate_banners']

    def approve_banners(self, request, queryset):
        """Approva banner selezionati"""
        from django.utils import timezone
        from django.core.mail import send_mail
        from django.conf import settings

        count = 0
        for banner in queryset.filter(approved=False):
            banner.approved = True
            banner.approved_by = request.user
            banner.approved_at = timezone.now()

            # Se il banner è in attesa di approvazione e il pagamento è completato, attivalo
            was_pending = banner.status == 'pending_approval'
            if was_pending and banner.payment_status == 'completed':
                banner.status = 'active'

            banner.save()
            count += 1

            # Invia email all'utente per notificare l'approvazione
            if banner.user.email:
                try:
                    subject = f'✅ Banner Approvato: {banner.title}'
                    message = f'''Ciao {banner.user.username},

Il tuo banner è stato approvato ed è ora attivo sul sito!

Dettagli del banner:
- Titolo: {banner.title}
- Posizione: {banner.get_position_display()}
- Data inizio: {banner.start_date.strftime('%d/%m/%Y %H:%M')}
- Data fine: {banner.end_date.strftime('%d/%m/%Y %H:%M')}
- Durata: {banner.duration_days} giorni

Il banner sarà visibile ai visitatori del sito fino alla data di scadenza.

Grazie per aver scelto Ombra del Portico!

---
Ombra del Portico
{settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'https://ombradelportico.it'}
'''
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [banner.user.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Errore invio email approvazione banner {banner.id}: {e}")

        self.message_user(request, f'{count} banner approvati e notifiche inviate agli utenti.')
    approve_banners.short_description = 'Approva banner selezionati'

    def reject_banners(self, request, queryset):
        """Rifiuta banner selezionati"""
        updated = queryset.update(status='rejected', approved=False)
        self.message_user(request, f'{updated} banner rifiutati.')
    reject_banners.short_description = 'Rifiuta banner selezionati'

    def activate_banners(self, request, queryset):
        """Attiva banner selezionati (solo se approvati e pagati)"""
        count = 0
        for banner in queryset.filter(approved=True, payment_status='completed'):
            banner.status = 'active'
            banner.save()
            count += 1

        if count == 0:
            self.message_user(request, 'Nessun banner attivato. I banner devono essere approvati e pagati.', level='warning')
        else:
            self.message_user(request, f'{count} banner attivati.')
    activate_banners.short_description = 'Attiva banner selezionati'


# Admin per pubbliredazionali (filtro su Articolo)
class PubbliredazionaleInline(admin.StackedInline):
    """Inline per campi pubbliredazionale nell'admin articoli"""
    model = Articolo
    fields = ('nome_azienda', 'sito_web', 'intervistato_nome', 'intervistato_cognome', 'payment_status', 'payment_method',
              'payment_transaction_id', 'payment_date', 'total_price', 'interview_data', 'admin_notes')
    readonly_fields = ('total_price', 'interview_data')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PromotionalCode)
class PromotionalCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'description', 'discount_type', 'discount_value', 'applies_to', 'is_active', 'current_uses', 'max_uses', 'valid_until']
    list_filter = ['is_active', 'discount_type', 'applies_to', 'valid_from', 'valid_until']
    search_fields = ['code', 'description']
    readonly_fields = ['current_uses', 'created_at', 'updated_at', 'created_by']

    fieldsets = (
        ('Codice Promozionale', {
            'fields': ('code', 'description', 'is_active')
        }),
        ('Tipo Sconto', {
            'fields': ('discount_type', 'discount_value', 'applies_to')
        }),
        ('Validità', {
            'fields': ('valid_from', 'valid_until')
        }),
        ('Limiti', {
            'fields': ('max_uses', 'current_uses', 'min_amount')
        }),
        ('Metadati', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:  # Se è un nuovo oggetto
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
