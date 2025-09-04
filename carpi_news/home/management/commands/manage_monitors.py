from django.core.management.base import BaseCommand
from django.utils import timezone
import time
import signal
import sys

class Command(BaseCommand):
    help = 'Gestione dei monitor universali (start/stop/status)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            choices=['start', 'stop', 'status', 'restart'],
            help='Azione da eseguire sui monitor'
        )
        parser.add_argument(
            '--monitor',
            type=str,
            help='Nome specifico del monitor (opzionale)'
        )
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Avvia in modalità daemon (solo per start)'
        )

    def handle(self, *args, **options):
        action = options['action']
        monitor_name = options.get('monitor')
        daemon_mode = options.get('daemon', False)
        
        self.stdout.write(
            self.style.SUCCESS(f'=== GESTIONE MONITOR UNIVERSALI - {action.upper()} ===')
        )
        
        if action == 'start':
            self.start_monitors(monitor_name, daemon_mode)
        elif action == 'stop':
            self.stop_monitors(monitor_name)
        elif action == 'status':
            self.show_status(monitor_name)
        elif action == 'restart':
            self.restart_monitors(monitor_name)
    
    def start_monitors(self, specific_monitor=None, daemon_mode=False):
        """Avvia i monitor universali"""
        try:
            from home.monitor_manager import MonitorManager
            from home.monitor_configs import get_config, list_configs
            
            manager = MonitorManager()
            
            # Configurazioni disponibili
            all_configs = [
                ('carpi_calcio', 900),     # 15 minuti
                ('comune_carpi', 1200),    # 20 minuti
            ]
            
            # Filtra per monitor specifico se richiesto
            if specific_monitor:
                configs_to_start = [(name, interval) for name, interval in all_configs 
                                   if name == specific_monitor]
                if not configs_to_start:
                    self.stdout.write(
                        self.style.ERROR(f'Monitor "{specific_monitor}" non trovato')
                    )
                    return
            else:
                configs_to_start = all_configs
            
            # Aggiungi e avvia monitor
            started_count = 0
            for config_name, interval in configs_to_start:
                try:
                    # Verifica configurazione
                    config = get_config(config_name)
                    
                    # Aggiungi al manager
                    success = manager.add_monitor(config_name, interval)
                    if success:
                        self.stdout.write(f'  [OK] Monitor {config_name} configurato')
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'  [WARN] Monitor {config_name} già configurato o errore')
                        )
                        
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'  [ERROR] Errore configurazione {config_name}: {e}')
                    )
                    continue
            
            # Avvia tutti i monitor
            self.stdout.write('\nAvvio dei monitor...')
            results = manager.start_all_monitors()
            
            for monitor_name, started in results.items():
                if started:
                    self.stdout.write(
                        self.style.SUCCESS(f'  [OK] {monitor_name}: Avviato con successo')
                    )
                    started_count += 1
                else:
                    self.stdout.write(
                        self.style.ERROR(f'  [ERROR] {monitor_name}: Errore nell\'avvio')
                    )
            
            if started_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'\n{started_count}/{len(results)} monitor avviati con successo')
                )
                
                if daemon_mode:
                    self.stdout.write('\nModalità daemon attivata. Premi Ctrl+C per fermare...')
                    try:
                        # Gestore per chiusura pulita
                        def signal_handler(signum, frame):
                            self.stdout.write('\n\nChiusura dei monitor...')
                            manager.stop_all_monitors()
                            sys.exit(0)
                        
                        signal.signal(signal.SIGINT, signal_handler)
                        
                        # Loop infinito per mantenere attivi i monitor
                        while True:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        self.stdout.write('\nChiusura dei monitor...')
                        manager.stop_all_monitors()
                else:
                    self.stdout.write(
                        self.style.SUCCESS('Monitor avviati in background. Usa "manage_monitors stop" per fermarli.')
                    )
            else:
                self.stdout.write(
                    self.style.ERROR('Nessun monitor avviato con successo')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Errore nell\'avvio: {e}')
            )
    
    def stop_monitors(self, specific_monitor=None):
        """Ferma i monitor universali"""
        self.stdout.write('Comando stop non ancora implementato (i monitor sono daemon threads)')
        self.stdout.write('Per fermare i monitor, riavvia il server Django')
    
    def show_status(self, specific_monitor=None):
        """Mostra lo stato dei monitor"""
        try:
            from home.models import Articolo
            from home.monitor_configs import list_configs
            
            self.stdout.write('=== STATO SISTEMA ===\n')
            
            # Statistiche database
            total_articles = Articolo.objects.count()
            approved_articles = Articolo.objects.filter(approvato=True).count()
            
            self.stdout.write(f'Database:')
            self.stdout.write(f'  Totale articoli: {total_articles}')
            self.stdout.write(f'  Articoli approvati: {approved_articles}')
            
            # Articoli per categoria
            categories = Articolo.objects.values_list('categoria', flat=True).distinct()
            for category in categories:
                count = Articolo.objects.filter(categoria=category).count()
                self.stdout.write(f'  Categoria "{category}": {count} articoli')
            
            # Configurazioni disponibili
            self.stdout.write(f'\nConfigurazioni monitor disponibili:')
            configs = list_configs()
            for config_name in configs:
                self.stdout.write(f'  - {config_name}')
            
            # Ultimi articoli
            latest = Articolo.objects.order_by('-data_creazione')[:5]
            self.stdout.write(f'\nUltimi 5 articoli creati:')
            for article in latest:
                status = '[APPROVATO]' if article.approvato else '[IN ATTESA]'
                date_str = article.data_creazione.strftime('%d/%m/%Y %H:%M')
                self.stdout.write(f'  {date_str} - {article.titolo[:50]}... {status}')
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Errore nel recupero stato: {e}')
            )
    
    def restart_monitors(self, specific_monitor=None):
        """Riavvia i monitor"""
        self.stdout.write('Riavvio monitor...')
        self.stop_monitors(specific_monitor)
        time.sleep(2)
        self.start_monitors(specific_monitor)