from django.contrib import admin
from .models import Banner


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

        count = 0
        for banner in queryset.filter(approved=False):
            banner.approved = True
            banner.approved_by = request.user
            banner.approved_at = timezone.now()

            # Se il banner è in attesa di approvazione e il pagamento è completato, attivalo
            if banner.status == 'pending_approval' and banner.payment_status == 'completed':
                banner.status = 'active'

            banner.save()
            count += 1

        self.message_user(request, f'{count} banner approvati.')
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
