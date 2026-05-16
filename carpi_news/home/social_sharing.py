import logging
import requests
import time
from typing import Dict, Optional
from django.conf import settings
from PIL import Image
from io import BytesIO


logger = logging.getLogger(__name__)


class SocialMediaManager:
    """Gestisce la condivisione automatica sui social media - Telegram, Facebook e Instagram

    Twitter è ora gestito automaticamente via RSS + IFTTT
    """

    def __init__(self):
        # Telegram, Facebook e Instagram - Twitter gestito via RSS + IFTTT
        self.platforms = {
            'telegram': {
                'name': 'Telegram',
                'enabled': getattr(settings, 'TELEGRAM_AUTO_SHARE', False),
                'bot_token': getattr(settings, 'TELEGRAM_BOT_TOKEN', None),
                'chat_id': getattr(settings, 'TELEGRAM_CHAT_ID', None),
            },
            'facebook': {
                'name': 'Facebook',
                'enabled': getattr(settings, 'FACEBOOK_AUTO_SHARE', False),
                'page_id': getattr(settings, 'FACEBOOK_PAGE_ID', None),
                'access_token': getattr(settings, 'FACEBOOK_ACCESS_TOKEN', None),
            },
            'facebook_reel': {
                'name': 'Facebook Reel',
                # Il Reel richiede sia FACEBOOK_AUTO_SHARE che FACEBOOK_REEL_ENABLED:
                # cosi' chi non vuole i Reel mantiene la pubblicazione standard senza modifiche.
                'enabled': (
                    getattr(settings, 'FACEBOOK_AUTO_SHARE', False)
                    and getattr(settings, 'FACEBOOK_REEL_ENABLED', False)
                ),
                'page_id': getattr(settings, 'FACEBOOK_PAGE_ID', None),
                'access_token': getattr(settings, 'FACEBOOK_ACCESS_TOKEN', None),
            },
            'instagram': {
                'name': 'Instagram',
                'enabled': getattr(settings, 'INSTAGRAM_AUTO_SHARE', False),
                'account_id': getattr(settings, 'INSTAGRAM_ACCOUNT_ID', None),
                'access_token': getattr(settings, 'FACEBOOK_ACCESS_TOKEN', None),  # Usa stesso token di Facebook
            }
        }
    
    def _normalize_url(self, url: str) -> str:
        """
        Normalizza URL rimuovendo doppi slash e altri problemi comuni

        Args:
            url: URL da normalizzare

        Returns:
            URL normalizzato
        """
        if not url:
            return url

        # Separa protocollo dal resto
        if '://' in url:
            protocol, rest = url.split('://', 1)
            # Rimuovi doppi slash dal path (ma non dal protocollo)
            while '//' in rest:
                rest = rest.replace('//', '/')
            url = f"{protocol}://{rest}"

        return url

    def _get_article_url(self, articolo) -> str:
        """URL canonico dell'articolo."""
        return f"https://ombradelportico.it/articolo/{articolo.slug}/"

    def _get_social_article_url(self, articolo) -> str:
        """URL usato dai social per forzare metadata da articolo, non da evento."""
        return f"{self._get_article_url(articolo)}?social_share=1"

    def _get_absolute_image_url(self, foto_field: str) -> Optional[str]:
        """
        Converte il campo foto in URL assoluto utilizzabile dalle API social

        Args:
            foto_field: Il contenuto del campo foto dell'articolo

        Returns:
            URL assoluto dell'immagine normalizzato o None se non valido
        """
        if not foto_field:
            return None

        # Se è già un URL assoluto, normalizzalo e ritornalo
        if foto_field.startswith('http://') or foto_field.startswith('https://'):
            return self._normalize_url(foto_field)

        # Se è un percorso relativo (es. /media/images/downloaded/...)
        if foto_field.startswith('/media/'):
            url = f"https://ombradelportico.it{foto_field}"
            return self._normalize_url(url)

        # Se non inizia con /, aggiungi il prefisso completo
        if not foto_field.startswith('/'):
            url = f"https://ombradelportico.it/media/{foto_field}"
            return self._normalize_url(url)

        # Fallback: aggiungi il dominio
        url = f"https://ombradelportico.it{foto_field}"
        return self._normalize_url(url)

    def _refresh_facebook_link_preview(self, article_url: str, access_token: str) -> None:
        """
        Chiede a Facebook di aggiornare la cache Open Graph prima del post.
        Non blocca la condivisione se fallisce: /feed userà comunque il link.
        """
        try:
            response = requests.post(
                "https://graph.facebook.com/v24.0/",
                data={
                    'id': article_url,
                    'scrape': 'true',
                    'access_token': access_token,
                },
                timeout=15,
            )
            if response.status_code == 200:
                logger.info(f"Facebook: cache Open Graph aggiornata per {article_url}")
            else:
                logger.warning(
                    f"Facebook: refresh Open Graph fallito {response.status_code} - {response.text[:500]}"
                )
        except Exception as e:
            logger.warning(f"Facebook: errore refresh Open Graph per {article_url}: {str(e)[:200]}")

    def _validate_image_url(self, image_url: str, timeout: int = 10) -> bool:
        """
        Valida che un URL immagine sia accessibile e contenga un'immagine valida

        Args:
            image_url: URL dell'immagine da validare
            timeout: Timeout in secondi per la richiesta HEAD

        Returns:
            True se l'immagine è accessibile e valida, False altrimenti
        """
        try:
            logger.info(f"Validazione immagine: {image_url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; OmbraDelPortico/1.0; +https://ombradelportico.it)',
                'Accept': 'image/*',
            }

            response = requests.head(image_url, timeout=timeout, headers=headers, allow_redirects=True)

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '').lower()
                if 'image' in content_type:
                    logger.info(f"Immagine valida: {content_type}")
                    return True
                else:
                    logger.warning(f"URL non è un'immagine: Content-Type={content_type}")
                    return False
            else:
                logger.warning(f"Immagine non accessibile: HTTP {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            logger.error(f"Timeout validazione immagine ({timeout}s): {image_url}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Errore validazione immagine: {str(e)[:200]}")
            return False
        except Exception as e:
            logger.error(f"Errore imprevisto validazione: {str(e)[:200]}")
            return False

    def _add_title_overlay(self, img: Image.Image, title: str) -> Image.Image:
        """
        Aggiunge overlay con titolo all'immagine per Instagram.
        Fascia grigia semi-trasparente in basso con titolo in Playfair Display.

        Args:
            img: Immagine PIL già processata
            title: Titolo dell'articolo

        Returns:
            Immagine con overlay
        """
        from PIL import ImageDraw, ImageFont
        import textwrap

        width, height = img.size

        # Crea un layer trasparente per l'overlay
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Fascia grigia semi-trasparente in basso (20% altezza immagine)
        overlay_height = int(height * 0.2)
        overlay_y = height - overlay_height

        # Rettangolo grigio semi-trasparente
        draw.rectangle(
            [(0, overlay_y), (width, height)],
            fill=(50, 50, 50, 180)  # Grigio scuro con 70% opacità
        )

        # Carica font Playfair Display (prova diverse posizioni)
        font_size = int(width * 0.045)  # Font size proporzionale alla larghezza
        font = None

        try:
            # Prova a caricare Playfair Display
            font = ImageFont.truetype("/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Bold.ttf", font_size)
        except:
            try:
                # Fallback: Prova path alternativo
                font = ImageFont.truetype("C:\\Windows\\Fonts\\PlayfairDisplay-Bold.ttf", font_size)
            except:
                try:
                    # Fallback: Usa Georgia (simile a Playfair)
                    font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", font_size)
                except:
                    try:
                        # Ultimo fallback: Times New Roman
                        font = ImageFont.truetype("C:\\Windows\\Fonts\\timesbd.ttf", font_size)
                    except:
                        # Default font
                        font = ImageFont.load_default()
                        logger.warning("Instagram: Font Playfair Display non trovato, uso font default")

        # Wrappa il testo per farlo stare nella larghezza
        max_chars = int(width / (font_size * 0.6))  # Stima caratteri per riga
        wrapped_text = textwrap.fill(title, width=max_chars)
        lines = wrapped_text.split('\n')

        # Limita a massimo 3 righe
        if len(lines) > 3:
            lines = lines[:3]
            lines[2] = lines[2][:max_chars-3] + '...'

        # Calcola posizione verticale centrata nell'overlay
        line_height = font_size * 1.2
        total_text_height = len(lines) * line_height
        text_y = overlay_y + (overlay_height - total_text_height) // 2

        # Disegna ogni riga di testo
        for i, line in enumerate(lines):
            # Calcola larghezza testo per centrarlo
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            text_x = (width - text_width) // 2

            y_position = text_y + (i * line_height)

            # Ombra nera per maggiore leggibilità
            for offset_x, offset_y in [(2, 2), (-2, 2), (2, -2), (-2, -2)]:
                draw.text(
                    (text_x + offset_x, y_position + offset_y),
                    line,
                    font=font,
                    fill=(0, 0, 0, 255)
                )

            # Testo bianco principale
            draw.text(
                (text_x, y_position),
                line,
                font=font,
                fill=(255, 255, 255, 255)
            )

        # Converti immagine originale in RGBA
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        # Componi overlay su immagine
        img_with_overlay = Image.alpha_composite(img, overlay)

        # Converti a RGB per JPEG
        final_img = Image.new('RGB', img_with_overlay.size, (255, 255, 255))
        final_img.paste(img_with_overlay, (0, 0), img_with_overlay)

        logger.info(f"Instagram: Overlay titolo aggiunto ({len(lines)} righe)")
        return final_img

    def _prepare_instagram_image(self, image_url: str, articolo_slug: str, title: str = "") -> Optional[str]:
        """
        Prepara l'immagine per Instagram, croppando se necessario per rispettare aspect ratio.
        Instagram accetta aspect ratio tra 4:5 (0.8) e 1.91:1

        Args:
            image_url: URL assoluto dell'immagine originale
            articolo_slug: Slug dell'articolo per naming file

        Returns:
            URL dell'immagine pronta (originale o croppata), None se errore
        """
        # Retry con backoff esponenziale per gestire problemi di rete temporanei
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # Headers HTTP completi per evitare blocchi anti-bot
                headers = {
                    'User-Agent': 'Mozilla/5.0 (compatible; OmbraDelPortico/1.0; +https://ombradelportico.it)',
                    'Accept': 'image/webp,image/jpeg,image/png,image/*,*/*',
                    'Accept-Encoding': 'gzip, deflate',
                }

                timeout = 30  # Aumentato timeout per immagini grandi o server lenti
                logger.info(f"Instagram: Download immagine (tentativo {attempt + 1}/{max_retries}): {image_url}")

                response = requests.get(image_url, timeout=timeout, headers=headers)

                if response.status_code != 200:
                    logger.warning(f"HTTP {response.status_code} - tentativo {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        delay = 2 ** attempt  # 1s, 2s, 4s
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Download immagine fallito dopo {max_retries} tentativi: HTTP {response.status_code}")
                        return None

                # Download riuscito, prosegui con il processing
                break

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    delay = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"Errore download (tentativo {attempt + 1}/{max_retries}): {str(e)[:100]}. Retry tra {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Download immagine fallito dopo {max_retries} tentativi: {str(e)[:200]}")
                    return None

        try:

            img = Image.open(BytesIO(response.content))
            original_width, original_height = img.size
            aspect_ratio = original_width / original_height

            # Instagram accetta aspect ratio tra 0.8 (4:5 verticale) e 1.91 (orizzontale)
            needs_crop = not (0.8 <= aspect_ratio <= 1.91)

            if needs_crop:
                # Immagine troppo larga o troppo alta - crop al centro
                logger.info(f"Instagram: Crop necessario - {original_width}x{original_height} (aspect ratio: {aspect_ratio:.2f})")
            else:
                logger.info(f"Instagram: Immagine già compatibile - {original_width}x{original_height} (aspect ratio: {aspect_ratio:.2f})")

            if needs_crop:
                if aspect_ratio > 1.91:
                    # Troppo larga - usa aspect ratio 1.91:1 (massimo orizzontale Instagram)
                    target_aspect = 1.91
                    new_width = int(original_height * target_aspect)
                    new_height = original_height
                    logger.info(f"Instagram: Crop orizzontale a 1.91:1 -> {new_width}x{new_height}")
                else:
                    # Troppo alta - usa aspect ratio 0.8 (4:5, massimo verticale Instagram)
                    target_aspect = 0.8
                    new_width = original_width
                    new_height = int(original_width / target_aspect)
                    logger.info(f"Instagram: Crop verticale a 4:5 -> {new_width}x{new_height}")

                # Crop al centro
                left = (original_width - new_width) // 2
                top = (original_height - new_height) // 2
                right = left + new_width
                bottom = top + new_height

                processed_img = img.crop((left, top, right, bottom))
            else:
                # Nessun crop necessario, usa immagine originale
                processed_img = img

            # Converti in RGB se necessario
            if processed_img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', processed_img.size, (255, 255, 255))
                if processed_img.mode == 'P':
                    processed_img = processed_img.convert('RGBA')
                background.paste(processed_img, mask=processed_img.split()[-1] if processed_img.mode == 'RGBA' else None)
                processed_img = background

            # Aggiungi overlay con titolo (se fornito)
            if title:
                processed_img = self._add_title_overlay(processed_img, title)
                logger.info(f"Instagram: Overlay titolo applicato")

            # Salva immagine processata temporaneamente
            import os
            from django.conf import settings

            media_root = settings.MEDIA_ROOT
            instagram_dir = os.path.join(media_root, 'images', 'instagram_temp')
            os.makedirs(instagram_dir, exist_ok=True)

            # Nome file basato su slug articolo
            filename = f"{articolo_slug}_ig.jpg"
            filepath = os.path.join(instagram_dir, filename)

            processed_img.save(filepath, 'JPEG', quality=95, optimize=True)

            # Ritorna URL assoluto dell'immagine processata
            final_url = f"https://ombradelportico.it/media/images/instagram_temp/{filename}"
            logger.info(f"Instagram: Immagine salvata -> {final_url}")
            return final_url

        except Exception as e:
            logger.error(f"Errore preparazione immagine Instagram: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def share_article_on_approval(self, articolo) -> Dict[str, bool]:
        """
        Condivide automaticamente un articolo su Telegram, Facebook e Instagram quando viene approvato
        Con tracking per evitare duplicati - controlla se già pubblicato prima di condividere
        Twitter è ora gestito automaticamente via RSS + IFTTT

        Args:
            articolo: Istanza del modello Articolo

        Returns:
            Dict con il risultato della condivisione (Telegram, Facebook, Instagram)
        """
        from .models import SocialPublicationLog
        from django.db import transaction

        results = {}
        article_url = self._get_social_article_url(articolo)

        logger.info(f"Avvio condivisione social per articolo: {articolo.titolo} (Twitter via RSS+IFTTT)")

        # Telegram
        if self.platforms['telegram']['enabled']:
            should_share = False
            with transaction.atomic():
                # Controlla se già pubblicato con successo (lock a livello DB per prevenire race conditions)
                already_published = SocialPublicationLog.objects.select_for_update().filter(
                    articolo=articolo,
                    platform='telegram',
                    success=True
                ).exists()

                if already_published:
                    logger.info(f"Telegram: Articolo '{articolo.titolo}' già pubblicato, skip")
                    results['telegram'] = True
                else:
                    # Crea un record "in progress" per prevenire condivisioni parallele
                    log_entry, created = SocialPublicationLog.objects.get_or_create(
                        articolo=articolo,
                        platform='telegram',
                        defaults={'success': False, 'error_message': 'In progress...'}
                    )

                    # Se il record esisteva già, un altro worker sta gestendo questa condivisione
                    if not created:
                        logger.info(f"Telegram: Condivisione in corso da altro worker, skip")
                        results['telegram'] = log_entry.success
                    else:
                        should_share = True

            # Esegui condivisione fuori dalla transazione per evitare lock lunghi
            if should_share:
                success = self._share_to_telegram(articolo, article_url)
                results['telegram'] = success
                # Aggiorna il record
                SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    platform='telegram'
                ).update(
                    success=success,
                    error_message=None if success else "Errore condivisione Telegram"
                )
        else:
            logger.info("Condivisione Telegram disabilitata")

        # Facebook
        if self.platforms['facebook']['enabled']:
            should_share = False
            with transaction.atomic():
                # Controlla se già pubblicato con successo (lock a livello DB per prevenire race conditions)
                already_published = SocialPublicationLog.objects.select_for_update().filter(
                    articolo=articolo,
                    platform='facebook',
                    success=True
                ).exists()

                if already_published:
                    logger.info(f"Facebook: Articolo '{articolo.titolo}' già pubblicato, skip")
                    results['facebook'] = True
                else:
                    # Crea un record "in progress" per prevenire condivisioni parallele
                    log_entry, created = SocialPublicationLog.objects.get_or_create(
                        articolo=articolo,
                        platform='facebook',
                        defaults={'success': False, 'error_message': 'In progress...'}
                    )

                    # Se il record esisteva già, un altro worker sta gestendo questa condivisione
                    if not created:
                        logger.info(f"Facebook: Condivisione in corso da altro worker, skip")
                        results['facebook'] = log_entry.success
                    else:
                        should_share = True

            # Esegui condivisione fuori dalla transazione per evitare lock lunghi
            if should_share:
                success = self._share_to_facebook(articolo, article_url)
                results['facebook'] = success
                # Aggiorna il record
                SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    platform='facebook'
                ).update(
                    success=success,
                    error_message=None if success else "Errore condivisione Facebook"
                )
        else:
            logger.info("Condivisione Facebook disabilitata")

        # Facebook Reel (indipendente dal post Pagina: richiede immagine)
        if self.platforms['facebook_reel']['enabled']:
            if articolo.foto:
                should_share = False
                with transaction.atomic():
                    already_published = SocialPublicationLog.objects.select_for_update().filter(
                        articolo=articolo,
                        platform='facebook_reel',
                        success=True
                    ).exists()

                    if already_published:
                        logger.info(f"Facebook Reel: Articolo '{articolo.titolo}' già pubblicato, skip")
                        results['facebook_reel'] = True
                    else:
                        log_entry, created = SocialPublicationLog.objects.get_or_create(
                            articolo=articolo,
                            platform='facebook_reel',
                            defaults={'success': False, 'error_message': 'In progress...'}
                        )
                        if not created:
                            logger.info(f"Facebook Reel: pubblicazione in corso da altro worker, skip")
                            results['facebook_reel'] = log_entry.success
                        else:
                            should_share = True

                if should_share:
                    success, error_msg = self._share_to_facebook_reel(articolo)
                    results['facebook_reel'] = success
                    SocialPublicationLog.objects.filter(
                        articolo=articolo,
                        platform='facebook_reel'
                    ).update(
                        success=success,
                        error_message=None if success else error_msg[:1000]
                    )
            else:
                logger.warning(f"Facebook Reel saltato per '{articolo.titolo}': immagine obbligatoria")
                results['facebook_reel'] = False
        else:
            logger.info("Pubblicazione Facebook Reel disabilitata")

        # Instagram (solo se c'è un'immagine)
        if self.platforms['instagram']['enabled']:
            if articolo.foto:
                should_share = False
                with transaction.atomic():
                    # Controlla se già pubblicato con successo (lock a livello DB per prevenire race conditions)
                    already_published = SocialPublicationLog.objects.select_for_update().filter(
                        articolo=articolo,
                        platform='instagram',
                        success=True
                    ).exists()

                    if already_published:
                        logger.info(f"Instagram: Articolo '{articolo.titolo}' già pubblicato, skip")
                        results['instagram'] = True
                    else:
                        # Crea un record "in progress" per prevenire condivisioni parallele
                        log_entry, created = SocialPublicationLog.objects.get_or_create(
                            articolo=articolo,
                            platform='instagram',
                            defaults={'success': False, 'error_message': 'In progress...'}
                        )

                        # Se il record esisteva già, un altro worker sta gestendo questa condivisione
                        if not created:
                            logger.info(f"Instagram: Condivisione in corso da altro worker, skip")
                            results['instagram'] = log_entry.success
                        else:
                            should_share = True

                # Esegui condivisione fuori dalla transazione per evitare lock lunghi
                if should_share:
                    # Usa retry automatico con delay crescente
                    success, error_msg = self._share_to_instagram_with_retry(articolo, article_url)
                    results['instagram'] = success
                    # Aggiorna il record con messaggio errore dettagliato
                    SocialPublicationLog.objects.filter(
                        articolo=articolo,
                        platform='instagram'
                    ).update(
                        success=success,
                        error_message=None if success else error_msg[:1000]  # Limita a 1000 char
                    )
            else:
                logger.warning(f"Condivisione Instagram saltata per '{articolo.titolo}': immagine obbligatoria")
                results['instagram'] = False
        else:
            logger.info("Condivisione Instagram disabilitata")

        # Log risultati finali
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        logger.info(f"Condivisione completata: {success_count}/{total_count} piattaforme per '{articolo.titolo}'")

        return results

    def retry_failed_platforms_only(self, articolo) -> Dict[str, bool]:
        """
        Riprova la condivisione SOLO sulle piattaforme che non hanno avuto successo.
        Utile quando Instagram fallisce temporaneamente e serve un retry manuale.

        Args:
            articolo: Istanza del modello Articolo

        Returns:
            Dict con il risultato del retry per le piattaforme fallite
        """
        from .models import SocialPublicationLog

        results = {}
        article_url = self._get_social_article_url(articolo)

        logger.info(f"Retry condivisione solo piattaforme fallite per: {articolo.titolo}")

        # Telegram - retry solo se non pubblicato con successo
        if self.platforms['telegram']['enabled']:
            already_published = SocialPublicationLog.objects.filter(
                articolo=articolo,
                platform='telegram',
                success=True
            ).exists()

            if already_published:
                logger.info(f"Telegram: già pubblicato con successo, skip retry")
                results['telegram'] = True
            else:
                logger.info(f"Telegram: tentativo retry...")
                success = self._share_to_telegram(articolo, article_url)
                results['telegram'] = success
                SocialPublicationLog.objects.create(
                    articolo=articolo,
                    platform='telegram',
                    success=success,
                    error_message=None if success else "Retry fallito"
                )

        # Facebook - retry solo se non pubblicato con successo
        if self.platforms['facebook']['enabled']:
            already_published = SocialPublicationLog.objects.filter(
                articolo=articolo,
                platform='facebook',
                success=True
            ).exists()

            if already_published:
                logger.info(f"Facebook: già pubblicato con successo, skip retry")
                results['facebook'] = True
            else:
                logger.info(f"Facebook: tentativo retry...")
                success = self._share_to_facebook(articolo, article_url)
                results['facebook'] = success
                SocialPublicationLog.objects.create(
                    articolo=articolo,
                    platform='facebook',
                    success=success,
                    error_message=None if success else "Retry fallito"
                )

        # Facebook Reel - retry solo se non pubblicato con successo
        if self.platforms['facebook_reel']['enabled']:
            if articolo.foto:
                already_published = SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    platform='facebook_reel',
                    success=True
                ).exists()

                if already_published:
                    logger.info(f"Facebook Reel: già pubblicato, skip retry")
                    results['facebook_reel'] = True
                else:
                    logger.info(f"Facebook Reel: tentativo retry...")
                    success, error_msg = self._share_to_facebook_reel(articolo)
                    results['facebook_reel'] = success
                    SocialPublicationLog.objects.create(
                        articolo=articolo,
                        platform='facebook_reel',
                        success=success,
                        error_message=None if success else error_msg[:1000]
                    )
            else:
                logger.warning(f"Facebook Reel: immagine obbligatoria, skip retry")
                results['facebook_reel'] = False

        # Instagram - retry solo se non pubblicato con successo
        if self.platforms['instagram']['enabled']:
            if articolo.foto:
                already_published = SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    platform='instagram',
                    success=True
                ).exists()

                if already_published:
                    logger.info(f"Instagram: già pubblicato con successo, skip retry")
                    results['instagram'] = True
                else:
                    logger.info(f"Instagram: tentativo retry con delay...")
                    # Usa retry automatico anche per retry manuali
                    success, error_msg = self._share_to_instagram_with_retry(articolo, article_url)
                    results['instagram'] = success
                    SocialPublicationLog.objects.create(
                        articolo=articolo,
                        platform='instagram',
                        success=success,
                        error_message=None if success else error_msg[:1000]
                    )
            else:
                logger.warning(f"Instagram: immagine obbligatoria, skip retry")
                results['instagram'] = False

        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        logger.info(f"Retry completato: {success_count}/{total_count} piattaforme")

        return results

    def _share_to_telegram(self, articolo, article_url: str) -> bool:
        """Condivide su Telegram tramite Bot API con foto se disponibile"""
        try:
            config = self.platforms['telegram']
            if not config['bot_token'] or not config['chat_id']:
                logger.warning("Configurazione Telegram incompleta")
                return False
            
            # Prepara il messaggio
            message = f"📰 *{articolo.titolo}*\n\n{articolo.sommario[:300]}...\n\n[Leggi tutto]({article_url})\n\n#CarpiNews #OmbraDelPortico"
            
            # Se l'articolo ha una foto, usa sendPhoto, altrimenti sendMessage
            if articolo.foto:
                absolute_image_url = self._get_absolute_image_url(articolo.foto)
                if absolute_image_url:
                    # URL dell'API Telegram per inviare foto
                    url = f"https://api.telegram.org/bot{config['bot_token']}/sendPhoto"
                    
                    data = {
                        'chat_id': config['chat_id'],
                        'photo': absolute_image_url,
                        'caption': message,
                        'parse_mode': 'Markdown'
                    }
                else:
                    # Se non riusciamo a ottenere un URL valido, invia solo il testo
                    url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
                    
                    data = {
                        'chat_id': config['chat_id'],
                        'text': message,
                        'parse_mode': 'Markdown',
                        'disable_web_page_preview': False
                    }
            else:
                # URL dell'API Telegram per messaggio di testo
                url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
                
                data = {
                    'chat_id': config['chat_id'],
                    'text': message,
                    'parse_mode': 'Markdown',
                    'disable_web_page_preview': False
                }
            
            response = requests.post(url, data=data, timeout=10)
            
            # Debug logging per analizzare la risposta dell'API
            logger.info(f"Telegram API response status: {response.status_code}")
            logger.info(f"Telegram API response body: {response.text}")
            absolute_url = self._get_absolute_image_url(articolo.foto) if articolo.foto else None
            logger.info(f"Telegram foto URL originale: {articolo.foto if articolo.foto else 'Nessuna foto'}")
            logger.info(f"Telegram foto URL assoluto: {absolute_url if absolute_url else 'Nessuna foto valida'}")
            
            if response.status_code == 200:
                photo_info = " con foto" if articolo.foto else ""
                logger.info(f"Articolo condiviso su Telegram{photo_info}: {articolo.titolo}")
                return True
            else:
                logger.error(f"Errore condivisione Telegram: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Errore condivisione Telegram per articolo '{articolo.titolo}': {str(e)}")
            return False

    def _get_page_access_token(self, user_token: str, page_id: str) -> Optional[str]:
        """
        Ottiene il Page Access Token dalla pagina usando il User Access Token

        Args:
            user_token: User Access Token
            page_id: ID della pagina Facebook

        Returns:
            Page Access Token o None se non disponibile
        """
        try:
            url = f"https://graph.facebook.com/v24.0/{page_id}"
            params = {
                'fields': 'access_token',
                'access_token': user_token
            }
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                page_token = data.get('access_token')
                if page_token:
                    logger.info(f"Page Access Token ottenuto con successo per page {page_id}")
                    return page_token
                else:
                    logger.warning(f"Nessun Page Access Token trovato nella risposta")
                    return None
            else:
                logger.error(f"Errore nel recupero Page Access Token: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Errore nel recupero Page Access Token: {str(e)}")
            return None

    def _share_to_facebook(self, articolo, article_url: str) -> bool:
        """Condivide su Facebook Page tramite Graph API"""
        try:
            config = self.platforms['facebook']
            if not config['access_token'] or not config['page_id']:
                logger.warning("Configurazione Facebook incompleta")
                return False

            # Ottieni il Page Access Token (necessario per pubblicare)
            page_token = self._get_page_access_token(config['access_token'], config['page_id'])
            if not page_token:
                logger.error("Impossibile ottenere Page Access Token")
                return False

            # Prepara il contenuto del post
            # Facebook supporta fino a 63206 caratteri, ma è meglio limitare
            message = f"{articolo.titolo}\n\n{articolo.sommario[:500]}"
            if len(articolo.sommario) > 500:
                message += "..."

            # Aggiorna la cache Open Graph prima di pubblicare.
            # Evita il parametro picture su /feed: non è affidabile per link post moderni.
            self._refresh_facebook_link_preview(article_url, page_token)

            # Usa sempre l'endpoint /feed con il link
            # Facebook genererà automaticamente l'anteprima con immagine dal sito
            # Cliccando sull'immagine, l'utente va direttamente all'articolo
            url = f"https://graph.facebook.com/v24.0/{config['page_id']}/feed"
            data = {
                'access_token': page_token,
                'message': message,
                'link': article_url,
            }
            response = requests.post(url, data=data, timeout=30)

            # Debug logging
            logger.info(f"Facebook API response status: {response.status_code}")
            logger.info(f"Facebook API response body: {response.text}")

            if response.status_code == 200:
                response_data = response.json()
                post_id = response_data.get('id') or response_data.get('post_id')
                logger.info(f"Articolo condiviso su Facebook (Post ID: {post_id}): {articolo.titolo}")
                return True
            else:
                logger.error(f"Errore condivisione Facebook: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Errore condivisione Facebook per articolo '{articolo.titolo}': {str(e)}")
            return False

    def _share_to_facebook_reel(self, articolo) -> tuple[bool, str]:
        """
        Genera un Reel verticale 1080x1920 e lo pubblica sulla Pagina via Reels API.

        Indipendente dal post Pagina standard: ognuno ha il proprio SocialPublicationLog.
        Restituisce (success, error_message_or_video_id).
        """
        try:
            from .facebook_reels import reel_manager  # import locale per evitare costo a startup

            config = self.platforms['facebook_reel']
            if not config['access_token'] or not config['page_id']:
                error = "Configurazione Facebook Reel incompleta"
                logger.warning(error)
                return False, error

            # I Reel richiedono SEMPRE un'immagine sorgente
            if not articolo.foto:
                error = "Facebook Reel richiede un'immagine - post saltato"
                logger.warning(error)
                return False, error

            page_token = self._get_page_access_token(config['access_token'], config['page_id'])
            if not page_token:
                error = "Impossibile ottenere Page Access Token per Reel"
                logger.error(error)
                return False, error

            logger.info(f"Reel: avvio generazione + upload per '{articolo.titolo}'")
            success, info = reel_manager.publish(articolo, page_token)
            if success:
                logger.info(f"Reel pubblicato (video_id={info}): {articolo.titolo}")
                return True, info
            else:
                logger.error(f"Reel fallito per '{articolo.titolo}': {info}")
                return False, info

        except Exception as e:
            error = f"Eccezione Reel '{articolo.titolo}': {e}"
            logger.error(error, exc_info=True)
            return False, error

    def _share_to_instagram_with_retry(self, articolo, article_url: str, max_retries: int = 3) -> tuple[bool, str]:
        """
        Wrapper per _share_to_instagram con retry automatico e delay crescente

        Args:
            articolo: Istanza del modello Articolo
            article_url: URL completo dell'articolo
            max_retries: Numero massimo di tentativi (default 3)

        Returns:
            Tuple (success: bool, error_message: str)
        """
        delays = [0, 30, 60]  # Delay in secondi: immediato, +30s, +60s

        for attempt in range(max_retries):
            # Delay prima del tentativo (eccetto il primo)
            if attempt > 0:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.info(f"Instagram: Tentativo {attempt + 1}/{max_retries} in {delay}s...")
                time.sleep(delay)
            else:
                logger.info(f"Instagram: Tentativo {attempt + 1}/{max_retries}...")

            success, error_msg = self._share_to_instagram(articolo, article_url)

            if success:
                if attempt > 0:
                    logger.info(f"Instagram: Successo al tentativo {attempt + 1}/{max_retries}")
                return True, ""
            else:
                logger.warning(f"Instagram: Tentativo {attempt + 1}/{max_retries} fallito: {error_msg[:200]}")

                # Se è l'ultimo tentativo, ritorna l'errore
                if attempt == max_retries - 1:
                    final_error = f"Fallito dopo {max_retries} tentativi. Ultimo errore: {error_msg}"
                    logger.error(f"Instagram: {final_error}")
                    return False, final_error

        return False, f"Fallito dopo {max_retries} tentativi"

    def _share_to_instagram(self, articolo, article_url: str) -> tuple[bool, str]:
        """
        Condivide su Instagram tramite Instagram Graph API (processo in 2 fasi)

        Fase 1: Crea un container media (carica immagine + caption)
        Fase 2: Pubblica il container

        IMPORTANTE: Instagram richiede SEMPRE un'immagine. Post solo testo non supportati.

        Returns:
            Tuple (success: bool, error_message: str)
        """
        try:
            config = self.platforms['instagram']
            if not config['access_token'] or not config['account_id']:
                error = "Configurazione Instagram incompleta"
                logger.warning(error)
                return False, error

            # Verifica che ci sia un'immagine
            if not articolo.foto:
                error = "Instagram richiede un'immagine - post saltato"
                logger.error(error)
                return False, error

            # Ottieni Page Access Token (necessario per Instagram)
            page_token = self._get_page_access_token(
                config['access_token'],
                getattr(settings, 'FACEBOOK_PAGE_ID', '')
            )
            if not page_token:
                error = "Impossibile ottenere Page Access Token per Instagram"
                logger.error(error)
                return False, error

            # Prepara caption (max 2200 caratteri)
            caption = f"{articolo.titolo}\n\n{articolo.sommario[:450]}"
            if len(articolo.sommario) > 450:
                caption += "..."

            # Invece del link completo, invita a visitare il link in bio
            caption += f"\n\n🔗 Link in bio per leggere l'articolo completo"

            # Aggiungi hashtags basati sulla categoria
            hashtags = self._get_instagram_hashtags(articolo.categoria)
            caption += f"\n\n{hashtags}"

            # Limita a 2200 caratteri
            if len(caption) > 2200:
                caption = caption[:2197] + "..."

            # URL immagine assoluto
            original_image_url = self._get_absolute_image_url(articolo.foto)
            if not original_image_url:
                error = f"URL immagine non valido: {articolo.foto}"
                logger.error(error)
                return False, error

            # Prepara immagine per Instagram (crop automatico e overlay titolo)
            image_url = self._prepare_instagram_image(original_image_url, articolo.slug, articolo.titolo)
            if not image_url:
                error = f"Impossibile preparare immagine per Instagram"
                logger.error(error)
                return False, error

            # FASE 1: Crea container media
            logger.info(f"Instagram: Creazione container media per '{articolo.titolo}'...")
            create_url = f"https://graph.facebook.com/v24.0/{config['account_id']}/media"
            create_data = {
                'access_token': page_token,
                'image_url': image_url,
                'caption': caption,
            }

            create_response = requests.post(create_url, data=create_data, timeout=30)
            logger.info(f"Instagram container response: {create_response.status_code} - {create_response.text}")

            if create_response.status_code != 200:
                error = f"Errore creazione container Instagram: {create_response.text}"
                logger.error(error)
                return False, error

            container_id = create_response.json().get('id')
            if not container_id:
                error = "Container ID non ricevuto da Instagram"
                logger.error(error)
                return False, error

            logger.info(f"Instagram: Container creato con ID {container_id}")

            # Attendi che Instagram processi l'immagine (necessario per evitare errore "Media not ready")
            logger.info("Instagram: Attesa 5 secondi per il processamento dell'immagine...")
            time.sleep(5)

            # FASE 2: Pubblica il container
            logger.info(f"Instagram: Pubblicazione container {container_id}...")
            publish_url = f"https://graph.facebook.com/v24.0/{config['account_id']}/media_publish"
            publish_data = {
                'access_token': page_token,
                'creation_id': container_id,
            }

            publish_response = requests.post(publish_url, data=publish_data, timeout=30)
            logger.info(f"Instagram publish response: {publish_response.status_code} - {publish_response.text}")

            if publish_response.status_code == 200:
                post_id = publish_response.json().get('id')
                logger.info(f"Articolo condiviso su Instagram (Post ID: {post_id}): {articolo.titolo}")
                logger.info("Instagram: Ricordati di mantenere il link del sito nella bio per gli utenti")
                return True, ""
            else:
                error = f"Errore pubblicazione Instagram: {publish_response.text}"
                logger.error(error)
                return False, error

        except Exception as e:
            error = f"Errore condivisione Instagram per articolo '{articolo.titolo}': {str(e)}"
            logger.error(error)
            import traceback
            logger.error(traceback.format_exc())
            return False, error

    def _get_instagram_hashtags(self, categoria: str) -> str:
        """Genera hashtags appropriati basati sulla categoria dell'articolo"""
        base_hashtags = "#CarpiNews #OmbraDelPortico #Carpi"

        category_hashtags = {
            'Sport': '#Sport #CalcioCarpi #CarpiFC',
            'Politica': '#Politica #Amministrazione #ComuneCarpi',
            'Cultura & Eventi': '#Cultura #Eventi #EventiCarpi',
            'Cronaca': '#Cronaca #Notizie #News',
            'Economia': '#Economia #Business #Imprese',
            'Attualità': '#Attualita #News #Oggi',
        }

        category_specific = category_hashtags.get(categoria, '')
        return f"{base_hashtags} {category_specific}".strip()

    def get_platform_status(self) -> Dict[str, Dict]:
        """Restituisce lo stato di configurazione delle piattaforme (Telegram, Facebook, Instagram)"""
        status = {}

        # Telegram
        telegram_config = self.platforms['telegram']
        telegram_configured = bool(telegram_config['bot_token'] and telegram_config['chat_id'])

        status['telegram'] = {
            'name': telegram_config['name'],
            'enabled': telegram_config['enabled'],
            'configured': telegram_configured,
            'ready': telegram_config['enabled'] and telegram_configured
        }

        # Facebook
        facebook_config = self.platforms['facebook']
        facebook_configured = bool(facebook_config['access_token'] and facebook_config['page_id'])

        status['facebook'] = {
            'name': facebook_config['name'],
            'enabled': facebook_config['enabled'],
            'configured': facebook_configured,
            'ready': facebook_config['enabled'] and facebook_configured
        }

        # Facebook Reel (riusa credenziali della Pagina + flag FACEBOOK_REEL_ENABLED)
        reel_config = self.platforms['facebook_reel']
        status['facebook_reel'] = {
            'name': reel_config['name'],
            'enabled': reel_config['enabled'],
            'configured': bool(reel_config['access_token'] and reel_config['page_id']),
            'ready': reel_config['enabled'] and bool(reel_config['access_token'] and reel_config['page_id']),
            'note': 'Richiede immagine - genera video 1080x1920 con musica royalty-free'
        }

        # Instagram
        instagram_config = self.platforms['instagram']
        instagram_configured = bool(instagram_config['access_token'] and instagram_config['account_id'])

        status['instagram'] = {
            'name': instagram_config['name'],
            'enabled': instagram_config['enabled'],
            'configured': instagram_configured,
            'ready': instagram_config['enabled'] and instagram_configured,
            'note': 'Richiede immagine - post solo testo non supportati'
        }

        # Aggiungi info sui social gestiti via RSS
        status['rss_managed'] = {
            'name': 'Twitter via RSS+IFTTT',
            'enabled': True,  # RSS è sempre attivo
            'configured': True,  # Non richiede configurazione
            'ready': True,
            'feeds': [
                'https://ombradelportico.it/feed/rss/',
                'https://ombradelportico.it/feed/recenti/',
                'https://ombradelportico.it/feed/atom/'
            ]
        }

        return status


# Istanza globale del manager
social_manager = SocialMediaManager()
