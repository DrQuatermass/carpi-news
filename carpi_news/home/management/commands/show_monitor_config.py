from django.core.management.base import BaseCommand
from home.models import MonitorConfig
import json


class Command(BaseCommand):
    help = 'Mostra la configurazione di un monitor'

    def add_arguments(self, parser):
        parser.add_argument('monitor_name', type=str, help='Nome del monitor')

    def handle(self, *args, **options):
        monitor_name = options['monitor_name']

        try:
            monitor = MonitorConfig.objects.get(name=monitor_name)

            self.stdout.write(self.style.SUCCESS(f'\n=== Configurazione: {monitor.name} ===\n'))
            self.stdout.write(f'Tipo: {monitor.get_scraper_type_display()}')
            self.stdout.write(f'Base URL: {monitor.base_url}')
            self.stdout.write(f'Categoria: {monitor.category}')
            self.stdout.write(f'Attivo: {"Sì" if monitor.is_active else "No"}')
            self.stdout.write(f'Auto-approve: {"Sì" if monitor.auto_approve else "No"}')
            self.stdout.write(f'AI Generation: {"Sì" if monitor.use_ai_generation else "No"}')
            self.stdout.write(f'Web Search: {"Sì" if monitor.enable_web_search else "No"}')

            self.stdout.write('\n=== Config Data (JSON) ===')
            self.stdout.write(json.dumps(monitor.config_data, indent=2, ensure_ascii=False))

            if monitor.ai_system_prompt:
                self.stdout.write('\n=== AI System Prompt ===')
                self.stdout.write(monitor.ai_system_prompt)

        except MonitorConfig.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Monitor "{monitor_name}" non trovato'))
