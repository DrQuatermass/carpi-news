"""
Comando per generare automaticamente l'articolo giornaliero "Cosa fare oggi"

Raccoglie tutti gli eventi del giorno dalle categorie Cultura ed Eventi
e genera un articolo narrativo con AI che li presenta in modo coinvolgente.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models
from home.models import Articolo
from datetime import date
import logging
import anthropic
import os
import re

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Genera l\'articolo giornaliero "Cosa fare oggi?" con gli eventi del giorno nello stile di Umberto Eco. Usa ironia.'

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

        # Controlla se esiste già un articolo "Cosa fare oggi" per questa data
        # Usa categoria + data invece del titolo per evitare race conditions
        from django.db import transaction

        # Lock a livello DB per prevenire race condition tra worker Gunicorn
        with transaction.atomic():
            existing = Articolo.objects.select_for_update().filter(
                categoria='Cosa fare oggi',
                data_pubblicazione__date=target_date
            ).first()

            if existing:
                self.stdout.write(self.style.WARNING(f'\n[!] Articolo "Cosa fare oggi" già esistente per {target_date.strftime("%d/%m/%Y")}'))
                self.stdout.write(f'  ID: {existing.id}')
                self.stdout.write(f'  Slug: {existing.slug}')
                self.stdout.write(f'  Titolo: {existing.titolo}')
                self.stdout.write(f'  Creato: {existing.data_creazione.strftime("%d/%m/%Y %H:%M")}')
                self.stdout.write(self.style.WARNING('  Articolo già presente, skip per evitare duplicati'))
                return

            # Genera il contenuto dell'articolo (dentro la transazione per mantenere il lock)
            titolo_base = self.genera_titolo(target_date)
            titolo = titolo_base
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

        # Crea l'articolo con immagine di default per SEO
        articolo = Articolo.objects.create(
            titolo=titolo,
            contenuto=contenuto,
            sommario=sommario,
            categoria='Cosa fare oggi',
            foto='/static/home/images/Oggi.webp',
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

        return f"Cosa fare oggi: {giorno_settimana} {giorno} {mese}"

    def genera_sommario(self, eventi, data):
        """Genera il sommario dell'articolo ottimizzato per SEO"""
        giorni_settimana = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
        mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

        giorno_settimana = giorni_settimana[data.weekday()]
        giorno = data.day
        mese = mesi[data.month - 1]

        num_eventi = len(eventi)
        if num_eventi == 1:
            return f"Eventi oggi {giorno} {mese} a Carpi e Modena: {eventi[0].titolo}. Scopri cosa fare oggi in provincia!"
        else:
            return f"Cosa fare oggi {giorno_settimana} {giorno} {mese} a Carpi? Ecco {num_eventi} eventi da non perdere tra cultura, spettacoli e iniziative in città e provincia di Modena."

    def genera_contenuto(self, eventi, data):
        """Genera il contenuto HTML dell'articolo usando AI per creare un testo narrativo"""
        giorni_settimana = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
        mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

        giorno_settimana = giorni_settimana[data.weekday()]
        giorno = data.day
        mese = mesi[data.month - 1]

        # Prepara dati eventi per AI
        eventi_info = []
        for i, evento in enumerate(eventi, 1):
            eventi_info.append({
                'numero': i,
                'titolo': evento.titolo,
                'sommario': evento.sommario,
                'slug': evento.slug,
                'categoria': evento.categoria
            })

        # Genera contenuto con AI
        try:
            contenuto_ai = self._genera_con_ai(eventi_info, giorno_settimana, giorno, mese)

            # Inserisci i link agli eventi nel testo generato
            contenuto_finale = self._inserisci_link_eventi(contenuto_ai, eventi)

            return contenuto_finale

        except Exception as e:
            logger.error(f"Errore generazione AI: {e}")
            # Fallback al formato semplice
            return self._genera_contenuto_fallback(eventi, giorno_settimana, giorno, mese)

    def _genera_con_ai(self, eventi_info, giorno_settimana, giorno, mese):
        """Usa Claude per generare un articolo narrativo"""
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        # Prepara lista eventi per il prompt
        lista_eventi = "\n".join([
            f"{e['numero']}. {e['titolo']}\n   Categoria: {e['categoria']}\n   Descrizione: {e['sommario'][:200]}..."
            for e in eventi_info
        ])

        prompt = f"""Scrivi un articolo coinvolgente per la rubrica "Cosa fare oggi" del giornale locale di Carpi.

DATA: {giorno_settimana} {giorno} {mese}
EVENTI DEL GIORNO ({len(eventi_info)} eventi):

{lista_eventi}

ISTRUZIONI:
- Scrivi un articolo narrativo e coinvolgente (NON un semplice elenco)
- Inizia con un'introduzione accattivante che presenta la giornata
- Presenta gli eventi in modo fluido e narrativo, evidenziando varietà e ricchezza dell'offerta culturale
- Per ogni evento usa il formato: <h3>TITOLO_EVENTO</h3> seguito da un paragrafo descrittivo
- Usa un tono caldo, locale, che parla ai lettori di Carpi
- Concludi invitando a partecipare e menziona che la rubrica si aggiorna quotidianamente alle 8:05
- Usa tag HTML: <p>, <h3>, <strong>, <em>
- NON inserire link (verranno aggiunti automaticamente)
- Lunghezza: circa 400-600 parole

STILE: Giornalistico locale, caldo, coinvolgente, che valorizza il territorio."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            temperature=0.7,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        return message.content[0].text

    def _inserisci_link_eventi(self, contenuto_ai, eventi):
        """Inserisce automaticamente i link agli eventi nel testo generato dall'AI"""
        contenuto_finale = contenuto_ai

        for evento in eventi:
            # Cerca il titolo dell'evento nel testo e lo trasforma in link
            titolo_escaped = re.escape(evento.titolo)
            # Pattern per trovare il titolo dentro un tag h3
            pattern = f'(<h3>)({titolo_escaped})(</h3>)'
            replacement = f'\\1<a href="/articolo/{evento.slug}/" class="internal-link">\\2</a>\\3'
            contenuto_finale = re.sub(pattern, replacement, contenuto_finale, flags=re.IGNORECASE)

        return contenuto_finale

    def _genera_contenuto_fallback(self, eventi, giorno_settimana, giorno, mese):
        """Fallback senza AI in caso di errore"""
        contenuto = f'<p>Buongiorno! Ecco cosa succede oggi, <strong>{giorno_settimana} {giorno} {mese}</strong>, '
        contenuto += 'a Carpi e nei dintorni.</p>\n\n'

        if len(eventi) == 1:
            contenuto += '<p>Oggi abbiamo un evento speciale per voi:</p>\n\n'
        else:
            contenuto += f'<p>Abbiamo selezionato per voi <strong>{len(eventi)} eventi</strong> '
            contenuto += 'interessanti da non perdere:</p>\n\n'

        for i, evento in enumerate(eventi, 1):
            contenuto += f'<h3>{i}. <a href="/articolo/{evento.slug}/" class="internal-link">{evento.titolo}</a></h3>\n'
            contenuto += f'<p>{evento.sommario}</p>\n'
            contenuto += f'<p><a href="/articolo/{evento.slug}/" class="internal-link">>> Leggi tutti i dettagli</a></p>\n\n'

        contenuto += '<hr>\n\n'
        contenuto += '<p><em>Questa rubrica viene aggiornata ogni mattina alle 8:05 con gli eventi del giorno. '
        contenuto += 'Non perdere nessun appuntamento!</em></p>'

        return contenuto
