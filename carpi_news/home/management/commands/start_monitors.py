from django.core.management.base import BaseCommand
from django.utils import timezone
from home.models import MonitorConfig
from home.monitor_manager import MonitorManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Avvia i monitor attivi dal database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--monitor',
            type=str,
            help='Nome del monitor specifico da avviare (opzionale)'
        )
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Esegui in modalità daemon (continua in esecuzione)'
        )

    def handle(self, *args, **options):
        monitor_name = options.get('monitor')
        daemon_mode = options.get('daemon', False)

        # Carica monitor attivi dal database
        if monitor_name:
            monitors = MonitorConfig.objects.filter(name=monitor_name, is_active=True)
            if not monitors.exists():
                self.stdout.write(self.style.ERROR(f'Monitor attivo "{monitor_name}" non trovato'))
                return
        else:
            monitors = MonitorConfig.objects.filter(is_active=True).order_by('name')

        if not monitors.exists():
            self.stdout.write(self.style.WARNING('Nessun monitor attivo trovato nel database'))
            self.stdout.write('\nSuggerimento: Attiva i monitor dall\'admin o importali con:')
            self.stdout.write('  python manage.py import_monitors')
            return

        self.stdout.write(self.style.SUCCESS(f'\n=== Avvio {monitors.count()} Monitor dal Database ===\n'))

        # Crea manager
        manager = MonitorManager()

        added_count = 0
        for monitor_config in monitors:
            try:
                # Converti in SiteConfig
                site_config = monitor_config.to_site_config()

                # Ottieni intervallo dalla configurazione
                interval = monitor_config.config_data.get('interval', 600)

                # Aggiungi al manager
                success = manager.add_monitor_from_config(site_config, interval)

                if success:
                    added_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'[OK] {monitor_config.name} - Intervallo: {interval}s - '
                            f'Tipo: {monitor_config.get_scraper_type_display()}'
                        )
                    )
                else:
                    self.stdout.write(self.style.ERROR(f'[ERRORE] Impossibile aggiungere {monitor_config.name}'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'[ERRORE] {monitor_config.name}: {str(e)}'))

        if added_count == 0:
            self.stdout.write(self.style.ERROR('\nNessun monitor aggiunto al manager'))
            return

        # Avvia tutti i monitor
        self.stdout.write(self.style.SUCCESS(f'\n=== Avvio {added_count} Monitor ===\n'))

        try:
            # Avvia monitor come thread NON-daemon di default (continueranno dopo che il comando termina)
            # Solo se l'utente specifica --daemon, usa daemon mode
            results = manager.start_all_monitors(daemon=daemon_mode)
            success_count = sum(1 for success in results.values() if success)

            for monitor_name, started in results.items():
                if started:
                    self.stdout.write(self.style.SUCCESS(f'[OK] {monitor_name} avviato'))
                else:
                    self.stdout.write(self.style.ERROR(f'[ERRORE] {monitor_name} fallito'))

            # Aggiorna last_run per i monitor avviati
            if success_count > 0:
                monitors.update(last_run=timezone.now())

            self.stdout.write(self.style.SUCCESS(f'\n=== Riepilogo ==='))
            self.stdout.write(self.style.SUCCESS(f'Monitor avviati con successo: {success_count}/{len(results)}'))

            if daemon_mode:
                self.stdout.write(self.style.WARNING('\nModalità daemon attiva - I monitor continuano in esecuzione...'))
                self.stdout.write('Premi Ctrl+C per fermare')
                try:
                    import time
                    while True:
                        time.sleep(60)
                except KeyboardInterrupt:
                    self.stdout.write(self.style.WARNING('\nArresto monitor...'))
                    return
            else:
                self.stdout.write(self.style.SUCCESS('\nMonitor avviati in background'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nErrore nell\'avvio dei monitor: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
