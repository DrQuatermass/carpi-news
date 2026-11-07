from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import redirect, render
from django.contrib import messages
from django.contrib.admin import SimpleListFilter
from django import forms
from .models import (
    APIUsage,
    Articolo,
    ArticoloEliminato,
    ChatbotConversation,
    CondivisioneGruppo,
    GeocodeCache,
    GruppoFacebook,
    InstagramAutoDMLog,
    InstagramOptOut,
    MonitorConfig,
    NewsletterLog,
    NewsletterSubscriber,
    ShortLink,
    SocialPublicationLog,
)
import threading
import urllib.parse
import subprocess
import os
import json
from pathlib import Path
from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from datetime import timedelta
from ckeditor.widgets import CKEditorWidget


class HasWebSourcesFilter(SimpleListFilter):
    title = 'Fonti Web'
    parameter_name = 'has_web_sources'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Con fonti web'),
            ('no', 'Senza fonti web'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(fonti_web__isnull=True).exclude(fonti_web__exact=[])
        elif self.value() == 'no':
            return queryset.filter(fonti_web__isnull=True) | queryset.filter(fonti_web__exact=[])
        return queryset


class IsPubbliredazionaleFilter(SimpleListFilter):
    title = 'Tipo Articolo'
    parameter_name = 'is_pubbliredazionale'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Pubbliredazionali'),
            ('no', 'Articoli normali'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(is_pubbliredazionale=True)
        elif self.value() == 'no':
            return queryset.filter(is_pubbliredazionale=False)
        return queryset


class MonitorConfigForm(forms.ModelForm):
    """Form personalizzato per MonitorConfig con validazione JSON e help text"""

    # Templates JSON per ogni tipo di scraper
    CONFIG_TEMPLATES = {
        'html': {
            'interval': 600,
            'news_url': 'https://example.com/news/',
            'disable_rss': True,
            'selectors': ['.article', '.news', 'article'],
            'content_selectors': ['.content', '.article-body', 'main'],
            'image_selectors': ['img.featured', '.post-thumbnail img'],
            'content_filter_keywords': ['Carpi']
        },
        'wordpress_api': {
            'interval': 600,
            'api_url': 'https://example.com/wp-json/wp/v2/posts',
            'per_page': 10
        },
        'youtube_api': {
            'interval': 1800,
            'api_key': 'YOUR_YOUTUBE_API_KEY',
            'playlist_id': 'PLxxxxxx',
            'max_results': 5,
            'transcript_delay': 60,
            'live_stream_retry_delay': 3600
        },
        'graphql': {
            'interval': 600,
            'graphql_endpoint': 'https://api.example.com/graphql',
            'graphql_headers': {
                'accept': '*/*',
                'content-language': 'it'
            },
            'graphql_query': 'query { posts { id title content } }',
            'fallback_to_wordpress': True,
            'download_images': True
        },
        'email': {
            'interval': 300,
            'imap_server': 'imap.example.com',
            'imap_port': 993,
            'email': 'user@example.com',
            'password': 'YOUR_PASSWORD',
            'mailbox': 'INBOX',
            'sender_filter': [],
            'subject_filter': []
        }
    }

    class Meta:
        model = MonitorConfig
        fields = '__all__'
        widgets = {
            'config_data': forms.Textarea(attrs={
                'rows': 20,
                'style': 'font-family: monospace; font-size: 13px; width: 100%;'
            }),
            'ai_system_prompt': forms.Textarea(attrs={
                'rows': 15,
                'style': 'font-family: monospace; font-size: 13px; width: 100%;'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Help text dinamico per config_data basato sul tipo di scraper
        scraper_type = self.instance.scraper_type if self.instance.pk else 'html'
        template = self.CONFIG_TEMPLATES.get(scraper_type, self.CONFIG_TEMPLATES['html'])

        help_text = f"""
<div style="margin-top: 10px; padding: 15px; background: #f8f9fa; border-left: 4px solid #007bff; border-radius: 4px;">
    <h4 style="margin-top: 0; color: #007bff;">📋 Template per {scraper_type.upper()}</h4>
    <p style="margin-bottom: 10px;">Copia e incolla questo template, poi personalizzalo:</p>
    <pre style="background: #fff; padding: 10px; border: 1px solid #ddd; border-radius: 4px; overflow-x: auto; font-size: 12px;">{json.dumps(template, indent=2, ensure_ascii=False)}</pre>

    <details style="margin-top: 15px;">
        <summary style="cursor: pointer; color: #007bff; font-weight: bold;">📖 Documentazione Campi</summary>
        <div style="margin-top: 10px; padding-left: 15px;">
            <p><strong>interval</strong> (obbligatorio): Intervallo in secondi tra le esecuzioni (min 300)</p>
"""

        # Aggiungi documentazione specifica per tipo
        if scraper_type == 'html':
            help_text += """
            <p><strong>news_url</strong>: URL della pagina con le notizie</p>
            <p><strong>disable_rss</strong>: Disabilita discovery RSS (default: false)</p>
            <p><strong>selectors</strong>: Lista CSS selectors per trovare articoli</p>
            <p><strong>content_selectors</strong>: Selectors per estrarre contenuto</p>
            <p><strong>image_selectors</strong>: Selectors per trovare immagini</p>
            <p><strong>content_filter_keywords</strong>: Parole chiave per filtrare contenuti</p>
"""
        elif scraper_type == 'wordpress_api':
            help_text += """
            <p><strong>api_url</strong>: Endpoint API WordPress (es. /wp-json/wp/v2/posts)</p>
            <p><strong>per_page</strong>: Numero articoli per pagina (default: 10)</p>
"""
        elif scraper_type == 'youtube_api':
            help_text += """
            <p><strong>api_key</strong>: YouTube Data API key</p>
            <p><strong>playlist_id</strong>: ID della playlist (es. PLxxxxxx)</p>
            <p><strong>max_results</strong>: Numero max video da processare</p>
            <p><strong>transcript_delay</strong>: Pausa tra richieste trascrizioni (secondi)</p>
            <p><strong>live_stream_retry_delay</strong>: Attesa prima di riprovare dirette (secondi)</p>
"""
        elif scraper_type == 'graphql':
            help_text += """
            <p><strong>graphql_endpoint</strong>: URL endpoint GraphQL</p>
            <p><strong>graphql_headers</strong>: Headers HTTP da inviare</p>
            <p><strong>graphql_query</strong>: Query GraphQL da eseguire</p>
            <p><strong>fallback_to_wordpress</strong>: Usa WordPress API se GraphQL fallisce</p>
            <p><strong>download_images</strong>: Scarica immagini in locale</p>
"""
        elif scraper_type == 'email':
            help_text += """
            <p><strong>imap_server</strong>: Server IMAP (es. imap.gmail.com)</p>
            <p><strong>imap_port</strong>: Porta IMAP (default: 993)</p>
            <p><strong>email</strong>: Indirizzo email</p>
            <p><strong>password</strong>: Password email</p>
            <p><strong>mailbox</strong>: Cartella da monitorare (default: INBOX)</p>
"""

        help_text += """
        </div>
    </details>
</div>
"""

        self.fields['config_data'].help_text = mark_safe(help_text)

    def clean_config_data(self):
        """Valida che config_data sia JSON valido"""
        data = self.cleaned_data.get('config_data')

        if not data:
            return {}

        # Se è già un dict (dal database), ritorna
        if isinstance(data, dict):
            return data

        # Altrimenti valida il JSON
        try:
            parsed = json.loads(data) if isinstance(data, str) else data

            # Validazione intervallo
            interval = parsed.get('interval')
            if interval and interval < 300:
                raise forms.ValidationError('L\'intervallo minimo è 300 secondi (5 minuti)')

            return parsed
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'JSON non valido: {str(e)}')
        except Exception as e:
            raise forms.ValidationError(f'Errore nella validazione: {str(e)}')

class ArticoloAdminForm(forms.ModelForm):
    """Form personalizzato per Articolo con CKEditor"""
    # Le notizie arrivate per email senza link hanno fonte "email://<uid IMAP>" (serve al monitor
    # per non importarle due volte). Con il campo URL del modello il form le rifiutava come
    # "URL non valido" e l'articolo non si poteva salvare ne' approvare.
    fonte = forms.CharField(required=False, max_length=500, label='Fonte',
                            widget=forms.TextInput(attrs={'class': 'vURLField'}))

    def _get_validation_exclusions(self):
        # Niente URLValidator del modello sulla fonte (vedi sopra)
        esclusi = super()._get_validation_exclusions()
        esclusi.add('fonte')
        return esclusi

    class Meta:
        model = Articolo
        fields = '__all__'
        widgets = {
            'contenuto': CKEditorWidget(),
        }

    class Media:
        css = {
            'all': ('admin/css/ckeditor_custom.css',)
        }

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.da_rielaborare and cleaned.get('approvato'):
            raise forms.ValidationError(
                "Questa è la notizia grezza presa da un'altra fonte: premi \"Rielabora con AI\" "
                "accanto ad Approvato e approva la versione rielaborata."
            )
        return cleaned


@admin.register(Articolo)
class ArticoloAdmin(admin.ModelAdmin):
    form = ArticoloAdminForm
    list_display = ("titolo", "titolo_seo", "categoria", "tags", "spotlight_display", "is_pubbliredazionale", "payment_status_display", "approvato", "da_rielaborare", "escludi_newsletter", "data_pubblicazione", "views", "fonti_web_count")
    list_editable = ("escludi_newsletter",)
    list_filter = ['approvato', 'da_rielaborare', 'spotlight', 'categoria', 'escludi_newsletter', IsPubbliredazionaleFilter, 'payment_status', HasWebSourcesFilter]
    search_fields = ['titolo', 'titolo_seo', 'slug', 'tags', 'nome_azienda', 'sito_web', 'pubbliredazionale_user__username']

    def get_fieldsets(self, request, obj=None):
        """Fieldsets dinamici: diversi per pubbliredazionali e articoli normali"""
        if obj and obj.is_pubbliredazionale:
            return (
                ('Informazioni Base', {
                    'fields': ('titolo', 'titolo_seo', 'slug', 'contenuto', 'sommario', 'spunto_social', 'categoria', 'tags', 'foto', 'cerca_immagine_button', 'foto_upload', 'image_16x9', 'image_4x3', 'image_1x1')
                }),
                ('Pubbliredazionale - Informazioni Azienda', {
                    'fields': ('nome_azienda', 'sito_web', 'pubbliredazionale_user')
                }),
                ('Pubbliredazionale - Pagamento', {
                    'fields': ('payment_status', 'payment_method',
                               'payment_transaction_id', 'payment_date', 'total_price'),
                    'description': 'Informazioni sul pagamento. L\'approvazione si gestisce nel campo "Approvato" sotto.'
                }),
                ('Pubbliredazionale - Intervista AI', {
                    'fields': ('interview_data',),
                    'classes': ('collapse',)
                }),
                ('Approvazione', {
                    'fields': ('approvato', 'admin_notes')
                }),
                ('Metadata', {
                    'fields': ('views', 'data_pubblicazione', 'richieste_modifica', 'fonti_web_display', 'rigenera_button'),
                    'classes': ('collapse',)
                }),
            )
        else:
            return (
                ('Informazioni Base', {
                    'fields': ('titolo', 'titolo_seo', 'slug', 'contenuto', 'sommario', 'spunto_social', 'categoria', 'tags', 'data_evento', 'foto', 'cerca_immagine_button', 'foto_upload', 'image_16x9', 'image_4x3', 'image_1x1')
                }),
                ('Pubblicazione', {
                    'fields': (('approvato', 'rielabora_button'), 'spotlight', 'escludi_newsletter', 'fonte', 'data_pubblicazione', 'views')
                }),
                ('Rigenerazione AI', {
                    'fields': ('richieste_modifica', 'fonti_web_display', 'rigenera_button')
                }),
                ('Luogo', {
                    'fields': ('comune', 'luogo_nome', 'luogo_indirizzo', ('lat', 'lng'), 'luogo_preciso',
                               'luogo_origine', 'luogo_aggiornato'),
                    'description': "Compilato in automatico qualche secondo dopo l'approvazione (comune, "
                                   "posto e coordinate). Puoi correggerlo: l'origine diventa 'Inserito a mano' "
                                   "e l'automatismo non lo tocca più. Senza un posto preciso lascia 'Luogo "
                                   "preciso' spento: l'articolo non va sulla mappa ma resta nella pagina del "
                                   "comune. Le coordinate si leggono su openstreetmap.org (tasto destro, "
                                   "'Mostra indirizzo').",
                }),
            )

    LUOGO_CAMPI = ('comune', 'luogo_nome', 'luogo_indirizzo', 'lat', 'lng', 'luogo_preciso')

    def save_model(self, request, obj, form, change):
        # Una correzione a mano del luogo non deve essere sovrascritta dalla localizzazione automatica
        if change and any(c in form.changed_data for c in self.LUOGO_CAMPI) and 'luogo_origine' not in form.changed_data:
            obj.luogo_origine = 'manuale'
            obj.luogo_aggiornato = timezone.now()
            # Cambiati comune, luogo o indirizzo ma non le coordinate: si cercano su OpenStreetMap
            testo = {'comune', 'luogo_nome', 'luogo_indirizzo'} & set(form.changed_data)
            if testo and not {'lat', 'lng'} & set(form.changed_data):
                from .localizzazione import coordinate_da_campi
                try:
                    if not coordinate_da_campi(obj):
                        self.message_user(request, "Luogo: posto non trovato su OpenStreetMap, uso il centro del "
                                                   "comune. Puoi inserire le coordinate a mano.", level=messages.WARNING)
                except Exception as e:
                    self.message_user(request, f"Luogo: coordinate non aggiornate ({e})", level=messages.WARNING)
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        """Readonly fields dinamici"""
        base_readonly = ['rigenera_button', 'rielabora_button', 'cerca_immagine_button', 'views', 'fonti_web_display', 'total_price']
        if obj and obj.is_pubbliredazionale:
            return base_readonly + ['interview_data']
        return base_readonly

    def spotlight_display(self, obj):
        """Mostra se l'articolo è in spotlight"""
        if obj.spotlight:
            return format_html(
                '<span style="background: #FFD700; color: #333; padding: 4px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: bold;">⭐ SPOTLIGHT</span>'
            )
        return '-'
    spotlight_display.short_description = 'In Evidenza'

    def payment_status_display(self, obj):
        """Mostra stato pagamento"""
        if not obj.is_pubbliredazionale or not obj.payment_status:
            return '-'
        color = '#4CAF50' if obj.payment_status == 'completed' else '#FF9800'
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 8px; '
            'border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color, obj.get_payment_status_display()
        )
    payment_status_display.short_description = 'Pagamento'

    def _ai_button(self, obj, etichetta, colore):
        """Pulsante dentro il form admin: invia il form alla vista di rielaborazione
        (cosi' le "Richieste di modifica" appena scritte vengono usate subito)."""
        from home.rielaborazione_ai import in_corso
        if in_corso(obj.pk):
            return format_html(
                '<span style="display:inline-block; padding: 8px 14px; background:#f0ad4e; color:white; '
                'border-radius:4px; font-weight:bold;">⏳ Rielaborazione in corso: ricarica tra 1-3 minuti</span>'
            )
        return format_html(
            '<button type="submit" formaction="{}" formnovalidate class="button" '
            'style="background: {}; color: white; padding: 8px 14px; border: none; border-radius: 4px; '
            'font-weight: bold; cursor: pointer;">{}</button>',
            f'/admin/home/articolo/{obj.pk}/rielabora/', colore, etichetta,
        )

    def rielabora_button(self, obj):
        if not obj or not obj.pk:
            return '-'
        from home.rielaborazione_ai import trova_monitor
        monitor = trova_monitor(obj)
        regole = monitor.name if monitor else 'regole predefinite'
        if obj.da_rielaborare:
            return format_html(
                '{}<p style="margin: 6px 0 0; font-size: 12px; color: #a94442;">'
                'Notizia grezza da <strong>{}</strong>: non approvabile finché non viene rielaborata.</p>',
                self._ai_button(obj, '🤖 Rielabora con AI', '#c9302c'), regole,
            )
        return format_html(
            '{}<p style="margin: 6px 0 0; font-size: 12px; color: #666;">Regole: {}</p>',
            self._ai_button(obj, '🤖 Rielabora con AI', '#417690'), regole,
        )
    rielabora_button.short_description = 'Rielaborazione'

    def rigenera_button(self, obj):
        if obj.pk:  # Solo per oggetti già salvati
            return format_html(
                '<div style="margin: 10px 0;">{}'
                '<p style="margin-top: 8px; font-size: 12px; color: #666;">'
                'Stessa pipeline della generazione automatica (modello, regole del monitor, ricerca web). '
                'Le "Richieste di modifica" qui sopra vengono passate all\'AI. '
                'Al termine l\'articolo torna da approvare e ricevi l\'email.</p></div>',
                self._ai_button(obj, '🤖 Rigenera Articolo con AI', '#417690'),
            )
        return format_html('<p style="color: #666;">Salva l\'articolo prima per abilitare la rigenerazione AI</p>')
    rigenera_button.short_description = 'Rigenerazione AI'

    def fonti_web_count(self, obj):
        """Mostra il numero di fonti web utilizzate"""
        if obj.fonti_web:
            count = len(obj.fonti_web)
            return format_html(
                '<span style="background: #4CAF50; color: white; padding: 4px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: bold;">'
                '🔍 {} fonti</span>',
                count
            )
        return format_html(
            '<span style="color: #999; font-size: 11px;">❌ Nessuna fonte</span>'
        )
    fonti_web_count.short_description = 'Fonti Web'

    def fonti_web_display(self, obj):
        """Visualizza dettagliatamente le fonti web utilizzate con checkbox per nasconderle"""
        if not obj.fonti_web:
            return format_html(
                '<div style="padding: 10px; background: #f5f5f5; border-radius: 4px; color: #666;">'
                '<p><strong>🔍 Fonti Web:</strong> Nessuna fonte utilizzata</p>'
                '<p style="font-size: 12px; margin: 5px 0 0 0;">Questo articolo non ha utilizzato ricerche web durante la generazione.</p>'
                '</div>'
            )

        # Se l'articolo non è ancora salvato, mostra solo le fonti senza checkbox
        if not obj.pk:
            html_parts = [
                '<div style="padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #4CAF50;">'
                f'<h4 style="margin: 0 0 10px 0; color: #2c3e50;">🔍 Fonti Web Utilizzate ({len(obj.fonti_web)})</h4>'
                '<p style="color: #666; font-size: 12px; margin-bottom: 10px;">Salva l\'articolo per gestire la visibilità delle fonti.</p>'
            ]

            for i, fonte in enumerate(obj.fonti_web, 1):
                query = fonte.get('query_used', 'N/A')
                title = fonte.get('title', 'N/A')
                url = fonte.get('url', 'N/A')

                html_parts.append(
                    f'<div style="margin: 10px 0; padding: 10px; background: white; border-radius: 4px; border: 1px solid #e1e8ed;">'
                    f'<div style="margin-bottom: 8px;"><strong>Fonte {i}:</strong></div>'
                    f'<div style="margin-bottom: 5px;"><strong>Query utilizzata:</strong> '
                    f'<code style="background: #f1f3f4; padding: 2px 6px; border-radius: 3px; font-size: 12px;">{query}</code></div>'
                    f'<div style="margin-bottom: 5px;"><strong>Titolo:</strong> {title}</div>'
                    f'<div><strong>URL:</strong> <a href="{url}" target="_blank" style="color: #1976d2; text-decoration: none;">{url}</a></div>'
                    f'</div>'
                )

            html_parts.append('</div>')
            return mark_safe(''.join(html_parts))

        html_parts = [
            '<div style="padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #4CAF50;">'
            f'<h4 style="margin: 0 0 10px 0; color: #2c3e50;">🔍 Fonti Web Utilizzate ({len(obj.fonti_web)})</h4>'
        ]

        for i, fonte in enumerate(obj.fonti_web):
            query = fonte.get('query_used', 'N/A')
            title = fonte.get('title', 'N/A')
            url = fonte.get('url', 'N/A')
            is_hidden = fonte.get('hidden', False)

            opacity = '0.5' if is_hidden else '1'
            background = '#f5f5f5' if is_hidden else 'white'
            hidden_badge = '<span style="background: #ff5252; color: white; padding: 2px 8px; border-radius: 3px; font-size: 11px; margin-left: 8px;">🔒 Nascosta</span>' if is_hidden else ''

            html_parts.append(
                f'<div style="margin: 10px 0; padding: 10px; background: {background}; border-radius: 4px; border: 1px solid #e1e8ed; opacity: {opacity};">'
                f'<div style="display: flex; align-items: center; margin-bottom: 8px;">'
                f'<label style="display: flex; align-items: center; cursor: pointer; margin: 0;">'
                f'<input type="checkbox" name="fonte_{i}" value="1" {"checked" if is_hidden else ""} '
                f'onchange="toggleFonte{obj.pk}(this, {i})" '
                f'style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">'
                f'<strong>Nascondi Fonte {i + 1}</strong>'
                f'</label>'
                f'{hidden_badge}'
                f'</div>'
                f'<div style="margin-bottom: 5px; margin-left: 26px;"><strong>Query utilizzata:</strong> '
                f'<code style="background: #f1f3f4; padding: 2px 6px; border-radius: 3px; font-size: 12px;">{query}</code></div>'
                f'<div style="margin-bottom: 5px; margin-left: 26px;"><strong>Titolo:</strong> {title}</div>'
                f'<div style="margin-left: 26px;"><strong>URL:</strong> <a href="{url}" target="_blank" style="color: #1976d2; text-decoration: none;">{url}</a></div>'
                f'</div>'
            )

        html_parts.append(
            f'<script>'
            f'function toggleFonte{obj.pk}(checkbox, fonteIndex) {{'
            f'  const csrftoken = document.querySelector("[name=csrfmiddlewaretoken]").value;'
            f'  fetch("/admin/home/articolo/{obj.pk}/toggle_fonte/", {{'
            f'    method: "POST",'
            f'    headers: {{'
            f'      "Content-Type": "application/json",'
            f'      "X-CSRFToken": csrftoken'
            f'    }},'
            f'    body: JSON.stringify({{fonte_index: fonteIndex, hidden: checkbox.checked}})'
            f'  }}).then(response => response.json())'
            f'  .then(data => {{'
            f'    if (data.success) {{'
            f'      location.reload();'
            f'    }} else {{'
            f'      alert("Errore: " + data.error);'
            f'      checkbox.checked = !checkbox.checked;'
            f'    }}'
            f'  }})'
            f'  .catch(error => {{'
            f'    alert("Errore durante il salvataggio");'
            f'    checkbox.checked = !checkbox.checked;'
            f'  }});'
            f'}}'
            f'</script>'
            '</div>'
        )

        return mark_safe(''.join(html_parts))
    fonti_web_display.short_description = 'Dettaglio Fonti Web'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:articolo_id>/rielabora/', self.admin_site.admin_view(self.rielabora_articolo), name='rielabora_articolo'),
            path('<int:articolo_id>/rigenera/', self.admin_site.admin_view(self.rielabora_articolo), name='rigenera_articolo'),
            path('<int:articolo_id>/toggle_fonte/', self.admin_site.admin_view(self.toggle_fonte), name='toggle_fonte'),
            path('<int:articolo_id>/cerca_immagini/', self.admin_site.admin_view(self.cerca_immagini), name='cerca_immagini'),
            path('<int:articolo_id>/usa_immagine/', self.admin_site.admin_view(self.usa_immagine), name='usa_immagine'),
        ]
        return custom_urls + urls

    def cerca_immagine_button(self, obj):
        if not obj or not obj.pk:
            return format_html('<p style="color:#666;">Salva l\'articolo per cercare un\'immagine online</p>')
        return format_html(
            '<div id="cerca-img-{pk}">'
            '<button type="button" class="button" style="background:#417690;color:#fff;padding:8px 14px;border:none;'
            'border-radius:4px;font-weight:bold;cursor:pointer;" onclick="cercaImmagini{pk}(this)">'
            '🔎 Cerca immagine online</button>'
            '<input type="text" class="vTextField termini" placeholder="termini scelti in automatico" '
            'style="margin-left:8px;width:260px;" onkeydown="if(event.keyCode==13){{event.preventDefault();'
            'cercaImmagini{pk}(this.previousElementSibling);}}">'
            '<span class="esito" style="margin-left:10px;font-size:12px;color:#666;"></span>'
            '<div class="candidati" style="display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;"></div>'
            '<p style="margin:6px 0 0;font-size:12px;color:#666;">Cerca su Google Immagini con termini scelti '
            "dall'AI (o scritti nel campo, poi Invio): clicca "
            'una foto per sostituire quella attuale (salvata subito, il resto del form no). Sono foto trovate '
            'in rete: preferisci quelle di siti ufficiali.</p></div>'
            '<script>'
            'function cercaImmagini{pk}(btn){{'
            ' var box=document.getElementById("cerca-img-{pk}"), esito=box.querySelector(".esito"), griglia=box.querySelector(".candidati");'
            ' var termini=box.querySelector(".termini").value.trim();'
            ' esito.textContent="Ricerca in corso..."; griglia.innerHTML=""; btn.disabled=true;'
            ' fetch("/admin/home/articolo/{pk}/cerca_immagini/?q="+encodeURIComponent(termini),{{credentials:"same-origin"}})'
            '  .then(function(r){{return r.json();}}).then(function(d){{'
            '   btn.disabled=false; var c=d.candidati||[]; if(d.query_campo) box.querySelector(".termini").value=d.query_campo;'
            '   esito.textContent=c.length? c.length+" immagini trovate per: "+d.query : (d.errore||"Nessuna immagine trovata per: "+d.query);'
            '   c.forEach(function(x){{'
            '    var a=document.createElement("div"); a.style.cssText="width:180px;cursor:pointer;border:2px solid #ddd;border-radius:4px;padding:4px;font-size:11px;";'
            '    var im=document.createElement("img"); im.src=x.thumb; im.style.cssText="width:100%;height:110px;object-fit:cover;display:block;";'
            '    var t=document.createElement("div"); t.textContent=(x.larghezza||"?")+"×"+(x.altezza||"?")+" · "+(x.pagina||"").replace(/^https?:\\/\\/(www\\.)?/,"").split("/")[0];'
            '    t.style.cssText="color:#666;margin-top:3px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;";'
            '    a.appendChild(im); a.appendChild(t); a.title=x.titolo+"\\n"+x.pagina;'
            '    a.onclick=function(){{ usaImmagine{pk}(x.url, a, esito); }};'
            '    griglia.appendChild(a);'
            '   }});'
            '  }}).catch(function(e){{btn.disabled=false; esito.textContent="Errore: "+e;}});'
            '}}'
            'function usaImmagine{pk}(url, card, esito){{'
            ' esito.textContent="Scarico l\'immagine..."; card.style.borderColor="#f0ad4e";'
            ' var fd=new FormData(); fd.append("url",url);'
            ' fd.append("csrfmiddlewaretoken",(document.querySelector("[name=csrfmiddlewaretoken]")||{{}}).value||"");'
            ' fetch("/admin/home/articolo/{pk}/usa_immagine/",{{method:"POST",body:fd,credentials:"same-origin"}})'
            '  .then(function(r){{return r.json();}}).then(function(d){{'
            '   if(!d.ok){{card.style.borderColor="#c9302c"; esito.textContent=d.errore||"Errore"; return;}}'
            '   card.style.borderColor="#5cb85c"; esito.textContent="Foto sostituita e salvata: "+d.foto;'
            '   var f=document.getElementById("id_foto"); if(f) f.value=d.foto;'
            '  }}).catch(function(e){{card.style.borderColor="#c9302c"; esito.textContent="Errore: "+e;}});'
            '}}'
            '</script>',
            pk=obj.pk,
        )
    cerca_immagine_button.short_description = 'Immagine dalla rete'

    def cerca_immagini(self, request, articolo_id):
        """JSON con le immagini trovate su Google per il titolo (o la query ?q=)."""
        from home.immagini_online import cerca_immagini, cerca_per_articolo
        articolo = Articolo.objects.filter(pk=articolo_id).first()
        if not articolo:
            return JsonResponse({'candidati': [], 'errore': 'Articolo non trovato'}, status=404)
        manuale = (request.GET.get('q') or '').strip()
        if manuale:
            # Termini scritti a mano nel campo accanto al tasto: si cercano cosi' come sono
            usate = [manuale]
            candidati = cerca_immagini(manuale, max_risultati=8, articolo=articolo, operation='cerca_immagine_admin')
        else:
            # Termini scelti dall'AI dal titolo e dal testo (il titolo intero da' risultati a caso)
            usate, candidati = cerca_per_articolo(articolo.titolo, articolo.sommario + ' ' + articolo.contenuto,
                                                  articolo=articolo, operation='cerca_immagine_admin')
        query = ' / '.join(usate)
        return JsonResponse({'query': query, 'query_campo': usate[0] if usate else '', 'candidati': candidati,
                             'errore': '' if candidati else 'Nessuna immagine utilizzabile trovata'})

    def usa_immagine(self, request, articolo_id):
        """Scarica l'immagine scelta e la mette come foto dell'articolo."""
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'errore': 'Metodo non consentito'}, status=405)
        from home.immagini_online import usa_immagine
        articolo = Articolo.objects.filter(pk=articolo_id).first()
        url = request.POST.get('url', '')
        if not articolo or not url.startswith('http'):
            return JsonResponse({'ok': False, 'errore': 'Dati non validi'}, status=400)
        try:
            foto = usa_immagine(articolo, url)
        except Exception as e:
            return JsonResponse({'ok': False, 'errore': str(e)})
        return JsonResponse({'ok': True, 'foto': foto})

    def toggle_fonte(self, request, articolo_id):
        """Gestisce il toggle del campo hidden per le fonti web"""
        if request.method != 'POST':
            return HttpResponse('Method not allowed', status=405)

        try:
            import json
            articolo = Articolo.objects.get(pk=articolo_id)

            # Parse del body JSON
            data = json.loads(request.body)
            fonte_index = data.get('fonte_index')
            hidden = data.get('hidden', False)

            if articolo.fonti_web and 0 <= fonte_index < len(articolo.fonti_web):
                # Aggiorna il campo hidden della fonte
                articolo.fonti_web[fonte_index]['hidden'] = hidden
                articolo.save()

                return HttpResponse(
                    json.dumps({'success': True}),
                    content_type='application/json'
                )
            else:
                return HttpResponse(
                    json.dumps({'success': False, 'error': 'Fonte non trovata'}),
                    content_type='application/json',
                    status=400
                )

        except Exception as e:
            return HttpResponse(
                json.dumps({'success': False, 'error': str(e)}),
                content_type='application/json',
                status=500
            )
    
    def rielabora_articolo(self, request, articolo_id):
        """Avvia la rielaborazione AI con le regole del monitor d'origine
        (tasti "Rielabora con AI" e "Rigenera Articolo con AI")."""
        change_url = reverse('admin:home_articolo_change', args=[articolo_id])
        if request.method != 'POST':
            return redirect(change_url)
        try:
            from home.rielaborazione_ai import avvia_rielaborazione, trova_monitor
            articolo = Articolo.objects.get(pk=articolo_id)
            if 'richieste_modifica' in request.POST:
                articolo.richieste_modifica = request.POST.get('richieste_modifica', '')
                Articolo.objects.filter(pk=articolo.pk).update(richieste_modifica=articolo.richieste_modifica)
            if avvia_rielaborazione(articolo.pk, articolo.richieste_modifica):
                monitor = trova_monitor(articolo)
                messages.success(
                    request,
                    f'Rielaborazione di "{articolo.titolo[:80]}" avviata con le regole di '
                    f'{monitor.name if monitor else "default"}. Richiede 1-3 minuti: al termine '
                    f"l'articolo resta da approvare e ricevi l'email."
                )
            else:
                messages.warning(request, "C'è già una rielaborazione in corso per questo articolo.")
        except Articolo.DoesNotExist:
            messages.error(request, 'Articolo non trovato.')
            return redirect('admin:home_articolo_changelist')
        except Exception as e:
            messages.error(request, f'Errore durante la rielaborazione: {str(e)}')
        return redirect(change_url)


