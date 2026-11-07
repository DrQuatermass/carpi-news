"""Carica gli spettacoli in arrivo del Teatro Comunale di Carpi come notizie grezze (dal 7/11/2026).

    python manage.py importa_spettacoli_teatro            # prova: mostra cosa caricherebbe
    python manage.py importa_spettacoli_teatro --esegui   # crea le notizie grezze

Il sito del teatro (WordPress) tiene i dati in due posti:
- calendario (tipo tc_events, REST API): titolo, rassegna e pagina con data e orario
  ("24 Aprile 2027 21:00 - 23:30"); una riga per replica, senza descrizione;
- schede spettacolo (/spettacoli/<slug>/, non nella REST API, elencate nella sitemap
  show-item): autore, interpreti, regia, presentazione e foto. La data nella scheda e'
  spesso di una stagione passata: si usano solo le date del calendario.
Una notizia per spettacolo, con tutte le repliche future; fonte = URL della scheda, quindi
rilanciare il comando non crea doppioni. Le notizie sono collegate al monitor
"Teatro Comunale Carpi" (crea_monitor_cultura), da cui la rielaborazione prende la nota.
"""
import difflib
import html
import re
from collections import OrderedDict
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from home.models import Articolo, MonitorConfig

SITO = 'https://teatrocarpi.it'
MONITOR = 'Teatro Comunale Carpi'
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; OmbraDelPortico/1.0)'}
MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio',
        'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
RE_DATA = re.compile(r'(\d{1,2}) ([A-Za-z]+) (\d{4}) (\d{1,2}):(\d{2})')


def _get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=20, **kw)
    r.raise_for_status()
    return r


def _slug_base(slug):
    return re.sub(r'-\d+$', '', slug)  # le repliche hanno slug "-2"


def _data_replica(url):
    testo = BeautifulSoup(_get(url).text, 'html.parser').get_text(' ', strip=True)
    m = RE_DATA.search(testo)
    if not m or m.group(2).lower() not in MESI:
        return None
    g, mese, a, hh, mm = m.groups()
    return datetime(int(a), MESI.index(mese.lower()) + 1, int(g), int(hh), int(mm))


def _scheda(url):
    """Testo e foto della scheda spettacolo, senza la data (spesso vecchia) e i menu."""
    soup = BeautifulSoup(_get(url).text, 'html.parser')
    foto = soup.find('meta', property='og:image')
    corpo = soup.select_one('.mkdf-single-show-main-content') or soup.select_one('.mkdf-shows-single-holder')
    if not corpo:
        return '', foto.get('content') if foto else None
    for t in corpo.select('script, style, .mkdf-single-show-date'):
        t.decompose()
    # Ruoli (autore, attore, regista...) come "ruolo: nome"
    righe = []
    for ruolo in corpo.select('.mkdf-show-role'):
        nomi = [li.get_text(' ', strip=True) for li in ruolo.select('li')]
        etichetta = ruolo.find(['h6', 'h5', 'span', 'p'])
        etichetta = etichetta.get_text(strip=True) if etichetta else ''
        if nomi and etichetta in nomi:
            nomi.remove(etichetta)
        if nomi:
            righe.append(f"{etichetta}: {', '.join(nomi)}" if etichetta else ', '.join(nomi))
        ruolo.decompose()
    for holder in corpo.select('.mkdf-show-roles-holder'):
        holder.decompose()
    testo = re.sub(r'\n\s*\n+', '\n\n', corpo.get_text('\n', strip=True))
    testo = re.sub(r'\[/?vc_[^\]]*\]', '', testo).strip()
    return '\n'.join(righe) + ('\n\n' if righe else '') + testo, foto.get('content') if foto else None


def _fmt(d):
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year} ore {d:%H:%M}"


