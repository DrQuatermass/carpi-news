from django.contrib import admin
from .models import Banner


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'position', 'status', 'payment_status', 'total_price', 'impressions', 'clicks', 'ctr_display', 'start_date', 'end_date']
    list_filter = ['status', 'payment_status', 'position', 'created_at']
    search_fields = ['title', 'user__username', 'link_url']
    readonly_fields = ['total_price', 'impressions', 'clicks', 'ctr_display', 'created_at', 'updated_at']

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
        """Approva banner selezionati (solo se pagati)"""
        updated = queryset.filter(payment_status='completed').update(status='active')
        self.message_user(request, f'{updated} banner approvati.')
    approve_banners.short_description = 'Approva banner selezionati'

    def reject_banners(self, request, queryset):
        """Rifiuta banner selezionati"""
        updated = queryset.update(status='rejected')
        self.message_user(request, f'{updated} banner rifiutati.')
    reject_banners.short_description = 'Rifiuta banner selezionati'

    def activate_banners(self, request, queryset):
        """Attiva banner selezionati"""
        updated = queryset.filter(payment_status='completed').update(status='active')
        self.message_user(request, f'{updated} banner attivati.')
    activate_banners.short_description = 'Attiva banner selezionati'