@admin.register(MonitorConfig)
class MonitorConfigAdmin(admin.ModelAdmin):
    form = MonitorConfigForm
    list_display = ('name', 'scraper_type', 'category', 'status_indicator', 'last_run', 'control_buttons')
    list_filter = ('is_active', 'noindex', 'scraper_type', 'category', 'use_ai_generation')
    search_fields = ('name', 'base_url')
    readonly_fields = ('created_at', 'updated_at', 'last_run', 'control_buttons', 'config_help')

    fieldsets = (
        ('Informazioni Base', {
            'fields': ('name', 'base_url', 'scraper_type', 'category')
        }),
        ('Stato e Controllo', {
            'fields': ('is_active', 'auto_approve', 'noindex', 'control_buttons')
        }),
        ('Configurazione AI', {
            'fields': ('use_ai_generation', 'enable_web_search', 'ai_system_prompt'),
            'description': 'Con "Usa generazione AI" spento il monitor non rielabora in automatico: salva la notizia grezza '
                           '(non approvabile) e usa queste regole solo quando premi "Rielabora con AI" accanto ad Approvato. '
                           'Il prompt comune della redazione (lettore, stile, lunghezza, chiusura) e\' nel codice, in '
                           'home/prompt_redazione.py, e viene messo prima di questo campo: qui basta una nota breve sulla '
                           'fonte (che tipo di materiale e\' e cosa conta). Niente istruzioni di formato: le regole di '
                           'output le aggiunge il codice.',
        }),
        ('Configurazioni Specifiche (JSON)', {
            'fields': ('config_help', 'config_data'),
            'description': 'Configurazioni specifiche del monitor in formato JSON. Vedi template sopra.'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'last_run'),
            'classes': ('collapse',)
        }),
    )

    def config_help(self, obj):
        """Mostra template JSON per tutti i tipi di scraper"""
        html = ['<div style="margin: 20px 0;">']

        for scraper_type, template in MonitorConfigForm.CONFIG_TEMPLATES.items():
            html.append(f"""
                <details style="margin: 10px 0; border: 1px solid #ddd; border-radius: 4px;">
                    <summary style="padding: 10px; background: #f8f9fa; cursor: pointer; font-weight: bold;">
                        📋 Template: {scraper_type.upper()}
                    </summary>
                    <div style="padding: 10px;">
                        <button onclick="copyTemplate{scraper_type}()"
                                style="margin-bottom: 10px; padding: 5px 15px; background: #007bff; color: white;
                                       border: none; border-radius: 4px; cursor: pointer;">
                            📋 Copia Template
                        </button>
                        <pre id="template-{scraper_type}" style="background: #fff; padding: 10px; border: 1px solid #ddd;
                             border-radius: 4px; overflow-x: auto; font-size: 12px;">{json.dumps(template, indent=2, ensure_ascii=False)}</pre>
                        <script>
                        function copyTemplate{scraper_type}() {{
                            var text = document.getElementById('template-{scraper_type}').innerText;
                            navigator.clipboard.writeText(text).then(function() {{
                                alert('Template copiato! Incollalo nel campo config_data.');
                            }});
                        }}
                        </script>
                    </div>
                </details>
            """)

        html.append('</div>')
        return mark_safe(''.join(html))

    config_help.short_description = 'Template Configurazioni'

    def status_indicator(self, obj):
        """Mostra lo stato del monitor con colore"""
        if obj.is_active:
            return format_html(
                '<span style="background: #4CAF50; color: white; padding: 4px 12px; '
                'border-radius: 12px; font-size: 14px; font-weight: bold;">✓</span>'
            )
        return format_html(
            '<span style="background: #f44336; color: white; padding: 4px 12px; '
            'border-radius: 12px; font-size: 14px; font-weight: bold;">✗</span>'
        )
    status_indicator.short_description = 'Stato'

    def control_buttons(self, obj):
        """Pulsanti per controllare il monitor"""
        if not obj.pk:
            return format_html('<p style="color: #666;">Salva prima per abilitare i controlli</p>')

        buttons_html = []

        # Pulsante Start/Stop
        if obj.is_active:
            buttons_html.append(
                '<a class="button" href="{}" '
                'style="background: #f44336; color: white; padding: 8px 15px; margin: 0 5px; '
                'text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">'
                '⏸ Stop Monitor</a>'.format(f'/admin/home/monitorconfig/{obj.pk}/stop/')
            )
        else:
            buttons_html.append(
                '<a class="button" href="{}" '
                'style="background: #4CAF50; color: white; padding: 8px 15px; margin: 0 5px; '
                'text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">'
                '▶ Start Monitor</a>'.format(f'/admin/home/monitorconfig/{obj.pk}/start/')
            )

        # Pulsante Test
        buttons_html.append(
            '<a class="button" href="{}" '
            'style="background: #2196F3; color: white; padding: 8px 15px; margin: 0 5px; '
            'text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">'
            '🧪 Test Monitor</a>'.format(f'/admin/home/monitorconfig/{obj.pk}/test/')
        )

        # Pulsante View Logs
        buttons_html.append(
            '<a class="button" href="{}" '
            'style="background: #FF9800; color: white; padding: 8px 15px; margin: 0 5px; '
            'text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">'
            '📋 View Logs</a>'.format(f'/admin/home/monitorconfig/{obj.pk}/logs/')
        )

        return format_html('<div style="margin: 10px 0;">{}</div>', mark_safe(''.join(buttons_html)))
    control_buttons.short_description = 'Controlli Monitor'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:monitor_id>/start/', self.admin_site.admin_view(self.start_monitor), name='start_monitor'),
            path('<int:monitor_id>/stop/', self.admin_site.admin_view(self.stop_monitor), name='stop_monitor'),
            path('<int:monitor_id>/test/', self.admin_site.admin_view(self.test_monitor), name='test_monitor'),
            path('<int:monitor_id>/logs/', self.admin_site.admin_view(self.view_logs), name='view_monitor_logs'),
        ]
        return custom_urls + urls

    def start_monitor(self, request, monitor_id):
        """Avvia un monitor specifico"""
        try:
            monitor = MonitorConfig.objects.get(pk=monitor_id)
            monitor.is_active = True
            monitor.save()

            # Qui puoi aggiungere logica per avviare effettivamente il processo del monitor
            # Ad esempio, chiamando uno script o usando subprocess

            messages.success(request, f'Monitor "{monitor.name}" attivato con successo.')
        except MonitorConfig.DoesNotExist:
            messages.error(request, 'Monitor non trovato.')
        except Exception as e:
            messages.error(request, f'Errore durante l\'attivazione: {str(e)}')

        return redirect('admin:home_monitorconfig_changelist')

    def stop_monitor(self, request, monitor_id):
        """Ferma un monitor specifico"""
        try:
            monitor = MonitorConfig.objects.get(pk=monitor_id)
            monitor.is_active = False
            monitor.save()

            # Qui puoi aggiungere logica per fermare effettivamente il processo del monitor

            messages.success(request, f'Monitor "{monitor.name}" disattivato con successo.')
        except MonitorConfig.DoesNotExist:
            messages.error(request, 'Monitor non trovato.')
        except Exception as e:
            messages.error(request, f'Errore durante la disattivazione: {str(e)}')

        return redirect('admin:home_monitorconfig_changelist')

    def test_monitor(self, request, monitor_id):
        """Testa un monitor specifico"""
        try:
            monitor = MonitorConfig.objects.get(pk=monitor_id)

            # Avvia test in background
            thread = threading.Thread(target=self._test_monitor_background, args=(monitor,))
            thread.daemon = True
            thread.start()

            messages.info(request, f'Test del monitor "{monitor.name}" avviato. Controlla i log per i risultati.')
        except MonitorConfig.DoesNotExist:
            messages.error(request, 'Monitor non trovato.')
        except Exception as e:
            messages.error(request, f'Errore durante il test: {str(e)}')

        return redirect('admin:home_monitorconfig_changelist')

    def view_logs(self, request, monitor_id):
        """Visualizza i log di un monitor in una pagina dedicata"""
        try:
            monitor = MonitorConfig.objects.get(pk=monitor_id)

            # Leggi gli ultimi log
            log_file = Path('logs/monitors.log')
            log_lines = []

            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        # Filtra per il nome del monitor (case insensitive)
                        monitor_name_lower = monitor.name.lower()
                        for line in lines:
                            if monitor_name_lower in line.lower():
                                log_lines.append(line.rstrip())

                        # Prendi le ultime 100 righe
                        log_lines = log_lines[-100:]
                except Exception as e:
                    log_lines = [f'Errore nella lettura del file: {str(e)}']
            else:
                log_lines = ['File di log non trovato.']

            # Se non ci sono log
            if not log_lines:
                log_lines = ['Nessun log trovato per questo monitor.']

            # Renderizza template HTML
            from django.template.response import TemplateResponse

            context = {
                'monitor': monitor,
                'log_lines': log_lines,
                'log_count': len(log_lines),
                'title': f'Log Monitor: {monitor.name}',
                'site_header': 'Ombra del Portico Admin',
                'site_title': 'Log Monitor',
            }

            # HTML inline per evitare di creare un template file
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Log Monitor: {monitor.name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header {{
            padding: 20px;
            background: #417690;
            color: white;
            border-radius: 8px 8px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
        }}
        .header .actions {{
            display: flex;
            gap: 10px;
        }}
        .header a {{
            background: white;
            color: #417690;
            padding: 8px 16px;
            text-decoration: none;
            border-radius: 4px;
            font-weight: 500;
        }}
        .header a:hover {{
            background: #f0f0f0;
        }}
        .info {{
            padding: 15px 20px;
            background: #e7f3ff;
            border-bottom: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
        }}
        .info-item {{
            display: flex;
            flex-direction: column;
        }}
        .info-label {{
            font-size: 12px;
            color: #666;
            margin-bottom: 4px;
        }}
        .info-value {{
            font-weight: 600;
            color: #333;
        }}
        .logs {{
            padding: 20px;
            max-height: 600px;
            overflow-y: auto;
        }}
        .log-line {{
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 13px;
            padding: 6px 12px;
            margin: 2px 0;
            border-radius: 3px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        .log-line:hover {{
            background: #f9f9f9;
        }}
        .log-line.error {{
            background: #fff5f5;
            border-left: 3px solid #ff4444;
        }}
        .log-line.warning {{
            background: #fffef5;
            border-left: 3px solid #ffaa00;
        }}
        .log-line.info {{
            background: #f5f9ff;
            border-left: 3px solid #4488ff;
        }}
        .log-line.success {{
            background: #f5fff5;
            border-left: 3px solid #44ff88;
        }}
        .no-logs {{
            text-align: center;
            padding: 40px;
            color: #999;
            font-style: italic;
        }}
        .footer {{
            padding: 15px 20px;
            background: #f9f9f9;
            border-top: 1px solid #ddd;
            border-radius: 0 0 8px 8px;
            text-align: center;
            color: #666;
            font-size: 13px;
        }}
    </style>
    <script>
        function autoRefresh() {{
            setTimeout(function() {{
                location.reload();
            }}, 30000); // Ricarica ogni 30 secondi
        }}
        // Decommentare per auto-refresh
        // window.onload = autoRefresh;
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📋 Log Monitor: {monitor.name}</h1>
            <div class="actions">
                <a href="javascript:location.reload()">🔄 Ricarica</a>
                <a href="/admin/home/monitorconfig/{monitor.id}/change/">⬅ Torna al Monitor</a>
            </div>
        </div>

        <div class="info">
            <div class="info-item">
                <span class="info-label">Tipo Scraper</span>
                <span class="info-value">{monitor.get_scraper_type_display()}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Categoria</span>
                <span class="info-value">{monitor.category}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Stato</span>
                <span class="info-value" style="color: {'#4CAF50' if monitor.is_active else '#f44336'}">
                    {'✓ Attivo' if monitor.is_active else '✗ Disattivo'}
                </span>
            </div>
            <div class="info-item">
                <span class="info-label">Log Entries</span>
                <span class="info-value">{len(log_lines)}</span>
            </div>
        </div>

        <div class="logs">
"""

            if log_lines and log_lines[0] not in ['Nessun log trovato per questo monitor.', 'File di log non trovato.']:
                for line in log_lines:
                    # Determina il tipo di log dalla riga
                    css_class = 'log-line'
                    if 'ERROR' in line.upper() or 'ERRORE' in line.upper():
                        css_class += ' error'
                    elif 'WARNING' in line.upper() or 'WARN' in line.upper():
                        css_class += ' warning'
                    elif 'INFO' in line.upper():
                        css_class += ' info'
                    elif 'SUCCESS' in line.upper() or 'OK' in line.upper():
                        css_class += ' success'

                    # Escape HTML
                    line_escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html_content += f'            <div class="{css_class}">{line_escaped}</div>\n'
            else:
                html_content += f'            <div class="no-logs">{log_lines[0]}</div>\n'

            html_content += """
        </div>

        <div class="footer">
            Ultimi 100 log entries • File: logs/monitors.log
        </div>
    </div>
</body>
</html>
"""

            return HttpResponse(html_content)

        except MonitorConfig.DoesNotExist:
            messages.error(request, 'Monitor non trovato.')
            return redirect('admin:home_monitorconfig_changelist')
        except Exception as e:
            messages.error(request, f'Errore nella visualizzazione dei log: {str(e)}')
            return redirect('admin:home_monitorconfig_changelist')

    def _test_monitor_background(self, monitor):
        """Esegue il test del monitor in background"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            logger.info(f"Test monitor: {monitor.name}")

            # Converti in SiteConfig e testa
            site_config = monitor.to_site_config()

            # Qui puoi aggiungere la logica di test effettiva
            # Ad esempio, prova a fare scraping di una pagina

            logger.info(f"Test completato per monitor: {monitor.name}")

        except Exception as e:
            logger.error(f"Errore nel test del monitor {monitor.name}: {str(e)}")


@admin.register(APIUsage)
class APIUsageAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'api_type', 'operation', 'model', 'tokens_display', 'cost_display', 'success')
    list_filter = ('api_type', 'success', 'operation')
    search_fields = ('operation', 'model', 'error_message')
    readonly_fields = ('timestamp', 'api_type', 'operation', 'model', 'input_tokens', 'output_tokens',
                      'search_queries', 'input_cost', 'output_cost', 'cost_total', 'success',
                      'error_message', 'related_article')
    date_hierarchy = 'timestamp'

    def _local_day_range(self, date_value):
        """Restituisce il range timezone-aware per un giorno nel timezone Django."""
        current_tz = timezone.get_current_timezone()
        start = timezone.make_aware(
            timezone.datetime.combine(date_value, timezone.datetime.min.time()),
            current_tz
        )
        return start, start + timedelta(days=1)

    fieldsets = (
        ('Informazioni Base', {
            'fields': ('timestamp', 'api_type', 'operation', 'model', 'success')
        }),
        ('Utilizzo Tokens (Anthropic)', {
            'fields': ('input_tokens', 'output_tokens'),
            'classes': ('collapse',)
        }),
        ('Utilizzo Search (Google)', {
            'fields': ('search_queries',),
            'classes': ('collapse',)
        }),
        ('Costi (EUR)', {
            'fields': ('input_cost', 'output_cost', 'cost_total')
        }),
        ('Dettagli', {
            'fields': ('related_article', 'error_message'),
            'classes': ('collapse',)
        }),
    )

    def tokens_display(self, obj):
        """Mostra i token per le API Anthropic"""
        if obj.api_type == 'anthropic':
            return format_html(
                '<span style="color: #2196F3;">📥 {} in</span> | '
                '<span style="color: #4CAF50;">📤 {} out</span>',
                f"{obj.input_tokens:,}", f"{obj.output_tokens:,}"
            )
        elif obj.api_type == 'google_search':
            return format_html(
                '<span style="color: #FF9800;">🔍 {} queries</span>',
                obj.search_queries
            )
        return '-'
    tokens_display.short_description = 'Utilizzo'

    def cost_display(self, obj):
        """Mostra il costo formattato"""
        # Usa __dict__ per accedere al valore grezzo del campo
        cost_value = obj.__dict__.get('cost_total', 0)
        return format_html(
            '<span style="background: #4CAF50; color: white; padding: 4px 8px; '
            'border-radius: 12px; font-size: 12px; font-weight: bold;">${}</span>',
            f"{float(cost_value):.6f}"
        )
    cost_display.short_description = 'Costo'

    def has_add_permission(self, request):
        """Impedisci la creazione manuale di record"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Permetti solo agli admin di eliminare"""
        return request.user.is_superuser

    def changelist_view(self, request, extra_context=None):
        """Aggiungi statistiche nella vista elenco"""
        extra_context = extra_context or {}

        # Calcola statistiche
        today = timezone.localdate()
        last_7_days = today - timedelta(days=6)
        last_30_days = today - timedelta(days=29)

        # Stats oggi
        today_start, tomorrow_start = self._local_day_range(today)
        today_stats = APIUsage.objects.filter(
            timestamp__gte=today_start,
            timestamp__lt=tomorrow_start
        ).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id'),
            anthropic_calls=Count('id', filter=Q(api_type='anthropic')),
            google_calls=Count('id', filter=Q(api_type='google_search')),
            openai_calls=Count('id', filter=Q(api_type='openai')),
            openrouter_calls=Count('id', filter=Q(api_type='openrouter'))
        )

        # Stats ultimi 7 giorni
        week_start, _ = self._local_day_range(last_7_days)
        week_stats = APIUsage.objects.filter(timestamp__gte=week_start).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id')
        )

        # Stats ultimi 30 giorni
        month_start, _ = self._local_day_range(last_30_days)
        month_stats = APIUsage.objects.filter(timestamp__gte=month_start).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id')
        )

        extra_context['today_stats'] = today_stats
        extra_context['week_stats'] = week_stats
        extra_context['month_stats'] = month_stats

        # Link alla dashboard dettagliata
        extra_context['show_dashboard_link'] = True

        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_site.admin_view(self.dashboard_view), name='apiusage_dashboard'),
        ]
        return custom_urls + urls

    def dashboard_view(self, request):
        """Dashboard dettagliata dei costi API"""
        from django.db.models.functions import TruncDate

        # Periodo selezionato (default: ultimi 30 giorni)
        days = int(request.GET.get('days', 30))
        today = timezone.localdate()
        start_day = today - timedelta(days=days - 1)
        start_date, _ = self._local_day_range(start_day)
        _, tomorrow_start = self._local_day_range(today)
        current_tz = timezone.get_current_timezone()

        # Stats totali per periodo
        # Usa F() per riferirsi ai campi del database ed evitare conflitti di nomi
        total_stats = APIUsage.objects.filter(
            timestamp__gte=start_date,
            timestamp__lt=tomorrow_start
        ).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id'),
            anthropic_cost=Sum(F('cost_total'), filter=Q(api_type='anthropic')),
            openai_cost=Sum(F('cost_total'), filter=Q(api_type='openai')),
            openrouter_cost=Sum(F('cost_total'), filter=Q(api_type='openrouter')),
            google_cost=Sum(F('cost_total'), filter=Q(api_type='google_search')),
            anthropic_calls=Count('id', filter=Q(api_type='anthropic')),
            openai_calls=Count('id', filter=Q(api_type='openai')),
            openrouter_calls=Count('id', filter=Q(api_type='openrouter')),
            google_calls=Count('id', filter=Q(api_type='google_search')),
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            total_searches=Sum('search_queries')
        )

        # Costi giornalieri
        daily_costs = APIUsage.objects.filter(
            timestamp__gte=start_date,
            timestamp__lt=tomorrow_start
        ).annotate(
            date=TruncDate('timestamp', tzinfo=current_tz)
        ).values('date', 'api_type').annotate(
            daily_cost=Sum(F('cost_total')),
            daily_calls=Count('id')
        ).order_by('date', 'api_type')

        # Raggruppa per data
        daily_data = {}
        for item in daily_costs:
            date_str = item['date'].strftime('%Y-%m-%d')
            if date_str not in daily_data:
                daily_data[date_str] = {
                    'date': date_str,
                    'anthropic_cost': 0,
                    'openai_cost': 0,
                    'openrouter_cost': 0,
                    'google_search_cost': 0,
                    'total_cost': 0,
                    'anthropic_calls': 0,
                    'openai_calls': 0,
                    'openrouter_calls': 0,
                    'google_search_calls': 0,
                    'total_calls': 0
                }

            api_type = item['api_type']
            daily_data[date_str][f'{api_type}_cost'] = float(item['daily_cost'] or 0)
            daily_data[date_str][f'{api_type}_calls'] = item['daily_calls']
            daily_data[date_str]['total_cost'] += float(item['daily_cost'] or 0)
            daily_data[date_str]['total_calls'] += item['daily_calls']

        # Converti in lista ordinata
        daily_data_list = sorted(daily_data.values(), key=lambda x: x['date'])

        # Top operazioni per costo
        top_operations = APIUsage.objects.filter(
            timestamp__gte=start_date,
            timestamp__lt=tomorrow_start
        ).values('operation', 'api_type').annotate(
            operation_total_cost=Sum(F('cost_total')),
            total_calls=Count('id')
        ).order_by('-operation_total_cost')[:10]

        # Calcola costo medio per ogni operazione
        top_operations_list = list(top_operations)
        for op in top_operations_list:
            if op['total_calls'] > 0:
                op['avg_cost'] = float(op['operation_total_cost']) / op['total_calls']
            else:
                op['avg_cost'] = 0

        context = {
            'title': 'Dashboard Costi API',
            'days': days,
            'total_stats': total_stats,
            'daily_data': daily_data_list,
            'top_operations': top_operations_list,
            'opts': self.model._meta,
            'has_view_permission': True,
        }

        return render(request, 'admin/home/apiusage_dashboard.html', context)


