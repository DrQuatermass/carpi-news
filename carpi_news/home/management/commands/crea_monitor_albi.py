"""Crea i monitor degli albi pretori delle Terre d'Argine (piattaforma Italsoft).

    python manage.py crea_monitor_albi            # Carpi e Unione Terre d'Argine
    python manage.py crea_monitor_albi --tutti    # anche Campogalliano, Novi e Soliera

I monitor gia' presenti (stesso nome) non vengono toccati.
"""
from django.core.management.base import BaseCommand

from home.models import MonitorConfig
from home.prompt_redazione import NOTE_FONTE

ALBO_URL = 'https://trasparenza.terredargine.it/{sigla}/?page_id=740'

ALBI = [
    ('Albo Pretorio Comune di Carpi', 'carpi'),
    ("Albo Pretorio Unione Terre d'Argine", 'unioneterredargine'),
]
ALBI_ALTRI_COMUNI = [
    ('Albo Pretorio Comune di Campogalliano', 'campogalliano'),
    ('Albo Pretorio Comune di Novi di Modena', 'novi'),
    ('Albo Pretorio Comune di Soliera', 'soliera'),
]


class Command(BaseCommand):
    help = "Crea i monitor degli albi pretori (Carpi e Unione; --tutti anche gli altri comuni)"

    def add_arguments(self, parser):
        parser.add_argument('--tutti', action='store_true',
                            help='Anche Campogalliano, Novi di Modena e Soliera')
        parser.add_argument('--disattivi', action='store_true',
                            help='Crea i monitor spenti (da accendere dall\'admin)')

    def handle(self, *args, **opts):
        albi = ALBI + (ALBI_ALTRI_COMUNI if opts['tutti'] else [])
        for nome, sigla in albi:
            monitor, creato = MonitorConfig.objects.get_or_create(
                name=nome,
                defaults={
                    'base_url': ALBO_URL.format(sigla=sigla),
                    'scraper_type': 'albo_italsoft',
                    'category': 'Attualità',
                    'is_active': not opts['disattivi'],
                    'auto_approve': False,
                    'use_ai_generation': False,
                    'enable_web_search': True,
                    'ai_system_prompt': NOTE_FONTE['albo'].strip(),
                    # Gli albi cambiano poche volte al giorno; max_giorni=1 al primo avvio
                    # importa solo gli atti di oggi e ieri, non tutte le pubblicazioni in corso
                    'config_data': {'interval': 3600, 'max_giorni': 1},
                },
            )
            stato = 'creato' if creato else 'gia\' presente, non modificato'
            self.stdout.write(f"{nome}: {stato} ({monitor.base_url})")
