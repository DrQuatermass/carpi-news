"""Crea i monitor WordPress di teatro, biblioteca Loria e Fondazione CR Carpi (dal 7/11/2026).

    python manage.py crea_monitor_cultura              # crea i monitor attivi
    python manage.py crea_monitor_cultura --disattivi  # crea i monitor spenti

Leggono gli articoli normali (post) dalla REST API WordPress, come Comune Carpi e Terre
d'Argine: titolo, testo, immagine principale e link. Le notizie arrivano grezze, da
rielaborare con l'AI. per_page=5: al primo giro entrano gli ultimi 5 articoli di ogni sito
(lo scraper WordPress non ha un limite di eta'), poi solo i nuovi.
Gli spettacoli in calendario del teatro si caricano a parte con importa_spettacoli_teatro.

I monitor gia' presenti (stesso nome) non vengono toccati.
"""
from django.core.management.base import BaseCommand

from home.models import MonitorConfig
from home.prompt_redazione import NOTE_MONITOR

MONITOR = [
    ('Teatro Comunale Carpi', 'https://teatrocarpi.it/', 'Cultura & Eventi'),
    ('Biblioteca Loria', 'https://www.bibliotecaloria.it/', 'Cultura & Eventi'),
    ('Fondazione CR Carpi', 'https://www.fondazionecrcarpi.it/', 'Attualità'),
]


class Command(BaseCommand):
    help = "Crea i monitor di Teatro Comunale, Biblioteca Loria e Fondazione CR Carpi"

    def add_arguments(self, parser):
        parser.add_argument('--disattivi', action='store_true',
                            help="Crea i monitor spenti (da accendere dall'admin)")

    def handle(self, *args, **opts):
        for nome, url, categoria in MONITOR:
            monitor, creato = MonitorConfig.objects.get_or_create(
                name=nome,
                defaults={
                    'base_url': url,
                    'scraper_type': 'wordpress_api',
                    'category': categoria,
                    'is_active': not opts['disattivi'],
                    'auto_approve': False,
                    'use_ai_generation': False,
                    'enable_web_search': True,
                    'ai_system_prompt': NOTE_MONITOR[nome].strip(),
                    # Siti che pubblicano poche volte al mese: un controllo all'ora basta
                    'config_data': {'interval': 3600, 'per_page': 5},
                },
            )
            stato = 'creato' if creato else "gia' presente, non modificato"
            self.stdout.write(f"{nome}: {stato} ({monitor.base_url})")