@admin.register(ChatbotConversation)
class ChatbotConversationAdmin(admin.ModelAdmin):
    """Admin per le conversazioni del chatbot"""

    list_display = ('timestamp', 'session_id_short', 'user_message_preview', 'articles_found', 'response_time_display', 'user_ip')
    list_filter = ('timestamp', 'articles_found')
    search_fields = ('user_message', 'bot_response', 'session_id')
    readonly_fields = ('timestamp', 'session_id', 'user_message', 'bot_response', 'intent_data_display',
                      'articles_found', 'articles_links', 'user_ip', 'user_agent', 'response_time_ms')
    date_hierarchy = 'timestamp'

    fieldsets = (
        ('Informazioni Conversazione', {
            'fields': ('timestamp', 'session_id', 'response_time_ms')
        }),
        ('Messaggio Utente', {
            'fields': ('user_message',)
        }),
        ('Risposta Bot', {
            'fields': ('bot_response',)
        }),
        ('Analisi Intent', {
            'fields': ('intent_data_display',),
            'classes': ('collapse',)
        }),
        ('Risultati', {
            'fields': ('articles_found', 'articles_links')
        }),
        ('Metadata', {
            'fields': ('user_ip', 'user_agent'),
            'classes': ('collapse',)
        }),
    )

    def session_id_short(self, obj):
        """Mostra versione abbreviata del session_id"""
        return obj.session_id[:8] + '...' if len(obj.session_id) > 8 else obj.session_id
    session_id_short.short_description = 'Session'

    def user_message_preview(self, obj):
        """Mostra anteprima del messaggio utente"""
        return obj.user_message[:60] + '...' if len(obj.user_message) > 60 else obj.user_message
    user_message_preview.short_description = 'Messaggio'

    def response_time_display(self, obj):
        """Mostra tempo di risposta formattato"""
        if obj.response_time_ms:
            color = '#4CAF50' if obj.response_time_ms < 1000 else '#FF9800' if obj.response_time_ms < 3000 else '#F44336'
            return format_html(
                '<span style="color: {}; font-weight: bold;">{} ms</span>',
                color,
                obj.response_time_ms
            )
        return '-'
    response_time_display.short_description = 'Tempo Risposta'

    def intent_data_display(self, obj):
        """Mostra intent data formattato"""
        import json
        return format_html('<pre>{}</pre>', json.dumps(obj.intent_data, indent=2, ensure_ascii=False))
    intent_data_display.short_description = 'Intent Data'

    def articles_links(self, obj):
        """Mostra link agli articoli trovati"""
        if not obj.articles_ids:
            return '-'

        from .models import Articolo
        articles = Articolo.objects.filter(id__in=obj.articles_ids)

        links = []
        for article in articles:
            url = f'/admin/home/articolo/{article.id}/change/'
            links.append(f'<a href="{url}" target="_blank">{article.titolo[:50]}</a>')

        return format_html('<br>'.join(links))
    articles_links.short_description = 'Articoli Trovati'

    def has_add_permission(self, request):
        """Non permettere creazione manuale"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Permetti solo agli admin di eliminare"""
        return request.user.is_superuser


