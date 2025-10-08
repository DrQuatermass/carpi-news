from django.core.management.base import BaseCommand
from django.utils import timezone
from home.models import MonitorConfig
from home.monitor_manager import MonitorManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Gestisce i monitor attivi dal database'

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            type=str,
            choices=['start', 'stop', 'status', 'restart'],
            help='Azione da eseguire: start, stop, status, restart'
        )
        parser.add_argument(
            '--monitor',
            type=str,
            help='Nome del monitor specifico (opzionale, altrimenti tutti i monitor attivi)'
        )

    def handle(self, *args, **options):
        action = options['action']
        monitor_name = options.get('monitor')

        if action == 'status':
            self.show_status(monitor_name)
        elif action == 'start':
            self.start_monitors(monitor_name)
        elif action == 'stop':
            self.stop_monitors(monitor_name)
        elif action == 'restart':
            self.restart_monitors(monitor_name)

    def show_status(self, monitor_name=None):
        """Mostra lo stato dei monitor"""
        if monitor_name:
            monitors = MonitorConfig.objects.filter(name=monitor_name)
            if not monitors.exists():
                self.stdout.write(self.style.ERROR(f'Monitor "{monitor_name}" non trovato'))
                return
        else:
            monitors = MonitorConfig.objects.all()

        self.stdout.write(self.style.SUCCESS('\n=== Stato Monitor ===\n'))

        for monitor in monitors:
            status_color = self.style.SUCCESS if monitor.is_active else self.style.ERROR
            status_text = 'ATTIVO' if monitor.is_active else 'DISATTIVO'

            self.stdout.write(f'\n{monitor.name}:')
            self.stdout.write(f'  Stato: {status_color(status_text)}')
            self.stdout.write(f'  Tipo: {monitor.get_scraper_type_display()}')
            self.stdout.write(f'  Categoria: {monitor.category}')
            self.stdout.write(f'  Auto-approve: {"Sì" if monitor.auto_approve else "No"}')
            self.stdout.write(f'  AI Generation: {"Sì" if monitor.use_ai_generation else "No"}')
            if monitor.last_run:
                self.stdout.write(f'  Ultima esecuzione: {monitor.last_run}')
            else:
                self.stdout.write(f'  Ultima esecuzione: Mai')

    def start_monitors(self, monitor_name=None):
        """Avvia i monitor attivi"""
        if monitor_name:
            monitors = MonitorConfig.objects.filter(name=monitor_name, is_active=True)
            if not monitors.exists():
                self.stdout.write(self.style.ERROR(f'Monitor attivo "{monitor_name}" non trovato'))
                return
        else:
            monitors = MonitorConfig.objects.filter(is_active=True)

        if not monitors.exists():
            self.stdout.write(self.style.WARNING('Nessun monitor attivo da avviare'))
            return

        manager = MonitorManager()

        self.stdout.write(self.style.SUCCESS(f'\nAvvio {monitors.count()} monitor...\n'))

        for monitor in monitors:
            try:
                # Converti in SiteConfig
                site_config = monitor.to_site_config()

                # Aggiungi al manager (intervallo di default: 600 secondi)
                interval = monitor.config_data.get('interval', 600)
                success = manager.add_monitor_from_config(site_config, interval)

                if success:
                    self.stdout.write(self.style.SUCCESS(f'✓ {monitor.name} configurato'))
                else:
                    self.stdout.write(self.style.ERROR(f'✗ Errore configurazione {monitor.name}'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ Errore {monitor.name}: {str(e)}'))

        # Avvia tutti i monitor
        try:
            results = manager.start_all_monitors()
            success_count = sum(1 for success in results.values() if success)

            self.stdout.write(self.style.SUCCESS(f'\nMonitor avviati: {success_count}/{len(results)}'))

            # Aggiorna last_run
            for monitor in monitors:
                monitor.last_run = timezone.now()
                monitor.save(update_fields=['last_run'])

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Errore avvio monitor: {str(e)}'))

    def stop_monitors(self, monitor_name=None):
        """Ferma i monitor"""
        if monitor_name:
            monitors = MonitorConfig.objects.filter(name=monitor_name, is_active=True)
        else:
            monitors = MonitorConfig.objects.filter(is_active=True)

        for monitor in monitors:
            monitor.is_active = False
            monitor.save()
            self.stdout.write(self.style.SUCCESS(f'✓ Monitor "{monitor.name}" disattivato'))

        self.stdout.write(self.style.WARNING('\nNota: I processi attivi devono essere terminati manualmente'))

    def restart_monitors(self, monitor_name=None):
        """Riavvia i monitor"""
        self.stdout.write(self.style.WARNING('Arresto monitor...'))
        self.stop_monitors(monitor_name)

        self.stdout.write(self.style.SUCCESS('\nAvvio monitor...'))
        # Riattiva i monitor
        if monitor_name:
            monitors = MonitorConfig.objects.filter(name=monitor_name)
        else:
            monitors = MonitorConfig.objects.all()

        for monitor in monitors:
            monitor.is_active = True
            monitor.save()

        self.start_monitors(monitor_name)
