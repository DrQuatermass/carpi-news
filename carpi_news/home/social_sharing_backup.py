import logging
import urllib.parse
import requests
import time
from typing import Dict, List, Optional
from django.conf import settings


logger = logging.getLogger(__name__)


class SocialMediaManager:
    """Gestisce la condivisione automatica sui social media"""
    
    def __init__(self):
        # Solo Telegram - Facebook e Twitter ora gestiti via RSS + IFTTT
        self.platforms = {
            'telegram': {
                'name': 'Telegram',
                'enabled': getattr(settings, 'TELEGRAM_AUTO_SHARE', False),
                'bot_token': getattr(settings, 'TELEGRAM_BOT_TOKEN', None),
                'chat_id': getattr(settings, 'TELEGRAM_CHAT_ID', None),
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
    
    def share_article_on_approval(self, articolo) -> Dict[str, bool]:
        """
        Condivide automaticamente un articolo su Telegram quando viene approvato
        Facebook e Twitter sono ora gestiti automaticamente via RSS + IFTTT
        
        Args:
            articolo: Istanza del modello Articolo
            
        Returns:
            Dict con il risultato della condivisione (solo Telegram)
        """
        results = {}
        article_url = f"https://ombradelportico.it/articolo/{articolo.slug}/"
        
        logger.info(f"Avvio condivisione Telegram per articolo: {articolo.titolo} (Facebook/Twitter via RSS+IFTTT)")
        
        # Solo Telegram - altri social gestiti automaticamente via RSS feed
        if self.platforms['telegram']['enabled']:
            results['telegram'] = self._share_to_telegram(articolo, article_url)
        else:
            logger.info("Condivisione Telegram disabilitata - solo RSS feed attivo per altri social")
        
        # Log risultati
        if results.get('telegram'):
            logger.info(f"Articolo '{articolo.titolo}' condiviso con successo su Telegram")
        elif 'telegram' in results:
            logger.warning(f"Condivisione Telegram fallita per articolo '{articolo.titolo}'")
        
        return results
    
    def _share_to_telegram(self, articolo, article_url: str) -> bool:
        """Condivide su Telegram tramite Bot API con foto se disponibile"""
        try:
            config = self.platforms['telegram']
            if not config['bot_token'] or not config['chat_id']:
                logger.warning("Configurazione Telegram incompleta")
                return False
            
            # Prepara il messaggio (ottimizzato per Facebook 2025)
            # Titolo più accattivante con emoji
            emoji = "📰" if articolo.categoria != "Sport" else "⚽"
            title = f"{emoji} {articolo.titolo}"
            
            # Sommario limitato per leggibilità
            summary = articolo.sommario[:180] + "..." if len(articolo.sommario) > 180 else articolo.sommario
            
            # Hashtag specifici per categoria
            hashtags = f"#CarpiNews #OmbraDelPortico"
            if articolo.categoria:
                category_tag = f"#{articolo.categoria.replace(' ', '')}"
                hashtags = f"{category_tag} {hashtags}"
            
            message = f"{title}\n\n{summary}\n\n{hashtags}"
            
            # Parametri per la Graph API (v22.0 è la versione più recente 2025)
            url = f"https://graph.facebook.com/v22.0/{config['page_id']}/feed"
            data = {
                'message': message,
                'link': article_url,
                'access_token': config['access_token']
            }
            
            # Aggiungi immagine se disponibile (migliora engagement)
            if articolo.foto:
                # Facebook preferisce immagini separate dal link per miglior rendering
                absolute_image_url = self._get_absolute_image_url(articolo.foto)
                if absolute_image_url:
                    data['picture'] = absolute_image_url
            
            response = requests.post(url, data=data, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"Articolo condiviso su Facebook: {articolo.titolo}")
                return True
            else:
                logger.error(f"Errore condivisione Facebook: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Errore condivisione Facebook per articolo '{articolo.titolo}': {str(e)}")
            return False
    
    def _share_to_twitter(self, articolo, article_url: str) -> bool:
        """Condivide su Twitter/X tramite API v2"""
        try:
            config = self.platforms['twitter']
            if not all([config['api_key'], config['api_secret'], config['access_token'], config['access_token_secret']]):
                logger.warning("Configurazione Twitter incompleta")
                return False
            
            # Importa tweepy solo se necessario
            try:
                import tweepy
            except ImportError:
                logger.error("tweepy non installato. Installa con: pip install tweepy")
                return False
            
            # Autenticazione
            auth = tweepy.OAuth1UserHandler(
                config['api_key'],
                config['api_secret'],
                config['access_token'],
                config['access_token_secret']
            )
            
            api = tweepy.API(auth)
            client = tweepy.Client(
                consumer_key=config['api_key'],
                consumer_secret=config['api_secret'],
                access_token=config['access_token'],
                access_token_secret=config['access_token_secret']
            )
            
            # Prepara il tweet (max 280 caratteri)
            base_text = f"{articolo.titolo}"
            hashtags = " #CarpiNews #OmbraDelPortico"
            available_chars = 280 - len(article_url) - len(hashtags) - 3  # 3 per spazi
            
            if len(base_text) > available_chars:
                base_text = base_text[:available_chars-3] + "..."
            
            tweet_text = f"{base_text} {article_url}{hashtags}"
            
            # Invia il tweet
            response = client.create_tweet(text=tweet_text)
            
            if response.data:
                logger.info(f"Articolo condiviso su Twitter: {articolo.titolo}")
                return True
            else:
                logger.error(f"Errore condivisione Twitter per articolo '{articolo.titolo}'")
                return False
                
        except Exception as e:
            logger.error(f"Errore condivisione Twitter per articolo '{articolo.titolo}': {str(e)}")
            return False
    
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
    
    def get_platform_status(self) -> Dict[str, Dict]:
        """Restituisce lo stato di configurazione delle piattaforme"""
        status = {}
        for platform_id, config in self.platforms.items():
            is_configured = False
            
            if platform_id == 'facebook':
                is_configured = bool(config['page_id'] and config['access_token'])
            elif platform_id == 'twitter':
                is_configured = bool(all([config['api_key'], config['api_secret'], 
                                       config['access_token'], config['access_token_secret']]))
            elif platform_id == 'telegram':
                is_configured = bool(config['bot_token'] and config['chat_id'])
            
            status[platform_id] = {
                'name': config['name'],
                'enabled': config['enabled'],
                'configured': is_configured,
                'ready': config['enabled'] and is_configured
            }
        
        return status


# Istanza globale del manager
social_manager = SocialMediaManager()