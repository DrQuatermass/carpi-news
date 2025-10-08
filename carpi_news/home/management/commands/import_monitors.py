from django.core.management.base import BaseCommand
from django.db import IntegrityError
from home.models import MonitorConfig
from home.monitor_configs import MONITOR_CONFIGS
import json


class Command(BaseCommand):
    help = 'Importa i monitor esistenti da monitor_configs.py nel database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help='Aggiorna i monitor esistenti invece di saltarli'
        )
        parser.add_argument(
            '--delete-existing',
            action='store_true',
            help='Elimina tutti i monitor esistenti prima di importare'
        )

    def handle(self, *args, **options):
        update_existing = options['update']
        delete_existing = options['delete_existing']

        if delete_existing:
            confirm = input('Sei sicuro di voler eliminare tutti i monitor esistenti? (yes/no): ')
            if confirm.lower() == 'yes':
                count = MonitorConfig.objects.all().delete()[0]
                self.stdout.write(self.style.WARNING(f'Eliminati {count} monitor esistenti'))
            else:
                self.stdout.write(self.style.ERROR('Operazione annullata'))
                return

        self.stdout.write(self.style.SUCCESS(f'\n=== Importazione Monitor da monitor_configs.py ===\n'))

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Mappa degli intervalli di default (da apps.py)
        default_intervals = {
            'carpi_calcio': 300,
            'comune_carpi_graphql': 600,
            'eventi_carpi_graphql': 1800,
            'ansa_carpi': 300,
            'youtube_playlist': 1800,
            'youtube_playlist_2': 1800,
            'temponews': 600,
            'voce_carpi': 600,
            'voce_carpi_sport': 600,
            'terre_argine': 900,
            'novi_modena': 900,
            'soliera': 900,
            'campogalliano': 900,
            'questura_modena': 600,
            'email_comunicati': 300,
        }

        for config_key, site_config in MONITOR_CONFIGS.items():
            try:
                # Prepara i dati di configurazione specifica preservando TUTTE le impostazioni attuali
                config_data = {
                    'interval': default_intervals.get(config_key, 600),
                }

                # Lista di tutti gli attributi da preservare dal SiteConfig
                all_config_attrs = [
                    # HTML scraping
                    'news_url', 'rss_url', 'disable_rss', 'selectors', 'content_selectors',
                    'image_selectors', 'content_filter_keywords', 'url_filter_keywords',

                    # WordPress API
                    'per_page', 'api_url',

                    # YouTube API
                    'api_key', 'playlist_id', 'max_results', 'transcript_delay',
                    'live_stream_retry_delay',

                    # GraphQL
                    'graphql_endpoint', 'graphql_headers', 'graphql_query',
                    'graphql_operation_name', 'graphql_variables', 'fallback_to_wordpress',
                    'wordpress_config', 'download_images',

                    # Email
                    'imap_server', 'imap_port', 'email', 'password', 'mailbox',
                    'sender_filter', 'subject_filter', 'ai_twitter_prompt'
                ]

                # Copia tutti gli attributi presenti nel SiteConfig
                # Nota: SiteConfig salva tutti i kwargs in site_config.config
                for attr in all_config_attrs:
                    if attr in site_config.config:
                        value = site_config.config[attr]
                        # Includi solo se il valore non è None, stringa vuota o lista vuota
                        if value is not None and value != '' and value != []:
                            config_data[attr] = value

                # Dati del monitor con tutte le impostazioni attuali
                # Nota: SiteConfig salva tutti i parametri extra in site_config.config
                monitor_data = {
                    'name': site_config.name,
                    'base_url': site_config.base_url,
                    'scraper_type': site_config.scraper_type,
                    'category': site_config.category,
                    'is_active': True,  # Default attivo
                    'auto_approve': site_config.config.get('auto_approve', False),
                    'use_ai_generation': site_config.config.get('use_ai_generation', False),
                    'enable_web_search': site_config.config.get('enable_web_search', False),
                    'ai_system_prompt': site_config.config.get('ai_system_prompt', ''),
                    'config_data': config_data,
                }

                # Controlla se esiste già
                existing = MonitorConfig.objects.filter(name=site_config.name).first()

                if existing:
                    if update_existing:
                        # Aggiorna preservando tutte le configurazioni
                        for key, value in monitor_data.items():
                            setattr(existing, key, value)
                        existing.save()
                        updated_count += 1
                        self.stdout.write(self.style.SUCCESS(f'[OK] Aggiornato: {site_config.name}'))

                        # Mostra le configurazioni importate
                        self.stdout.write(f'     Intervallo: {config_data.get("interval")}s')
                        self.stdout.write(f'     AI Generation: {"Si" if monitor_data["use_ai_generation"] else "No"}')
                        self.stdout.write(f'     Web Search: {"Si" if monitor_data["enable_web_search"] else "No"}')
                        if config_data.get('news_url'):
                            self.stdout.write(f'     News URL: {config_data["news_url"]}')
                        if config_data.get('api_url'):
                            self.stdout.write(f'     API URL: {config_data["api_url"]}')
                        if config_data.get('graphql_endpoint'):
                            self.stdout.write(f'     GraphQL Endpoint: {config_data["graphql_endpoint"]}')
                    else:
                        skipped_count += 1
                        self.stdout.write(self.style.WARNING(f'[SKIP] Saltato (esiste gia): {site_config.name}'))
                else:
                    # Crea nuovo con tutte le configurazioni
                    MonitorConfig.objects.create(**monitor_data)
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f'[OK] Creato: {site_config.name}'))

                    # Mostra le configurazioni importate
                    self.stdout.write(f'     Tipo: {site_config.scraper_type}')
                    self.stdout.write(f'     Intervallo: {config_data.get("interval")}s')
                    self.stdout.write(f'     Categoria: {monitor_data["category"]}')
                    self.stdout.write(f'     AI Generation: {"Si" if monitor_data["use_ai_generation"] else "No"}')

                    # Mostra configurazioni specifiche in base al tipo
                    if site_config.scraper_type == 'html' and config_data.get('news_url'):
                        self.stdout.write(f'     News URL: {config_data["news_url"]}')
                        if config_data.get('selectors'):
                            self.stdout.write(f'     Selectors: {len(config_data["selectors"])} definiti')
                    elif site_config.scraper_type == 'wordpress_api' and config_data.get('api_url'):
                        self.stdout.write(f'     API URL: {config_data["api_url"]}')
                    elif site_config.scraper_type == 'youtube_api' and config_data.get('playlist_id'):
                        self.stdout.write(f'     Playlist ID: {config_data["playlist_id"]}')
                    elif site_config.scraper_type == 'graphql' and config_data.get('graphql_endpoint'):
                        self.stdout.write(f'     GraphQL Endpoint: {config_data["graphql_endpoint"]}')
                    elif site_config.scraper_type == 'email' and config_data.get('imap_server'):
                        self.stdout.write(f'     IMAP Server: {config_data["imap_server"]}')

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'[ERRORE] con {site_config.name}: {str(e)}'))
                import traceback
                self.stdout.write(traceback.format_exc())

        # Riepilogo
        self.stdout.write(self.style.SUCCESS(f'\n=== Riepilogo ==='))
        self.stdout.write(self.style.SUCCESS(f'[OK] Monitor creati: {created_count}'))
        if update_existing:
            self.stdout.write(self.style.SUCCESS(f'[OK] Monitor aggiornati: {updated_count}'))
        self.stdout.write(self.style.WARNING(f'[SKIP] Monitor saltati: {skipped_count}'))
        self.stdout.write(self.style.SUCCESS(f'\nTotale monitor in database: {MonitorConfig.objects.count()}'))