@admin.register(SocialPublicationLog)
class SocialPublicationLogAdmin(admin.ModelAdmin):
    """Admin per il log delle pubblicazioni social"""
    list_display = ['status_icon', 'platform', 'articolo_title', 'shared_url', 'instagram_media_id', 'published_at', 'updated_at']
    list_filter = ['platform', 'success', 'published_at']
    search_fields = ['articolo__titolo', 'articolo__slug', 'shared_url', 'instagram_media_id', 'instagram_media_ids']
    readonly_fields = [
        'articolo', 'platform', 'success', 'published_at', 'updated_at',
        'error_message', 'shared_url', 'short_link', 'instagram_media_id',
        'instagram_media_ids',
    ]
    date_hierarchy = 'published_at'
    ordering = ['-published_at']

    def status_icon(self, obj):
        """Icona di stato"""
        if obj.success:
            return format_html('<span style="color: green; font-size: 16px;">✓</span>')
        return format_html('<span style="color: red; font-size: 16px;">✗</span>')
    status_icon.short_description = 'Stato'

    def articolo_title(self, obj):
        """Titolo articolo con link"""
        return format_html(
            '<a href="/admin/home/articolo/{}/change/">{}</a>',
            obj.articolo.id,
            obj.articolo.titolo[:50] + ('...' if len(obj.articolo.titolo) > 50 else '')
        )
    articolo_title.short_description = 'Articolo'

    def has_add_permission(self, request):
        """Non permettere creazione manuale"""
        return False


