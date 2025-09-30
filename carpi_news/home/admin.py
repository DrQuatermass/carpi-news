from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.admin import SimpleListFilter
from .models import Articolo
import threading
import urllib.parse


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

@admin.register(Articolo)
class ArticoloAdmin(admin.ModelAdmin):
    list_display = ("titolo", "approvato", "data_pubblicazione", "views", "fonti_web_count", "condividi_social")
    list_filter = ['approvato', HasWebSourcesFilter]
    fields = ('titolo', 'contenuto', 'sommario', 'categoria', 'approvato', 'fonte', 'foto', 'foto_upload', 'views', 'richieste_modifica', 'fonti_web_display', 'rigenera_button')
    readonly_fields = ('rigenera_button', 'views', 'fonti_web_display')
    
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
    
    def condividi_social(self, obj):
        if obj.approvato:  # Solo per articoli approvati
            # URL completo dell'articolo  
            article_url = f"https://carpinews.it/articolo/{obj.slug}/"
            article_title = obj.titolo
            
            # Prepara il testo per la condivisione
            text = f"{article_title} - Ombra del Portico"
            
            # URL encoded per i parametri
            encoded_url = urllib.parse.quote(article_url, safe='')
            encoded_text = urllib.parse.quote(text, safe='')
            
            # URL per i vari social
            facebook_url = f"https://www.facebook.com/sharer/sharer.php?u={encoded_url}"
            twitter_url = f"https://twitter.com/intent/tweet?url={encoded_url}&text={encoded_text}"
            linkedin_url = f"https://www.linkedin.com/sharing/share-offsite/?url={encoded_url}"
            whatsapp_url = f"https://api.whatsapp.com/send?text={encoded_text}%20{encoded_url}"
            telegram_url = f"https://t.me/share/url?url={encoded_url}&text={encoded_text}"
            
            # Genera un ID unico per evitare conflitti
            unique_id = f"share_{obj.id}"
            
            return format_html(
                '<button onclick="condividi_{}()" '
                'style="background: linear-gradient(45deg, #ff6b6b, #4ecdc4, #45b7d1, #96ceb4, #ffeaa7); '
                'color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; '
                'font-weight: bold; font-size: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); '
                'transition: transform 0.1s;">'
                '🌐 Condividi Ovunque</button>'
                '<script>'
                'function condividi_{}() {{'
                '  const urls = ["{}", "{}", "{}", "{}", "{}"];'
                '  urls.forEach((url, index) => {{'
                '    setTimeout(() => {{'
                '      window.open(url, "_blank", "width=600,height=400,scrollbars=yes,resizable=yes");'
                '    }}, index * 300);'
                '  }});'
                '}}'
                '</script>',
                obj.id, obj.id, facebook_url, twitter_url, linkedin_url, whatsapp_url, telegram_url
            )
        else:
            return format_html('<span style="color: #999; font-size: 12px;">⏳ Approva per condividere</span>')
    
    condividi_social.short_description = 'Condividi sui Social'

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
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt_base
                }]
            )
            
            contenuto_rigenerato = response.content[0].text.strip()
            
            if contenuto_rigenerato and contenuto_rigenerato != articolo.contenuto:
                # Salva il contenuto rigenerato
                articolo.contenuto = contenuto_rigenerato
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