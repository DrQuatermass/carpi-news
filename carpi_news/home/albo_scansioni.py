"""
Lettura su richiesta degli atti dell'albo pretorio pubblicati come scansione.

Il monitor degli albi salta i documenti senza testo (scansioni) e quelli troppo grandi: la
notizia grezza si apre allora con ALBO_AVVISO_TESTO_NON_LETTO e dell'atto si conosce solo
l'oggetto. Leggere tutte le scansioni in automatico costerebbe una chiamata AI per centinaia
di atti che nessuno rielabora: qui la lettura parte solo quando la redazione preme
"Rielabora con AI" su una di quelle notizie (richiesta di Sven, 20/11/2026).

Si riscaricano i documenti dall'albo (il link ha un token che cambia a ogni visita, quindi
si ripassa dall'elenco con il numero di registro) e:
- se un documento ha il testo, lo si usa cosi' com'e' (capita con gli allegati oltre il
  limite di peso del monitor);
- se e' una scansione, il PDF va a Claude, che lo trascrive.

Modello: quello dei monitor (settings.ANTHROPIC_MODEL), una trascrizione non ha bisogno di
quello della rielaborazione. Costi in APIUsage, operation `albo_lettura_scansione`.
"""

import base64
import io
import logging
import re
from urllib.parse import urljoin

from django.conf import settings

logger = logging.getLogger(__name__)

OPERAZIONE = "albo_lettura_scansione"
MAX_BYTE_DOCUMENTO = 20 * 1024 * 1024    # in base64 cresce di un terzo: la richiesta ha un tetto di 32 MB
MAX_PAGINE_SCANSIONE = 30                # oltre, la trascrizione costa troppo per una notizia breve
MAX_SCANSIONI = 2                        # documenti trascritti per atto
MAX_CARATTERI = 30000                    # testo passato alla rielaborazione

PROMPT_TRASCRIZIONE = """Questo PDF e' la scansione di un atto amministrativo italiano \
(ordinanza, determinazione, delibera). Trascrivi il testo dell'atto, fedelmente e per intero, \
nell'ordine in cui si legge.

- Riporta cifre, date, nomi di vie e di luoghi esattamente come sono scritti.
- Dove una parola o un numero non si legge, scrivi [illeggibile]: non tirare a indovinare.
- Tralascia timbri, firme, loghi, numeri di pagina e intestazioni ripetute.
- Di planimetrie e disegni scrivi solo le scritte che contengono.
- Nessun commento, riassunto o premessa: solo il testo dell'atto."""


def _registro_da_fonte(fonte: str):
    """('https://.../?page_id=740', '2173/2026') da '<albo>#reg-2173-2026'; (None, None) altrimenti."""
    m = re.match(r'^(.*)#reg-(\d+)-(\d{4})$', fonte or '')
    return (m.group(1), f"{m.group(2)}/{m.group(3)}") if m else (None, None)


def _pagine(dati: bytes) -> int:
    from PyPDF2 import PdfReader
    return len(PdfReader(io.BytesIO(dati)).pages)


def _trascrivi(dati: bytes, articolo) -> str:
    """Testo di un PDF scansionato, letto da Claude. '' se la chiamata non va a buon fine."""
    import anthropic
    from home.anthropic_params import anthropic_model, response_text, thinking_params
    from home.api_usage_tracker import APIUsageTracker

    modello = anthropic_model()
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=300.0)
    risposta = client.messages.create(
        model=modello,
        max_tokens=16000,
        messages=[{'role': 'user', 'content': [
            {'type': 'document',
             'source': {'type': 'base64', 'media_type': 'application/pdf',
                        'data': base64.standard_b64encode(dati).decode('ascii')}},
            {'type': 'text', 'text': PROMPT_TRASCRIZIONE},
        ]}],
        **thinking_params('low'),
    )
    try:
        APIUsageTracker.track_anthropic(OPERAZIONE, modello, risposta.usage.input_tokens,
                                        risposta.usage.output_tokens,
                                        related_article=articolo if articolo.pk else None)
    except Exception as e:
        logger.warning("Tracking costi %s fallito: %s", OPERAZIONE, e)
    if risposta.stop_reason == 'refusal':
        logger.warning("Atto %s: il modello ha declinato la trascrizione", articolo.pk)
        return ''
    testo = response_text(risposta).strip()
    if risposta.stop_reason == 'max_tokens':
        testo += "\n\n[trascrizione interrotta: l'atto e' piu' lungo di quanto letto]"
    return testo