@admin.register(ShortLink)
class ShortLinkAdmin(admin.ModelAdmin):
    list_display = ['token', 'articolo', 'platform', 'medium', 'clicks_count', 'created_at']
    list_filter = ['platform', 'medium', 'created_at']
    search_fields = ['token', 'articolo__titolo', 'articolo__slug']
    readonly_fields = ['created_at', 'updated_at', 'clicks_count', 'last_referer']
    date_hierarchy = 'created_at'


@admin.register(InstagramAutoDMLog)
class InstagramAutoDMLogAdmin(admin.ModelAdmin):
    list_display = ['articolo', 'ig_user_id', 'trigger_type', 'trigger_value', 'dm_sent', 'created_at']
    list_filter = ['trigger_type', 'dm_sent', 'created_at']
    search_fields = ['articolo__titolo', 'ig_user_id', 'media_id', 'trigger_value']
    readonly_fields = ['articolo', 'ig_user_id', 'trigger_type', 'trigger_value', 'media_id', 'short_link', 'dm_sent', 'dm_error', 'created_at']
    date_hierarchy = 'created_at'


@admin.register(InstagramOptOut)
class InstagramOptOutAdmin(admin.ModelAdmin):
    list_display = ['ig_user_id', 'created_at']
    search_fields = ['ig_user_id']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'