class Command(BaseCommand):
    help = "Carica gli spettacoli futuri del Teatro Comunale di Carpi come notizie grezze"

    def add_arguments(self, parser):
        parser.add_argument('--esegui', action='store_true', help='Crea davvero le notizie (senza: solo prova)')

    def handle(self, *args, **opts):
        monitor = MonitorConfig.objects.filter(name=MONITOR).first()
        if not monitor:
            raise CommandError(f'Monitor "{MONITOR}" assente: lancia prima crea_monitor_cultura')

        eventi = _get(f'{SITO}/wp-json/wp/v2/tc_events', params={'per_page': 100}).json()
        rassegne = {c['id']: html.unescape(c['name']) for c in
                    _get(f'{SITO}/wp-json/wp/v2/event_category', params={'per_page': 100}).json()}
        sitemap = _get(f'{SITO}/wp-sitemap-posts-show-item-1.xml').text
        schede = {u.rstrip('/').split('/')[-1]: u for u in
                  re.findall(r'<loc>(https://teatrocarpi\.it/spettacoli/[^<]+)</loc>', sitemap)}

        adesso = datetime.now()
        spettacoli = OrderedDict()  # url scheda -> dati
        for ev in eventi:
            titolo = html.unescape(ev['title']['rendered']).strip()
            quando = _data_replica(ev['link'])
            if not quando:
                self.stdout.write(self.style.WARNING(f'  data non trovata: {titolo} ({ev["link"]})'))
                continue
            if quando < adesso:
                continue
            base = _slug_base(ev['slug'])
            simile = difflib.get_close_matches(base, schede.keys(), n=1, cutoff=0.55)
            url = schede[simile[0]] if simile else ev['link']
            s = spettacoli.setdefault(url, {
                'titolo': titolo, 'date': [], 'scheda': bool(simile),
                'rassegne': [rassegne.get(c, '') for c in ev.get('event_category', [])
                             if not rassegne.get(c, '').lower().startswith('stagione')],
            })
            s['date'].append(quando)

        creati = 0
        for url, s in sorted(spettacoli.items(), key=lambda x: min(x[1]['date'])):
            s['date'].sort()
            esiste = Articolo.objects.filter(fonte=url).exists()
            stato = 'gia\' presente' if esiste else ('senza scheda' if not s['scheda'] else 'nuovo')
            self.stdout.write(f"{min(s['date']):%d/%m/%Y} | {s['titolo'][:50]} | {len(s['date'])} date | {stato} | {url}")
            if esiste or not opts['esegui']:
                continue

            testo_scheda, foto = _scheda(url) if s['scheda'] else ('', None)
            righe = [
                'SPETTACOLO DELLA STAGIONE 2026/27 DEL TEATRO COMUNALE DI CARPI (piazza dei Martiri 72, Carpi)',
                f"Rassegna: {', '.join(r for r in s['rassegne'] if r)}" if any(s['rassegne']) else '',
                'DATE IN CALENDARIO: ' + '; '.join(_fmt(d) for d in s['date']),
                'Biglietteria: tel. 059 649263, biglietteria.teatro@comune.carpi.mo.it',
                '',
                'SCHEDA DELLO SPETTACOLO:' if testo_scheda else 'Scheda dello spettacolo non disponibile sul sito del teatro.',
                testo_scheda,
            ]
            contenuto = '\n'.join(r for r in righe if r is not None)
            articolo = Articolo(
                titolo=s['titolo'][:200],
                contenuto=contenuto,
                categoria=monitor.category,
                fonte=url,
                foto=foto,
                foto_valida=bool(foto),
                data_evento=min(s['date']).date(),
                approvato=False,
                da_rielaborare=True,
                monitor_origine=monitor,
                data_pubblicazione=timezone.now(),
            )
            articolo.save()
            creati += 1

        self.stdout.write(f'\n{len(spettacoli)} spettacoli in arrivo, '
                          + (f'{creati} notizie grezze create' if opts['esegui'] else 'prova: rilancia con --esegui'))
