"""
Comando per generare automaticamente l'articolo giornaliero "Cosa fare oggi?"

Raccoglie tutti gli eventi del giorno dalle categorie Cultura ed Eventi
e li aggrega in un unico articolo con link ai dettagli.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models
from home.models import Articolo
from datetime import date
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Genera l\'articolo giornaliero "Cosa fare oggi?" con gli eventi del giorno'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data',
            type=str,
            help='Data specifica (YYYY-MM-DD). Default: oggi',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra l\'anteprima senza salvare',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Determina la data target
        if options['data']:
            try:
                target_date = date.fromisoformat(options['data'])
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Formato data non valido: {options["data"]}. Usa YYYY-MM-DD'))
                return
        else:
            target_date = date.today()

        self.stdout.write(f'\n{"="*70}')
        self.stdout.write(self.style.WARNING(f'Generazione "Cosa fare oggi?" per {target_date.strftime("%d/%m/%Y")}'))
        if dry_run:
            self.stdout.write(self.style.WARNING('MODALITÀ DRY-RUN: Nessuna modifica verrà salvata'))
        self.stdout.write(f'{"="*70}\n')

        # Cerca eventi per la data target nelle categorie Cultura ed Eventi
        eventi_query = Articolo.objects.filter(
            data_evento=target_date,
            approvato=True
        ).filter(
            models.Q(categoria__icontains='Cultura') |
            models.Q(categoria__icontains='Eventi')
        ).order_by('titolo')

        eventi = list(eventi_query)

        if not eventi:
            self.stdout.write(self.style.WARNING(f'[X] Nessun evento trovato per il {target_date.strftime("%d/%m/%Y")}'))
            self.stdout.write('  Verifica che gli articoli abbiano:')
            self.stdout.write('  - Categoria "Cultura" o "Eventi"')
            self.stdout.write('  - Campo data_evento compilato')
            self.stdout.write('  - Stato approvato=True')
            return

        self.stdout.write(self.style.SUCCESS(f'[OK] Trovati {len(eventi)} eventi per oggi:\n'))
        for evento in eventi:
            self.stdout.write(f'  • {evento.titolo} ({evento.categoria})')

        # Genera il contenuto dell'articolo
        titolo = self.genera_titolo(target_date)
        contenuto = self.genera_contenuto(eventi, target_date)
        sommario = self.genera_sommario(eventi, target_date)

        if dry_run:
            self.stdout.write('\n' + '='*70)
            self.stdout.write(self.style.SUCCESS('ANTEPRIMA ARTICOLO:'))
            self.stdout.write('='*70)
            self.stdout.write(f'\nTITOLO: {titolo}\n')
            self.stdout.write(f'SOMMARIO:\n{sommario}\n')
            self.stdout.write(f'CONTENUTO:\n{contenuto}\n')
            self.stdout.write('='*70)
            self.stdout.write(self.style.WARNING('\nEsegui senza --dry-run per salvare l\'articolo'))
            return

        # Crea l'articolo
        articolo = Articolo.objects.create(
            titolo=titolo,
            contenuto=contenuto,
            sommario=sommario,
            categoria='Cosa fare oggi?',
            approvato=True,
            data_pubblicazione=timezone.now()
        )

        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS(f'[OK] Articolo creato con successo!'))
        self.stdout.write(f'  ID: {articolo.id}')
        self.stdout.write(f'  Slug: {articolo.slug}')
        self.stdout.write(f'  URL: /articolo/{articolo.slug}/')
        self.stdout.write(f'  Eventi inclusi: {len(eventi)}')
        self.stdout.write('='*70)

    def genera_titolo(self, data):
        """Genera il titolo dell'articolo"""
        giorni_settimana = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']
        mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

        giorno_settimana = giorni_settimana[data.weekday()]
        giorno = data.day
        mese = mesi[data.month - 1]

        return f"Cosa fare oggi? {giorno_settimana} {giorno} {mese}"

    def genera_sommario(self, eventi, data):
        """Genera il sommario dell'articolo"""
        num_eventi = len(eventi)
        if num_eventi == 1:
            return f"Oggi a Carpi e dintorni: {eventi[0].titolo}. Scopri tutti i dettagli!"
        else:
            return f"Oggi a Carpi e dintorni ci sono {num_eventi} eventi da non perdere: " + \
                   ", ".join([e.titolo for e in eventi[:3]]) + \
                   (f" e altri {num_eventi - 3} eventi!" if num_eventi > 3 else "!")

    def genera_contenuto(self, eventi, data):
        """Genera il contenuto HTML dell'articolo con link agli eventi"""
        giorni_settimana = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
        mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

        giorno_settimana = giorni_settimana[data.weekday()]
        giorno = data.day
        mese = mesi[data.month - 1]

        contenuto = f'<p>Buongiorno! Ecco cosa succede oggi, <strong>{giorno_settimana} {giorno} {mese}</strong>, '
        contenuto += 'a Carpi e nei dintorni.</p>\n\n'

        if len(eventi) == 1:
            contenuto += '<p>Oggi abbiamo un evento speciale per voi:</p>\n\n'
        else:
            contenuto += f'<p>Abbiamo selezionato per voi <strong>{len(eventi)} eventi</strong> '
            contenuto += 'interessanti da non perdere:</p>\n\n'

        # Aggiungi ogni evento con link
        for i, evento in enumerate(eventi, 1):
            contenuto += f'<h3>{i}. <a href="/articolo/{evento.slug}/" class="internal-link">{evento.titolo}</a></h3>\n'
            contenuto += f'<p>{evento.sommario}</p>\n'
            contenuto += f'<p><a href="/articolo/{evento.slug}/" class="internal-link">>> Leggi tutti i dettagli</a></p>\n\n'

        contenuto += '<hr>\n\n'
        contenuto += '<p><em>Questa rubrica viene aggiornata ogni mattina alle 8:05 con gli eventi del giorno. '
        contenuto += 'Non perdere nessun appuntamento!</em></p>'

        return contenuto