# Aggiungi link alla dashboard nella lista APIUsage
admin.site.add_action(APIUsageAdmin.dashboard_view, 'Visualizza Dashboard Costi')


# ---------------------------------------------------------------------------
# NEWSLETTER
# ---------------------------------------------------------------------------

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ['email', 'nome', 'attivo', 'origine', 'data_iscrizione']
    list_filter = ['attivo', 'origine']
    list_editable = ['attivo']
    search_fields = ['email', 'nome']
    readonly_fields = ['data_iscrizione', 'origine', 'token_disiscrizione']
    actions = ['attiva_selezionati', 'disattiva_selezionati']

    def attiva_selezionati(self, request, queryset):
        queryset.update(attivo=True)
        self.message_user(request, f"{queryset.count()} iscritti riattivati.")
    attiva_selezionati.short_description = "Riattiva iscritti selezionati"

    def disattiva_selezionati(self, request, queryset):
        queryset.update(attivo=False)
        self.message_user(request, f"{queryset.count()} iscritti disattivati.")
    disattiva_selezionati.short_description = "Disattiva iscritti selezionati"


@admin.register(NewsletterLog)
class NewsletterLogAdmin(admin.ModelAdmin):
    list_display = ['data_invio', 'oggetto', 'num_articoli', 'num_destinatari', 'stato']
    list_filter = ['stato']
    readonly_fields = ['data_invio', 'oggetto', 'num_destinatari', 'num_articoli', 'stato', 'note']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False 


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = ('query', 'lat', 'lng', 'display_name', 'creato')
    search_fields = ('query', 'display_name')


