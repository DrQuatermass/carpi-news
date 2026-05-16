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
            'facebook_story': {
                'name': 'Facebook Story',
                # Riusa il video verticale del Reel, ma pubblica una Storia.
                # FACEBOOK_REEL_ENABLED resta come alias legacy per evitare cambi .env immediati.
                'enabled': (
                    getattr(settings, 'FACEBOOK_AUTO_SHARE', False)
                    and (
                        getattr(settings, 'FACEBOOK_STORY_ENABLED', False)
                        or getattr(settings, 'FACEBOOK_REEL_ENABLED', False)
                    )
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

    def _cleanup_instagram_local_file(self, articolo_slug: str) -> None:
        """
        Rimuove il template Instagram locale dopo pubblicazione riuscita.
        Una volta che Meta ha scaricato l'immagine dall'URL e l'ha pubblicata,
        il file in MEDIA_ROOT/images/instagram_temp/<slug>_ig.jpg non e' piu'
        necessario (Instagram serve il post dalla propria CDN). Non blocca
        nulla se il file e' gia' assente o non eliminabile.
        """
        import os
        from pathlib import Path
        try:
            local_path = Path(settings.MEDIA_ROOT) / "images" / "instagram_temp" / f"{articolo_slug}_ig.jpg"
            if local_path.exists():
                size_kb = local_path.stat().st_size // 1024
                local_path.unlink()
                logger.info(f"Instagram: file locale rimosso {local_path.name} ({size_kb} KB liberati)")
        except OSError as e:
            logger.warning(f"Instagram: cleanup file locale fallito per {articolo_slug}: {e}")

    def _prepare_instagram_image(self, image_url: str, articolo_slug: str,
                                  title: str = "", category: str = "Notizie") -> Optional[str]:
        """
        Scarica l'immagine articolo, applica il template Instagram 1080x1080
        coerente con il Reel (logo + card + badge categoria + titolo Playfair +
        CTA "Leggi nel link in bio") e ritorna l'URL pubblico dell'immagine
        salvata in MEDIA_ROOT/images/instagram_temp/<slug>_ig.jpg.

        Args:
            image_url: URL assoluto dell'immagine originale dell'articolo
            articolo_slug: slug per il nome file output
            title: titolo dell'articolo (overlay)
            category: categoria (badge sopra il titolo)

        Returns:
            URL pubblico dell'immagine template, oppure None se errore.
        """
        from .instagram_templates import render_instagram_post

        # 1) Scarica l'immagine sorgente con retry esponenziale
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (compatible; OmbraDelPortico/1.0; +https://ombradelportico.it)',
                    'Accept': 'image/webp,image/jpeg,image/png,image/*,*/*',
                    'Accept-Encoding': 'gzip, deflate',
                }
                logger.info(f"Instagram: download immagine (tentativo {attempt + 1}/{max_retries}): {image_url}")
                resp = requests.get(image_url, timeout=30, headers=headers)
                if resp.status_code == 200:
                    response = resp
                    break
                logger.warning(f"Instagram: HTTP {resp.status_code} (tentativo {attempt + 1}/{max_retries})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Instagram: errore download tentativo {attempt + 1}/{max_retries}: {str(e)[:100]}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        if response is None:
            logger.error(f"Instagram: download immagine fallito dopo {max_retries} tentativi")
            return None

        # 2) Salva la sorgente in un file temp
        import tempfile, os
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"ig_src_{articolo_slug}_", suffix=".img")
        try:
            with os.fdopen(tmp_fd, "wb") as tmp:
                tmp.write(response.content)

            # 3) Genera il template via il modulo dedicato
            out_path = render_instagram_post(
                image_path=tmp_path,
                slug=articolo_slug,
                title=title,
                category=category or "Notizie",
            )
            if out_path is None:
                logger.error(f"Instagram: render template fallito per slug={articolo_slug}")
                return None

            final_url = f"https://ombradelportico.it/media/images/instagram_temp/{out_path.name}"
            logger.info(f"Instagram: template salvato -> {final_url}")
            return final_url
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

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

        # Facebook Story (indipendente dal post Pagina: richiede immagine)
        if self.platforms['facebook_story']['enabled']:
            if articolo.foto:
                should_share = False
                with transaction.atomic():
                    already_published = SocialPublicationLog.objects.select_for_update().filter(
                        articolo=articolo,
                        platform='facebook_story',
                        success=True
                    ).exists()

                    if already_published:
                        logger.info(f"Facebook Story: Articolo '{articolo.titolo}' già pubblicato, skip")
                        results['facebook_story'] = True
                    else:
                        log_entry, created = SocialPublicationLog.objects.get_or_create(
                            articolo=articolo,
                            platform='facebook_story',
                            defaults={'success': False, 'error_message': 'In progress...'}
                        )
                        if not created:
                            logger.info(f"Facebook Story: pubblicazione in corso da altro worker, skip")
                            results['facebook_story'] = log_entry.success
                        else:
                            should_share = True

                if should_share:
                    success, error_msg = self._share_to_facebook_story(articolo)
                    results['facebook_story'] = success
                    SocialPublicationLog.objects.filter(
                        articolo=articolo,
                        platform='facebook_story'
                    ).update(
                        success=success,
                        error_message=None if success else error_msg[:1000]
                    )
            else:
                logger.warning(f"Facebook Story saltata per '{articolo.titolo}': immagine obbligatoria")
                results['facebook_story'] = False
        else:
            logger.info("Pubblicazione Facebook Story disabilitata")

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

        # Facebook Story - retry solo se non pubblicato con successo
        if self.platforms['facebook_story']['enabled']:
            if articolo.foto:
                already_published = SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    platform='facebook_story',
                    success=True
                ).exists()

                if already_published:
                    logger.info(f"Facebook Story: già pubblicata, skip retry")
                    results['facebook_story'] = True
                else:
                    logger.info(f"Facebook Story: tentativo retry...")
                    success, error_msg = self._share_to_facebook_story(articolo)
                    results['facebook_story'] = success
                    SocialPublicationLog.objects.create(
                        articolo=articolo,
                        platform='facebook_story',
                        success=success,
                        error_message=None if success else error_msg[:1000]
                    )
            else:
                logger.warning(f"Facebook Story: immagine obbligatoria, skip retry")
                results['facebook_story'] = False

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

    def _share_to_facebook_story(self, articolo) -> tuple[bool, str]:
        """
        Genera un video verticale 1080x1920 e lo pubblica come Storia Facebook.

        Indipendente dal post Pagina standard: ognuno ha il proprio SocialPublicationLog.
        Restituisce (success, error_message_or_post_id).
        """
        try:
            from .facebook_reels import reel_manager  # import locale per evitare costo a startup

            config = self.platforms['facebook_story']
            if not config['access_token'] or not config['page_id']:
                error = "Configurazione Facebook Story incompleta"
                logger.warning(error)
                return False, error

            # Le Stories video richiedono SEMPRE un'immagine sorgente per generare il video.
            if not articolo.foto:
                error = "Facebook Story richiede un'immagine - post saltato"
                logger.warning(error)
                return False, error

            page_token = self._get_page_access_token(config['access_token'], config['page_id'])
            if not page_token:
                error = "Impossibile ottenere Page Access Token per Story"
                logger.error(error)
                return False, error

            logger.info(f"Facebook Story: avvio generazione + upload per '{articolo.titolo}'")
            success, info = reel_manager.publish(articolo, page_token)
            if success:
                logger.info(f"Facebook Story pubblicata (post_id={info}): {articolo.titolo}")
                return True, info
            else:
                logger.error(f"Facebook Story fallita per '{articolo.titolo}': {info}")
                return False, info

        except Exception as e:
            error = f"Eccezione Facebook Story '{articolo.titolo}': {e}"
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

            # Prepara immagine per Instagram (template 1080x1080 con logo, card, badge e CTA)
            image_url = self._prepare_instagram_image(
                original_image_url,
                articolo.slug,
                articolo.titolo,
                articolo.categoria or "Notizie",
            )
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
                # Cleanup: Instagram ha gia' scaricato e processato l'immagine,
                # il file locale non serve piu'. Su failure NON eliminiamo per debug.
                self._cleanup_instagram_local_file(articolo.slug)
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

        # Facebook Story (riusa credenziali della Pagina + flag FACEBOOK_STORY_ENABLED)
        story_config = self.platforms['facebook_story']
        status['facebook_story'] = {
            'name': story_config['name'],
            'enabled': story_config['enabled'],
            'configured': bool(story_config['access_token'] and story_config['page_id']),
            'ready': story_config['enabled'] and bool(story_config['access_token'] and story_config['page_id']),
            'note': 'Richiede immagine - genera video 1080x1920 e lo pubblica come Storia'
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
            'enabled': True,  # RSS e' sempre attivo
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
