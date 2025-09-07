from django.core.management.base import BaseCommand
from django.utils import timezone
from home.models import Articolo
from home.social_sharing import social_manager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Testa il sistema di condivisione automatica sui social'

    def add_arguments(self, parser):
        parser.add_argument(
            '--article-id',
            type=int,
            help='ID specifico dell\'articolo da condividere (opzionale)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula la condivisione senza inviare realmente',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Mostra solo lo stato delle configurazioni social',
        )

    def handle(self, *args, **options):
        if options['status']:
            self.show_social_status()
            return
            
        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING('MODALITÀ DRY-RUN - Nessuna condivisione reale verrà effettuata')
            )
        
        # Ottieni articolo da testare
        if options['article_id']:
            try:
                articolo = Articolo.objects.get(id=options['article_id'], approvato=True)
                self.stdout.write(f"Test condivisione per articolo specifico: {articolo.titolo}")
            except Articolo.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Articolo con ID {options["article_id"]} non trovato o non approvato')
                )
                return
        else:
            # Usa l'ultimo articolo approvato
            articolo = Articolo.objects.filter(approvato=True).order_by('-data_pubblicazione').first()
            if not articolo:
                self.stdout.write(
                    self.style.ERROR('Nessun articolo approvato trovato per il test')
                )
                return
            self.stdout.write(f"Test condivisione per ultimo articolo approvato: {articolo.titolo}")
        
        # Mostra info articolo
        self.stdout.write(f"Articolo: {articolo.titolo}")
        self.stdout.write(f"Slug: {articolo.slug}")
        self.stdout.write(f"Categoria: {articolo.categoria}")
        self.stdout.write(f"Data pubblicazione: {articolo.data_pubblicazione}")
        self.stdout.write(f"URL: https://carpinews.it/articolo/{articolo.slug}/")
        self.stdout.write("")
        
        # Test della condivisione
        if not options['dry_run']:
            self.stdout.write("Avvio condivisione...")
            results = social_manager.share_article_on_approval(articolo)
            
            # Mostra risultati
            self.stdout.write(self.style.SUCCESS("Risultati condivisione:"))
            for platform, success in results.items():
                status = "OK - Successo" if success else "ERROR - Fallito"
                style = self.style.SUCCESS if success else self.style.ERROR
                self.stdout.write(f"  {platform}: {style(status)}")
        else:
            # Simula la condivisione
            self.stdout.write("Simulazione condivisione (dry-run)...")
            status = social_manager.get_platform_status()
            
            for platform_id, config in status.items():
                if config['enabled'] and config['configured']:
                    self.stdout.write(f"  {config['name']}: {self.style.SUCCESS('OK - Sarebbe condiviso')}")
                elif config['enabled']:
                    self.stdout.write(f"  {config['name']}: {self.style.WARNING('WARN - Abilitato ma non configurato')}")
                else:
                    self.stdout.write(f"  {config['name']}: {self.style.ERROR('X - Disabilitato')}")

    def show_social_status(self):
        """Mostra lo stato delle configurazioni social"""
        self.stdout.write(self.style.SUCCESS("=== STATO CONFIGURAZIONI SOCIAL MEDIA ==="))
        
        status = social_manager.get_platform_status()
        
        for platform_id, config in status.items():
            self.stdout.write(f"\n{config['name'].upper()}:")
            self.stdout.write(f"  Abilitato: {'Sì' if config['enabled'] else 'No'}")
            self.stdout.write(f"  Configurato: {'Sì' if config['configured'] else 'No'}")
            self.stdout.write(f"  Pronto: {'Sì' if config['ready'] else 'No'}")
            
            # Mostra dettagli configurazione
            platform_config = social_manager.platforms[platform_id]
            if platform_id == 'facebook':
                self.stdout.write(f"  Page ID: {'OK - Impostato' if platform_config['page_id'] else 'X - Mancante'}")
                self.stdout.write(f"  Access Token: {'OK - Impostato' if platform_config['access_token'] else 'X - Mancante'}")
            elif platform_id == 'twitter':
                self.stdout.write(f"  API Key: {'OK - Impostata' if platform_config['api_key'] else 'X - Mancante'}")
                self.stdout.write(f"  API Secret: {'OK - Impostato' if platform_config['api_secret'] else 'X - Mancante'}")
                self.stdout.write(f"  Access Token: {'OK - Impostato' if platform_config['access_token'] else 'X - Mancante'}")
                self.stdout.write(f"  Access Token Secret: {'OK - Impostato' if platform_config['access_token_secret'] else 'X - Mancante'}")
            elif platform_id == 'telegram':
                self.stdout.write(f"  Bot Token: {'OK - Impostato' if platform_config['bot_token'] else 'X - Mancante'}")
                self.stdout.write(f"  Chat ID: {'OK - Impostato' if platform_config['chat_id'] else 'X - Mancante'}")
        
        # Statistiche generali
        enabled_count = sum(1 for config in status.values() if config['enabled'])
        ready_count = sum(1 for config in status.values() if config['ready'])
        
        self.stdout.write(f"\n=== RIEPILOGO ===")
        self.stdout.write(f"Piattaforme abilitate: {enabled_count}/{len(status)}")
        self.stdout.write(f"Piattaforme pronte: {ready_count}/{len(status)}")
        
        if ready_count == 0:
            self.stdout.write(
                self.style.WARNING(
                    "\nWARN - NESSUNA PIATTAFORMA CONFIGURATA - La condivisione automatica non funzionera."
                )
            )
            self.stdout.write("Configura almeno una piattaforma nel file .env per abilitare la condivisione automatica.")
        elif ready_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nOK - {ready_count} piattaforma/e pronta/e per la condivisione automatica!"
                )
            )