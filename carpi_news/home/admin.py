from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.utils.html import format_html
from django.shortcuts import redirect
from django.contrib import messages
from .models import Articolo
import threading
import urllib.parse

@admin.register(Articolo)
class ArticoloAdmin(admin.ModelAdmin):
    list_display = ("titolo", "approvato", "data_pubblicazione", "views", "condividi_social")
    list_filter = ['approvato']
    fields = ('titolo', 'contenuto', 'sommario', 'categoria', 'approvato', 'fonte', 'foto', 'foto_upload', 'views', 'richieste_modifica', 'rigenera_button')
    readonly_fields = ('rigenera_button', 'views')
    
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
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:articolo_id>/rigenera/', self.admin_site.admin_view(self.rigenera_articolo), name='rigenera_articolo'),
        ]
        return custom_urls + urls
    
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