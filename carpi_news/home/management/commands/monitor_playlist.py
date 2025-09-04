import time
from django.core.management.base import BaseCommand
from django.conf import settings
from home.playlist_monitor import YouTubePlaylistMonitor


class Command(BaseCommand):
    help = 'Monitora una playlist YouTube per nuovi video'

    def add_arguments(self, parser):
        parser.add_argument(
            '--playlist-id',
            type=str,
            default=settings.YOUTUBE_PLAYLIST_ID,
            help='ID della playlist YouTube da monitorare'
        )
        parser.add_argument(
            '--api-key',
            type=str,
            default=settings.YOUTUBE_API_KEY,
            help='YouTube API key'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=300,
            help='Intervallo di controllo in secondi (default: 300 = 5 minuti)'
        )

    def handle(self, *args, **options):
        playlist_id = options['playlist_id']
        api_key = options['api_key']
        interval = options['interval']
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Avvio monitor playlist {playlist_id} ogni {interval} secondi'
            )
        )
        
        monitor = YouTubePlaylistMonitor(playlist_id, api_key, interval)
        monitor.start_monitoring()
        
        try:
            # Mantieni il comando attivo
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop_monitoring()
            self.stdout.write(
                self.style.SUCCESS('Monitor fermato dall\'utente')
            )