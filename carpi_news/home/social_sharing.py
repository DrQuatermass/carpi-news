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
        self.platforms = {
            'facebook': {
                'name': 'Facebook',
                'enabled': getattr(settings, 'FACEBOOK_AUTO_SHARE', False),
                'page_id': getattr(settings, 'FACEBOOK_PAGE_ID', None),
                'access_token': getattr(settings, 'FACEBOOK_ACCESS_TOKEN', None),
            },
            'twitter': {
                'name': 'Twitter/X',
                'enabled': getattr(settings, 'TWITTER_AUTO_SHARE', False),
                'api_key': getattr(settings, 'TWITTER_API_KEY', None),
                'api_secret': getattr(settings, 'TWITTER_API_SECRET', None),
                'access_token': getattr(settings, 'TWITTER_ACCESS_TOKEN', None),
                'access_token_secret': getattr(settings, 'TWITTER_ACCESS_TOKEN_SECRET', None),
            },
            'telegram': {
                'name': 'Telegram',
                'enabled': getattr(settings, 'TELEGRAM_AUTO_SHARE', False),
                'bot_token': getattr(settings, 'TELEGRAM_BOT_TOKEN', None),
                'chat_id': getattr(settings, 'TELEGRAM_CHAT_ID', None),
            }
        }
    
    def share_article_on_approval(self, articolo) -> Dict[str, bool]:
        """
        Condivide automaticamente un articolo sui social quando viene approvato
        
        Args:
            articolo: Istanza del modello Articolo
            
        Returns:
            Dict con il risultato della condivisione per ogni piattaforma
        """
        results = {}
        article_url = f"https://ombradelportico.it/articolo/{articolo.slug}/"
        
        logger.info(f"Avvio condivisione automatica per articolo: {articolo.titolo}")
        
        # Facebook
        if self.platforms['facebook']['enabled']:
            results['facebook'] = self._share_to_facebook(articolo, article_url)
        
        # Twitter/X
        if self.platforms['twitter']['enabled']:
            results['twitter'] = self._share_to_twitter(articolo, article_url)
        
        # Telegram
        if self.platforms['telegram']['enabled']:
            results['telegram'] = self._share_to_telegram(articolo, article_url)
        
        # Log risultati
        successful_shares = [platform for platform, success in results.items() if success]
        failed_shares = [platform for platform, success in results.items() if not success]
        
        if successful_shares:
            logger.info(f"Articolo '{articolo.titolo}' condiviso con successo su: {', '.join(successful_shares)}")
        
        if failed_shares:
            logger.warning(f"Condivisione fallita per articolo '{articolo.titolo}' su: {', '.join(failed_shares)}")
        
        return results
    
    def _share_to_facebook(self, articolo, article_url: str) -> bool:
        """Condivide su Facebook tramite Graph API"""
        try:
            config = self.platforms['facebook']
            if not config['page_id'] or not config['access_token']:
                logger.warning("Configurazione Facebook incompleta")
                return False
            
            # Prepara il messaggio
            message = f"{articolo.titolo}\n\n{articolo.sommario[:200]}...\n\n#CarpiNews #OmbraDelPortico"
            
            # Parametri per la Graph API
            url = f"https://graph.facebook.com/v18.0/{config['page_id']}/feed"
            data = {
                'message': message,
                'link': article_url,
                'access_token': config['access_token']
            }
            
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
                # URL dell'API Telegram per inviare foto
                url = f"https://api.telegram.org/bot{config['bot_token']}/sendPhoto"
                
                data = {
                    'chat_id': config['chat_id'],
                    'photo': articolo.foto,
                    'caption': message,
                    'parse_mode': 'Markdown'
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