@admin.register(ArticoloEliminato)
class ArticoloEliminatoAdmin(admin.ModelAdmin):
    """Registro delle cancellazioni: il totale per mese, monitor o motivo si legge dai filtri."""
    list_display = ('titolo', 'monitor', 'categoria', 'motivo', 'data_creazione', 'data_eliminazione')
    list_filter = ('motivo', 'monitor', 'categoria')
    date_hierarchy = 'data_eliminazione'
    search_fields = ('titolo', 'fonte')
    readonly_fields = [f.name for f in ArticoloEliminato._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.db.models import Count
        from django.db.models.functions import TruncMonth
        per_mese = (ArticoloEliminato.objects.annotate(mese=TruncMonth('data_eliminazione'))
                    .values('mese').annotate(n=Count('id')).order_by('-mese')[:6])
        riepilogo = ' · '.join(f"{r['mese']:%m/%Y}: {r['n']}" for r in per_mese if r['mese'])
        if riepilogo:
            messages.info(request, f"Totale eliminati: {ArticoloEliminato.objects.count()} — per mese: {riepilogo}")
        return super().changelist_view(request, extra_context)


@admin.register(GruppoFacebook)
class GruppoFacebookAdmin(admin.ModelAdmin):
    """Gruppi Facebook + pagina "Condividi nei gruppi" (pubblicazione a mano, vedi gruppi_facebook.py)."""
    list_display = ['nome', 'comune', 'parole_chiave', 'come_pagina', 'attivo', 'n_condivisioni', 'ultima_condivisione']
    list_filter = ['attivo', 'come_pagina', 'comune']
    list_editable = ['attivo']
    search_fields = ['nome', 'comune', 'parole_chiave']
    readonly_fields = ['slug', 'creato']
    change_list_template = 'admin/home/gruppofacebook/change_list.html'

    def get_queryset(self, request):
        from django.db.models import Max
        return super().get_queryset(request).annotate(
            _n=Count('condivisioni'), _ultima=Max('condivisioni__data'))

    @admin.display(description='Condivisioni', ordering='_n')
    def n_condivisioni(self, obj):
        return obj._n

    @admin.display(description='Ultima', ordering='_ultima')
    def ultima_condivisione(self, obj):
        return timezone.localtime(obj._ultima).strftime('%d/%m %H:%M') if obj._ultima else '-'

    def get_urls(self):
        return [
            path('condividi/', self.admin_site.admin_view(self.condividi_view), name='gruppi_condividi'),
        ] + super().get_urls()

    def condividi_view(self, request):
        from .gruppi_facebook import gruppi_ordinati, link_gruppo, testo_condivisione

        try:
            giorni = min(max(int(request.GET.get('giorni', 2)), 1), 14)
        except ValueError:
            giorni = 2

        if request.method == 'POST':
            articolo = Articolo.objects.filter(pk=request.POST.get('articolo')).first()
            gruppo = GruppoFacebook.objects.filter(pk=request.POST.get('gruppo')).first()
            if articolo and gruppo:
                if request.POST.get('azione') == 'annulla':
                    CondivisioneGruppo.objects.filter(articolo=articolo, gruppo=gruppo).delete()
                else:
                    CondivisioneGruppo.objects.get_or_create(articolo=articolo, gruppo=gruppo)
            return redirect(f"{reverse('admin:gruppi_condividi')}?giorni={giorni}#art-{request.POST.get('articolo', '')}")

        gruppi = list(GruppoFacebook.objects.filter(attivo=True))
        articoli = list(Articolo.objects.filter(
            approvato=True,
            data_pubblicazione__gte=timezone.now() - timedelta(days=giorni),
        ).order_by('-data_pubblicazione'))

        fatte = {(c.articolo_id, c.gruppo_id): c.data for c in CondivisioneGruppo.objects.filter(
            articolo__in=articoli)}
        ultime_24h = dict(CondivisioneGruppo.objects.filter(
            data__gte=timezone.now() - timedelta(hours=24)).values_list('gruppo').annotate(n=Count('id')))

        schede = []
        for articolo in articoli:
            consigliati, altri = [], []
            for gruppo, punti, motivo in gruppi_ordinati(articolo, gruppi):
                condiviso = fatte.get((articolo.pk, gruppo.pk))
                riga = {
                    'gruppo': gruppo,
                    'motivo': motivo,
                    'condiviso': condiviso,
                    'post_24h': ultime_24h.get(gruppo.pk, 0),
                    'testo': '' if condiviso else testo_condivisione(articolo, gruppo, link_gruppo(articolo, gruppo)),
                }
                (consigliati if punti else altri).append(riga)
            schede.append({'articolo': articolo, 'consigliati': consigliati, 'altri': altri,
                           'n_fatte': sum(1 for r in consigliati + altri if r['condiviso'])})

        context = {
            **self.admin_site.each_context(request),
            'title': 'Condividi nei gruppi Facebook',
            'opts': self.model._meta,
            'schede': schede,
            'giorni': giorni,
            'scelte_giorni': [1, 2, 3, 7],
            'n_gruppi': len(gruppi),
        }
        return render(request, 'admin/home/gruppofacebook/condividi.html', context)


@admin.register(CondivisioneGruppo)
class CondivisioneGruppoAdmin(admin.ModelAdmin):
    list_display = ['data', 'gruppo', 'articolo']
    list_filter = ['gruppo']
    date_hierarchy = 'data'
    raw_id_fields = ['articolo']
