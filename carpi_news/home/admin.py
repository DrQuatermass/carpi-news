from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import redirect, render
from django.contrib import messages
from django.contrib.admin import SimpleListFilter
from django import forms
from .models import Articolo, MonitorConfig, APIUsage, ChatbotConversation, SocialPublicationLog
import threading
import urllib.parse
import subprocess
import os
import json
from pathlib import Path
from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from datetime import timedelta


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

@admin.register(Articolo)
class ArticoloAdmin(admin.ModelAdmin):
    list_display = ("titolo", "categoria", "spotlight_display", "is_pubbliredazionale", "payment_status_display", "approved_display", "approvato", "data_pubblicazione", "views", "fonti_web_count")
    list_filter = ['approvato', 'spotlight', 'categoria', IsPubbliredazionaleFilter, 'payment_status', HasWebSourcesFilter]
    search_fields = ['titolo', 'slug', 'nome_azienda', 'sito_web', 'pubbliredazionale_user__username']
    actions = ['approve_pubbliredazionali']

    def get_fieldsets(self, request, obj=None):
        """Fieldsets dinamici: diversi per pubbliredazionali e articoli normali"""
        if obj and obj.is_pubbliredazionale:
            return (
                ('Informazioni Base', {
                    'fields': ('titolo', 'slug', 'contenuto', 'sommario', 'categoria', 'foto', 'foto_upload')
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
                    'fields': ('approvato', 'approved_by', 'approved_at', 'admin_notes')
                }),
                ('Metadata', {
                    'fields': ('views', 'data_pubblicazione', 'richieste_modifica', 'fonti_web_display', 'rigenera_button'),
                    'classes': ('collapse',)
                }),
            )
        else:
            return (
                ('Informazioni Base', {
                    'fields': ('titolo', 'slug', 'contenuto', 'sommario', 'categoria', 'data_evento', 'foto', 'foto_upload')
                }),
                ('Pubblicazione', {
                    'fields': ('approvato', 'spotlight', 'fonte', 'data_pubblicazione', 'views')
                }),
                ('Rigenerazione AI', {
                    'fields': ('richieste_modifica', 'fonti_web_display', 'rigenera_button')
                }),
            )

    def get_readonly_fields(self, request, obj=None):
        """Readonly fields dinamici"""
        base_readonly = ['rigenera_button', 'views', 'fonti_web_display', 'total_price', 'approved_by', 'approved_at']
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

    def approved_display(self, obj):
        """Mostra stato approvazione pubbliredazionale"""
        if not obj.is_pubbliredazionale:
            return '-'
        if obj.approvato:
            return format_html(
                '<span style="background: #4CAF50; color: white; padding: 4px 8px; '
                'border-radius: 12px; font-size: 11px; font-weight: bold;">✓ APPROVATO</span>'
            )
        return format_html(
            '<span style="background: #FF9800; color: white; padding: 4px 8px; '
            'border-radius: 12px; font-size: 11px; font-weight: bold;">⏳ IN ATTESA</span>'
        )
    approved_display.short_description = 'Approvazione'

    def approve_pubbliredazionali(self, request, queryset):
        """Azione admin per approvare pubbliredazionali e inviare notifica email"""
        from django.utils import timezone
        from django.core.mail import send_mail
        from django.conf import settings

        pubbliredazionali = queryset.filter(is_pubbliredazionale=True, approvato=False)
        count = 0

        for pub in pubbliredazionali:
            # Approva il pubbliredazionale
            pub.approvato = True
            pub.save()
            count += 1

            # Invia email notifica all'utente
            try:
                user_email = pub.pubbliredazionale_user.email if pub.pubbliredazionale_user else None
                if user_email:
                    preview_url = f"{settings.SITE_URL}/gestionale/pubbliredazionale/{pub.id}/preview/"

                    subject = f'Il tuo pubbliredazionale è stato approvato - {pub.nome_azienda}'
                    message = f'''Gentile {pub.pubbliredazionale_user.first_name or 'Cliente'},

Il tuo pubbliredazionale è stato approvato dalla redazione!

Azienda: {pub.nome_azienda}
Titolo: {pub.titolo}

Puoi ora procedere al pagamento e alla pubblicazione accedendo al seguente link:
{preview_url}

Una volta completato il pagamento, l'articolo verrà pubblicato sul sito.

Grazie per aver scelto i nostri servizi.

---
Ombra del Portico - Notizie di Carpi
{settings.SITE_URL}
'''

                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [user_email],
                        fail_silently=True,
                    )
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Errore invio email approvazione pubbliredazionale {pub.id}: {e}")

        self.message_user(request, f'{count} pubbliredazionale/i approvato/i con successo. Email di notifica inviate.')
    approve_pubbliredazionali.short_description = 'Approva pubbliredazionali selezionati'

    def rigenera_button(self, obj):
        if obj.pk:  # Solo per oggetti già salvati
            return format_html(
                '<div style="margin: 10px 0;">'
                '<a class="button" href="{}" style="background: #417690; color: white; padding: 10px 15px; '
                'text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">'
                '🤖 Rigenera Articolo con AI</a>'
                '<p style="margin-top: 8px; font-size: 12px; color: #666;">'
                'Compila il campo "Richieste di modifica" sopra per personalizzare la rigenerazione, '
                
                '</p></div>',
                f'/admin/home/articolo/{obj.pk}/rigenera/'
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
            path('<int:articolo_id>/rigenera/', self.admin_site.admin_view(self.rigenera_articolo), name='rigenera_articolo'),
            path('<int:articolo_id>/toggle_fonte/', self.admin_site.admin_view(self.toggle_fonte), name='toggle_fonte'),
        ]
        return custom_urls + urls

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
    
    def rigenera_articolo(self, request, articolo_id):
        try:
            articolo = Articolo.objects.get(pk=articolo_id)
            
            # Avvia la rigenerazione in background
            thread = threading.Thread(target=self._rigenera_articolo_background, args=(articolo,))
            thread.daemon = True
            thread.start()
            
            messages.success(request, f'Rigenerazione dell\'articolo "{articolo.titolo}" avviata. Controlla tra qualche minuto.')
            
        except Articolo.DoesNotExist:
            messages.error(request, 'Articolo non trovato.')
        except Exception as e:
            messages.error(request, f'Errore durante la rigenerazione: {str(e)}')
        
        return redirect('admin:home_articolo_changelist')
    
    def _rigenera_articolo_background(self, articolo):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            logger.info(f"Inizio rigenerazione articolo: {articolo.titolo} (ID: {articolo.id})")
            import anthropic
            
            # Inizializza il client Anthropic
            from django.conf import settings
            api_key = settings.ANTHROPIC_API_KEY
            if not api_key:
                logger.error("ERRORE: ANTHROPIC_API_KEY non configurata!")
                print("ERRORE: ANTHROPIC_API_KEY non configurata!")
                return
                
            client = anthropic.Anthropic(api_key=api_key)
            
            # Prepara il prompt per la rigenerazione
            prompt_base = f"""Sei un giornalista esperto che deve riscrivere e migliorare questo articolo di news locale per Ombra del Portico.

ARTICOLO ORIGINALE:
Titolo: {articolo.titolo}
Contenuto: {articolo.contenuto}

ISTRUZIONI:
- Mantieni tutte le informazioni fattuali importanti
- Migliora lo stile giornalistico e la leggibilità
- Usa un tono professionale ma accessibile
- Mantieni la struttura HTML se presente
- Non inventare informazioni non presenti nell'originale"""

            # Aggiungi eventuali richieste specifiche
            if articolo.richieste_modifica and articolo.richieste_modifica.strip():
                prompt_base += f"\n\nRICHIESTE SPECIFICHE DI MODIFICA: {articolo.richieste_modifica}"
            
            prompt_base += "\n\nFornisci SOLO il contenuto dell'articolo riscritto, senza commenti aggiuntivi:"
            
            # Chiamata all'API Anthropic
            model_name = "claude-sonnet-4-20250514"
            response = client.messages.create(
                model=model_name,
                max_tokens=4000,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt_base
                }]
            )

            contenuto_rigenerato = response.content[0].text.strip()

            # Traccia utilizzo API
            try:
                from home.api_usage_tracker import APIUsageTracker
                APIUsageTracker.track_anthropic(
                    operation='rigenera_articolo',
                    model=model_name,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    related_article=articolo,
                    success=True
                )
            except Exception as e:
                logger.warning(f"Errore nel tracciare utilizzo API: {e}")

            if contenuto_rigenerato and contenuto_rigenerato != articolo.contenuto:
                # Applica formattazione HTML e link interni con content_polisher
                from home.content_polisher import content_polisher

                contenuto_pulito = content_polisher.clean_content(contenuto_rigenerato)
                contenuto_formattato = content_polisher.format_article_structure(contenuto_pulito)
                contenuto_finale = content_polisher.add_internal_links(
                    contenuto_formattato,
                    article_title=articolo.titolo,
                    current_article_slug=articolo.slug,
                    current_article_date=articolo.data_pubblicazione
                )

                # Salva il contenuto formattato
                articolo.contenuto = contenuto_finale
                # Rigenera anche il sommario
                articolo.sommario = ""  # Così verrà rigenerato automaticamente nel save()
                # Imposta come non approvato per revisione
                articolo.approvato = False
                articolo.save()
                logger.info(f"Articolo '{articolo.titolo}' rigenerato e salvato con successo")
                print(f"Articolo '{articolo.titolo}' rigenerato con successo")
            else:
                logger.warning(f"Nessuna modifica generata per l'articolo '{articolo.titolo}'")
                print(f"Nessuna modifica generata per l'articolo '{articolo.titolo}'")
                
        except Exception as e:
            # Log dell'errore (il sistema di logging dovrebbe catturarlo)
            logger.error(f"Errore nella rigenerazione background: {str(e)}")
            print(f"Errore nella rigenerazione background: {str(e)}")
            # Puoi aggiungere logging più sofisticato qui se necessario


