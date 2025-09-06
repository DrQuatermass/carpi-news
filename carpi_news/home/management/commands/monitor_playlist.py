import time
from django.core.management.base import BaseCommand
from django.conf import settings
# NOTA: Questo comando è obsoleto - YouTube è ora gestito dal sistema universale


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
        self.stdout.write(
            self.style.WARNING(
                'COMANDO OBSOLETO: Il monitoraggio YouTube è ora gestito automaticamente dal sistema universale.'
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                'YouTube ("L\'Eco del Consiglio") si avvia automaticamente con il server Django.'
            )
        )