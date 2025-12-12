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
            'instagram': {
                'name': 'Instagram',
                'enabled': getattr(settings, 'INSTAGRAM_AUTO_SHARE', False),
                'account_id': getattr(settings, 'INSTAGRAM_ACCOUNT_ID', None),
                'access_token': getattr(settings, 'FACEBOOK_ACCESS_TOKEN', None),  # Usa stesso token di Facebook
            }
        }
    
    def _get_absolute_image_url(self, foto_field: str) -> Optional[str]:
        """
        Converte il campo foto in URL assoluto utilizzabile dalle API social
        
        Args:
            foto_field: Il contenuto del campo foto dell'articolo
            
        Returns:
            URL assoluto dell'immagine o None se non valido
        """
        if not foto_field:
            return None
            
        # Se è già un URL assoluto, ritornalo così com'è
        if foto_field.startswith('http://') or foto_field.startswith('https://'):
            return foto_field
            
        # Se è un percorso relativo (es. /media/images/downloaded/...)
        if foto_field.startswith('/media/'):
            return f"https://ombradelportico.it{foto_field}"
            
        # Se non inizia con /, aggiungi il prefisso completo
        if not foto_field.startswith('/'):
            return f"https://ombradelportico.it/media/{foto_field}"
            
        # Fallback: aggiungi il dominio
        return f"https://ombradelportico.it{foto_field}"

    def _validate_instagram_image(self, image_url: str) -> bool:
        """
        Valida che l'immagine rispetti i requisiti di Instagram per aspect ratio.
        Instagram accetta aspect ratio tra 4:5 (0.8) e 1.91:1

        Args:
            image_url: URL assoluto dell'immagine

        Returns:
            True se l'immagine è compatibile, False altrimenti
        """
        try:
            response = requests.get(image_url, timeout=10)
            if response.status_code != 200:
                logger.error(f"Impossibile scaricare immagine per validazione: {response.status_code}")
                return False

            img = Image.open(BytesIO(response.content))
            width, height = img.size
            aspect_ratio = width / height

            # Instagram accetta aspect ratio tra 0.8 (4:5 verticale) e 1.91 (orizzontale)
            if 0.8 <= aspect_ratio <= 1.91:
                logger.info(f"Instagram: Immagine valida - {width}x{height} (aspect ratio: {aspect_ratio:.2f})")
                return True
            else:
                logger.warning(f"Instagram: Immagine NON valida - {width}x{height} (aspect ratio: {aspect_ratio:.2f}, richiesto 0.8-1.91)")
                return False

        except Exception as e:
            logger.error(f"Errore validazione immagine Instagram: {str(e)}")
            return False

    def share_article_on_approval(self, articolo) -> Dict[str, bool]:
        """
        Condivide automaticamente un articolo su Telegram, Facebook e Instagram quando viene approvato
        Twitter è ora gestito automaticamente via RSS + IFTTT

        Args:
            articolo: Istanza del modello Articolo

        Returns:
            Dict con il risultato della condivisione (Telegram, Facebook, Instagram)
        """
        results = {}
        article_url = f"https://ombradelportico.it/articolo/{articolo.slug}/"

        logger.info(f"Avvio condivisione social per articolo: {articolo.titolo} (Twitter via RSS+IFTTT)")

        # Telegram
        if self.platforms['telegram']['enabled']:
            results['telegram'] = self._share_to_telegram(articolo, article_url)
        else:
            logger.info("Condivisione Telegram disabilitata")

        # Facebook
        if self.platforms['facebook']['enabled']:
            results['facebook'] = self._share_to_facebook(articolo, article_url)
        else:
            logger.info("Condivisione Facebook disabilitata")

        # Instagram (solo se c'è un'immagine)
        if self.platforms['instagram']['enabled']:
            if articolo.foto:
                results['instagram'] = self._share_to_instagram(articolo, article_url)
            else:
                logger.warning(f"Condivisione Instagram saltata per '{articolo.titolo}': immagine obbligatoria")
                results['instagram'] = False
        else:
            logger.info("Condivisione Instagram disabilitata")

        # Log risultati
        for platform, success in results.items():
            if success:
                logger.info(f"Articolo '{articolo.titolo}' condiviso con successo su {platform.capitalize()}")
            else:
                logger.warning(f"Condivisione {platform.capitalize()} fallita per articolo '{articolo.titolo}'")

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

    def _share_to_instagram(self, articolo, article_url: str) -> bool:
        """
        Condivide su Instagram tramite Instagram Graph API (processo in 2 fasi)

        Fase 1: Crea un container media (carica immagine + caption)
        Fase 2: Pubblica il container

        IMPORTANTE: Instagram richiede SEMPRE un'immagine. Post solo testo non supportati.
        """
        try:
            config = self.platforms['instagram']
            if not config['access_token'] or not config['account_id']:
                logger.warning("Configurazione Instagram incompleta")
                return False

            # Verifica che ci sia un'immagine
            if not articolo.foto:
                logger.error("Instagram richiede un'immagine - post saltato")
                return False

            # Ottieni Page Access Token (necessario per Instagram)
            page_token = self._get_page_access_token(
                config['access_token'],
                getattr(settings, 'FACEBOOK_PAGE_ID', '')
            )
            if not page_token:
                logger.error("Impossibile ottenere Page Access Token per Instagram")
                return False

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
            image_url = self._get_absolute_image_url(articolo.foto)
            if not image_url:
                logger.error(f"URL immagine non valido: {articolo.foto}")
                return False

            # Verifica aspect ratio Instagram (deve essere tra 0.8 e 1.91)
            if not self._validate_instagram_image(image_url):
                logger.error(f"Immagine non compatibile con Instagram (aspect ratio fuori range 0.8-1.91): {image_url}")
                return False

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
                logger.error(f"Errore creazione container Instagram: {create_response.text}")
                return False

            container_id = create_response.json().get('id')
            if not container_id:
                logger.error("Container ID non ricevuto da Instagram")
                return False

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
                return True
            else:
                logger.error(f"Errore pubblicazione Instagram: {publish_response.text}")
                return False

        except Exception as e:
            logger.error(f"Errore condivisione Instagram per articolo '{articolo.titolo}': {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False

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