def leggi_atto(articolo, monitor) -> str:
    """Testo dei documenti dell'atto da cui nasce `articolo`, pronto per la rielaborazione:
    blocchi "ETICHETTA:\\n\\ntesto". '' se l'atto non e' piu' all'albo o non si riesce a leggerlo
    (la rielaborazione prosegue allora con il solo avviso e la regola della notizia breve)."""
    from home.universal_news_monitor import AlboItalsoftScraper

    albo_url, registro = _registro_da_fonte(articolo.fonte)
    if not registro or not monitor or monitor.scraper_type != 'albo_italsoft':
        return ''
    scraper = AlboItalsoftScraper(monitor.to_site_config(), {'User-Agent': 'Mozilla/5.0'})
    riga = next((r for r in scraper._leggi_tabella() if r['registro'] == registro and r['dettaglio']), None)
    if not riga:
        logger.info("Atto %s (%s): non e' piu' nell'elenco dell'albo", articolo.pk, registro)
        return ''
    _, documenti = scraper._leggi_dettaglio(urljoin(albo_url, riga['dettaglio']), riga['ente'])
    # Prima l'atto, poi gli allegati utili (non pareri e visti contabili)
    documenti = [d for d in documenti if d['link']]
    documenti = ([d for d in documenti if d['ruolo'] == 'ATTO'] +
                 [d for d in documenti if d['ruolo'] != 'ATTO' and scraper._allegato_utile(d)])

    blocchi, scansioni, spazio = [], 0, MAX_CARATTERI
    for doc in documenti:
        if spazio < 500:
            break
        if doc['byte'] > MAX_BYTE_DOCUMENTO:
            logger.info("Atto %s: documento troppo grande, saltato: %s", articolo.pk, doc['nome'])
            continue
        try:
            link = doc['link'].get('pdf') or doc['link'].get('p7m')
            dati = scraper._get_request(urljoin(albo_url, link), timeout=60).content
            if not dati.startswith(b'%PDF'):
                dati = scraper._pdf_da_p7m(dati)
            if not dati or len(dati) > MAX_BYTE_DOCUMENTO:
                continue
            testo = scraper._testo_pdf(dati, spazio)
            etichetta = "estratto automaticamente dal PDF"
            if len(testo) < 200:        # scansione
                if scansioni >= MAX_SCANSIONI or _pagine(dati) > MAX_PAGINE_SCANSIONE:
                    logger.info("Atto %s: scansione non trascritta (troppe o troppo lunga): %s",
                                articolo.pk, doc['nome'])
                    continue
                scansioni += 1
                testo = scraper._accorcia_atto(_trascrivi(dati, articolo), spazio)
                etichetta = "trascritto dall'AI dalla scansione: puo' contenere errori di lettura"
        except Exception as e:
            logger.warning("Atto %s: documento non letto (%s): %s", articolo.pk, doc['nome'], e)
            continue
        if len(testo) < 200:
            continue
        nome = "TESTO DELL'ATTO" if doc['ruolo'] == 'ATTO' else f"ALLEGATO \"{doc['nome']}\""
        blocchi.append(f"{nome} ({etichetta}):\n\n{testo}")
        spazio -= len(testo)
    logger.info("Atto %s (%s): letti %d documenti, %d trascritti dall'AI",
                articolo.pk, registro, len(blocchi), scansioni)
    return "\n\n".join(blocchi)