@admin.register(MonitorConfig)
class MonitorConfigAdmin(admin.ModelAdmin):
    form = MonitorConfigForm
    list_display = ('name', 'scraper_type', 'category', 'status_indicator', 'last_run', 'control_buttons')
    list_filter = ('is_active', 'scraper_type', 'category', 'use_ai_generation')
    search_fields = ('name', 'base_url')
    readonly_fields = ('created_at', 'updated_at', 'last_run', 'control_buttons', 'config_help')

    fieldsets = (
        ('Informazioni Base', {
            'fields': ('name', 'base_url', 'scraper_type', 'category')
        }),
        ('Stato e Controllo', {
            'fields': ('is_active', 'auto_approve', 'control_buttons')
        }),
        ('Configurazione AI', {
            'fields': ('use_ai_generation', 'enable_web_search', 'ai_system_prompt'),
            'classes': ('collapse',)
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
        today = timezone.now().date()
        last_7_days = today - timedelta(days=7)
        last_30_days = today - timedelta(days=30)

        # Stats oggi
        today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
        today_stats = APIUsage.objects.filter(timestamp__gte=today_start).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id'),
            anthropic_calls=Count('id', filter=Q(api_type='anthropic')),
            google_calls=Count('id', filter=Q(api_type='google_search'))
        )

        # Stats ultimi 7 giorni
        week_start = timezone.make_aware(timezone.datetime.combine(last_7_days, timezone.datetime.min.time()))
        week_stats = APIUsage.objects.filter(timestamp__gte=week_start).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id')
        )

        # Stats ultimi 30 giorni
        month_start = timezone.make_aware(timezone.datetime.combine(last_30_days, timezone.datetime.min.time()))
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
        start_date = timezone.now() - timedelta(days=days)

        # Stats totali per periodo
        # Usa F() per riferirsi ai campi del database ed evitare conflitti di nomi
        total_stats = APIUsage.objects.filter(timestamp__gte=start_date).aggregate(
            total_cost=Sum(F('cost_total')),
            total_calls=Count('id'),
            anthropic_cost=Sum(F('cost_total'), filter=Q(api_type='anthropic')),
            google_cost=Sum(F('cost_total'), filter=Q(api_type='google_search')),
            anthropic_calls=Count('id', filter=Q(api_type='anthropic')),
            google_calls=Count('id', filter=Q(api_type='google_search')),
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            total_searches=Sum('search_queries')
        )

        # Costi giornalieri
        daily_costs = APIUsage.objects.filter(
            timestamp__gte=start_date
        ).annotate(
            date=TruncDate('timestamp')
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
                    'google_cost': 0,
                    'total_cost': 0,
                    'anthropic_calls': 0,
                    'google_calls': 0,
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
            timestamp__gte=start_date
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
    list_display = ['status_icon', 'platform', 'articolo_title', 'published_at']
    list_filter = ['platform', 'success', 'published_at']
    search_fields = ['articolo__titolo', 'articolo__slug']
    readonly_fields = ['articolo', 'platform', 'success', 'published_at', 'error_message']
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


# Aggiungi link alla dashboard nella lista APIUsage
admin.site.add_action(APIUsageAdmin.dashboard_view, 'Visualizza Dashboard Costi') 