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
from home.rubriche_ai import genera_con_ricerca
import re

logger = logging.getLogger(__name__)

RIGA_FINALE = ('\n<p><em>"Cosa fare oggi" esce ogni mattina alle 8:05 con gli appuntamenti della giornata '
               'a Carpi e dintorni.</em></p>')


class Command(BaseCommand):
    help = 'Genera l\'articolo giornaliero "Cosa fare oggi" con gli eventi del giorno e le mostre ancora aperte.'

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
        # Mostre e rassegne iniziate nei giorni scorsi e ancora aperte (data_evento e' solo
        # l'inizio: senza questo comparivano solo il primo giorno)
        for evento in self.eventi_in_corso(target_date, escludi={e.id for e in eventi}):
            eventi.append(evento)

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
        sommario = self.sommario_da_contenuto(contenuto) or self.genera_sommario(eventi, target_date)

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
            data_pubblicazione=timezone.now(),
            fonti_web=getattr(self, '_fonti_web', None) or None,
            ai_model_used=getattr(self, '_modello', None),
        )

        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS(f'[OK] Articolo creato con successo!'))
        self.stdout.write(f'  ID: {articolo.id}')
        self.stdout.write(f'  Slug: {articolo.slug}')
        self.stdout.write(f'  URL: /articolo/{articolo.slug}/')
        self.stdout.write(f'  Eventi inclusi: {len(eventi)}')
        self.stdout.write('='*70)

    MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto',
            'settembre', 'ottobre', 'novembre', 'dicembre']
    # "fino al 15 novembre", "fino a domenica 15 novembre 2026", "dal 3 al 15 novembre"
    RE_FINE = re.compile(
        r"\b(?:fino\s+a(?:l|ll')?|dal\s+\d{1,2}(?:\s+[a-z]+)?\s+al)\s+"
        r"(?:(?:luned|marted|mercoled|gioved|venerd)[iì]\s+|sabato\s+|domenica\s+)?"
        r"(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)"
        r"(?:\s+(\d{4}))?", re.IGNORECASE)
    MAX_IN_CORSO = 3
    RE_MOSTRA = re.compile(r'\b(mostra|mostre|esposizion|personale\b|collettiva\b|visitabil)', re.IGNORECASE)
    RE_NON_MOSTRA = re.compile(r'\b(festival|rassegn|cartellone|stagione|concors|iscrizion)', re.IGNORECASE)

    def fine_evento(self, testo, inizio):
        """Ultima data di chiusura esplicita nel testo ("fino al ..."), o None."""
        fine = None
        for giorno, mese, anno_testo in self.RE_FINE.findall(testo or ''):
            anno = int(anno_testo) if anno_testo else inizio.year
            try:
                d = date(anno, self.MESI.index(mese.lower()) + 1, int(giorno))
                if not anno_testo and d < inizio:
                    # "fino al 10 gennaio" detto a dicembre: e' l'anno dopo
                    d = date(anno + 1, d.month, d.day)
            except ValueError:
                continue
            if d >= inizio and (fine is None or d > fine):
                fine = d
        return fine

    def eventi_in_corso(self, target_date, escludi=()):
        """Eventi iniziati negli ultimi 120 giorni che nel testo dichiarano una chiusura >= oggi.
        Massimo MAX_IN_CORSO, i piu' vicini alla chiusura prima."""
        from datetime import timedelta
        candidati = Articolo.objects.filter(
            approvato=True,
            data_evento__lt=target_date,
            data_evento__gte=target_date - timedelta(days=120),
        ).filter(
            models.Q(categoria__icontains='Cultura') | models.Q(categoria__icontains='Eventi')
        ).exclude(id__in=list(escludi))
        trovati = []
        for e in candidati:
            testo = re.sub(r'<[^>]+>', ' ', e.contenuto or '')
            # Solo mostre: rassegne e festival hanno date sparse e finivano in pagina anche nei
            # giorni senza appuntamenti. La parola va cercata in titolo e sommario: nel testo
            # bastava "installazioni" in un festival (6/11: festival delle IntelligenzE)
            intestazione = f"{e.titolo} {e.sommario or ''}"
            if not self.RE_MOSTRA.search(intestazione) or self.RE_NON_MOSTRA.search(e.titolo or ''):
                continue
            fine = self.fine_evento(testo, e.data_evento)
            if fine and fine >= target_date:
                e.in_corso_fino = fine
                trovati.append(e)
        trovati.sort(key=lambda e: e.in_corso_fino)
        return trovati[:self.MAX_IN_CORSO]

    def genera_titolo(self, data):
        """Genera il titolo dell'articolo"""
        giorni_settimana = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']
        mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

        giorno_settimana = giorni_settimana[data.weekday()]
        giorno = data.day
        mese = mesi[data.month - 1]

        return f"Cosa fare oggi: {giorno_settimana} {giorno} {mese}"

    @staticmethod
    def sommario_da_contenuto(contenuto):
        """Il paragrafo d'apertura scritto dal modello (conta solo gli eventi davvero presentati).
        Prima il sommario era un modello fisso: "Ecco N eventi da non perdere", con N che
        contava anche mostre chiuse e festival scartati dal testo."""
        # L'apertura e' tutto cio' che sta prima del primo <h3> (a volte senza <p>)
        testo = re.split(r'<h3', contenuto or '', maxsplit=1)[0]
        testo = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', testo)).strip()
        if len(testo) < 60 or testo.startswith('Buongiorno!'):  # fallback senza AI
            return ''
        if len(testo) > 320:
            testo = testo[:320].rsplit(' ', 1)[0].rstrip(',;:') + '…'
        return testo

    def genera_sommario(self, eventi, data):
        """Sommario di riserva, se il testo AI non ha un paragrafo d'apertura usabile"""
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
            return f"Cosa fare oggi {giorno_settimana} {giorno} {mese} a Carpi e dintorni: gli appuntamenti della giornata tra cultura, spettacoli e iniziative."

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
            fino = getattr(evento, 'in_corso_fino', None)
            eventi_info.append({
                'numero': i,
                'titolo': evento.titolo,
                'sommario': evento.sommario,
                # Testo intero (fino a 6000 caratteri): orari, prezzi e prenotazioni stanno in
                # fondo alle schede e con il vecchio taglio a 1500 caratteri si perdevano
                'testo': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', evento.contenuto or '')).strip()[:6000],
                'slug': evento.slug,
                'categoria': evento.categoria,
                'quando': (f"in corso, aperto fino al {fino.day} {self.MESI[fino.month - 1]}" if fino else "oggi"),
            })

        # Genera contenuto con AI
        try:
            contenuto_ai = self._genera_con_ai(eventi_info, giorno_settimana, giorno, mese)

            # Inserisci i link agli eventi nel testo generato
            contenuto_finale = self._inserisci_link_eventi(self._apertura_in_paragrafo(contenuto_ai), eventi)

            # Riga fissa della rubrica: la scrive il codice, non il modello (prima la chiedeva il
            # prompt e ogni giorno usciva una variante di "tre proposte, scegliete la vostra")
            return contenuto_finale + RIGA_FINALE

        except Exception as e:
            logger.error(f"Errore generazione AI: {e}")
            # Fallback al formato semplice
            return self._genera_contenuto_fallback(eventi, giorno_settimana, giorno, mese)

    def _genera_con_ai(self, eventi_info, giorno_settimana, giorno, mese):
        """Usa Claude per generare un articolo narrativo"""
        # Prepara lista eventi per il prompt
        lista_eventi = "\n".join([
            f"{e['numero']}. {e['titolo']}\n   Quando: {e['quando']}\n   Categoria: {e['categoria']}\n   Testo della scheda: {e['testo']}"
            for e in eventi_info
        ])
        oggi = [e for e in eventi_info if e['quando'] == 'oggi']
        parole = max(150, min(650, 60 + 110 * len(oggi) + 50 * (len(eventi_info) - len(oggi))))

        prompt = f"""Scrivi la rubrica "Cosa fare oggi" di Ombra del Portico, giornale online di Carpi. Chi la legge al mattino, dal telefono, vuole decidere in fretta se e dove uscire oggi.

DATA: {giorno_settimana} {giorno} {mese}
EVENTI ({len(eventi_info)}):

{lista_eventi}

COME SCRIVERLA:
- Una o due frasi di apertura che dicono che giornata è (quanti appuntamenti, di che tipo, dove), partendo dai fatti. Niente formule come "è una di quelle giornate", "c'è un filo che tiene insieme".
- Poi un blocco per evento: <h3>TITOLO</h3>, dove TITOLO è il titolo dell'evento copiato esattamente come lo trovi sopra (serve per il link), seguito da uno o due paragrafi.
- In ogni blocco, prima cos'è e per chi è, poi in una frase finale le informazioni pratiche presenti nella scheda: orario, luogo con indirizzo, costo o ingresso libero, come prenotare. Se un dato manca nella scheda, non scriverlo e non stimarlo.
- Metti prima gli eventi di oggi in ordine di orario; quelli "in corso" (mostre) vanno in fondo, presentati come ancora aperti, con la data di chiusura e l'orario di oggi.
- Una mostra "in corso" che secondo la scheda oggi ({giorno_settimana}) è chiusa (per esempio apre solo nel fine settimana) va tolta del tutto: niente blocco, niente accenno.
- Il primo paragrafo deve contare solo gli appuntamenti che poi presenti.
- Chiudi con l'ultimo evento: niente frase finale di riepilogo, niente "scegliete il vostro", niente promemoria sulla rubrica (lo aggiunge il sistema).
- Tono caldo e locale, ironia leggera solo dove l'evento la regge. Niente aggettivi promozionali ("imperdibile", "da non perdere", "straordinario").
- Tag HTML ammessi: <p>, <h3>, <strong>, <em>. Niente link (li aggiunge il sistema).
- Lunghezza: circa {parole} parole in tutto."""

        # Modello e tracking costi: home/rubriche_ai.py. Una ricerca al massimo: le schede bastano,
        # serve solo se un dato pratico manca o va verificato
        esito = genera_con_ricerca(prompt, operation='cosa_fare_oggi', max_ricerche=1)
        self._fonti_web = esito['fonti_web']
        self._modello = esito['modello']
        logger.info("Cosa fare oggi generato con %s, %d ricerche web" % (esito['modello'], esito['ricerche']))

        return esito['testo']

    @staticmethod
    def _apertura_in_paragrafo(html):
        """Se il modello scrive l'apertura come testo nudo prima del primo <h3>, la mette in un <p>."""
        testa, sep, resto = (html or '').strip().partition('<h3')
        if testa.strip() and not testa.lstrip().startswith('<'):
            testa = '<p>' + testa.strip() + '</p>\n\n'
        return testa + sep + resto

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
