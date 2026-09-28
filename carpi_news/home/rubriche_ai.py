"""Generazione AI per le rubriche quotidiane (editoriale delle 8:00, "Cosa fare oggi").

Le rubriche non passano dai monitor, quindi hanno un loro percorso:
- modello dedicato (settings.RUBRICHE_ANTHROPIC_MODEL, default Claude Opus 5);
- ricerca web con lo stesso strumento dei monitor (Google + lettura delle pagine),
  al massimo settings.RUBRICHE_MAX_RICERCHE ricerche per testo (0 = ricerca spenta);
- ogni chiamata e ogni ricerca finiscono in APIUsage, quindi nella dashboard costi.
"""
import logging

import anthropic
from django.conf import settings

from home.anthropic_params import response_text, thinking_params

logger = logging.getLogger(__name__)

STRUMENTO_RICERCA = {
    "name": "web_search",
    "description": (
        "Ricerca web con lettura del contenuto delle pagine trovate. Serve a verificare un fatto "
        "(nomi, cariche, date, orari, luoghi, numeri) o ad aggiungere contesto su cio' che e' gia' "
        "nel materiale fornito. Scrivi query BREVI, 2-4 parole chiave (nomi propri, luogo, tema): "
        "le frasi lunghe non restituiscono risultati. Ogni risultato riporta la data di pubblicazione: "
        "colloca ogni informazione nel suo tempo e non scambiare un fatto passato per attuale."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "2-4 parole chiave, senza frasi lunghe"},
            "max_results": {"type": "integer", "default": 2, "description": "Numero massimo di risultati (1-5)"},
        },
        "required": ["query"],
    },
}

REGOLE_RICERCA = """

RICERCA WEB E FEDELTA' AI FATTI:
Hai a disposizione lo strumento web_search, per un massimo di {max_ricerche} ricerche. Usalo quando un'informazione verificabile migliora il testo: un precedente, un numero, un orario, il ruolo di una persona. Se il materiale fornito basta, scrivi senza cercare.
Scrivi per lettori che conoscono la citta': un dettaglio plausibile ma non verificato viene riconosciuto subito come errore. Ogni fatto del testo deve quindi venire dal materiale fornito o dai risultati delle ricerche. Se un dato non c'e', non scriverlo e non stimarlo. Non creare virgolettati. Ironia e tono personale vanno bene finche' non affermano fatti nuovi: anche la descrizione di un luogo, la sua acustica, le distanze, le abitudini del pubblico e i consigli pratici (arrivare prima, cosa portare) sono affermazioni di fatto, quindi scrivile solo se il materiale le sostiene.
Dai risultati prendi solo cio' che riguarda davvero l'argomento. Non inserire link a siti esterni nel testo."""


def modello_rubriche():
    return getattr(settings, 'RUBRICHE_ANTHROPIC_MODEL', 'claude-opus-5')


def max_ricerche_rubriche():
    return max(0, int(getattr(settings, 'RUBRICHE_MAX_RICERCHE', 3)))


def _traccia_chiamata(operation, modello, message):
    try:
        from home.api_usage_tracker import APIUsageTracker
        APIUsageTracker.track_anthropic(
            operation=operation,
            model=modello,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            related_article=None,
            success=True,
        )
    except Exception as e:
        logger.warning("Tracking costi non riuscito per %s: %s", operation, e)


def _esegui_ricerca(query, max_results, fonti_web, operation):
    """Esegue una ricerca e ritorna il testo da restituire al modello."""
    from home.web_search_tool import web_search_tool

    try:
        max_results = min(max(int(max_results or 2), 1), 5)
        risultati = web_search_tool.search_with_content(query, max_results, fetch_content=True)
    except Exception as e:
        logger.warning("Ricerca web fallita per '%s': %s", query, e)
        return "La ricerca non e' riuscita. Prosegui con le informazioni disponibili."

    if not risultati:
        return "Nessun risultato per questa ricerca. Prosegui con le informazioni disponibili."

    try:
        from home.api_usage_tracker import APIUsageTracker
        APIUsageTracker.track_google_search(
            operation='web_search_' + operation, num_queries=1, related_article=None, success=True)
    except Exception as e:
        logger.warning("Tracking ricerca non riuscito: %s", e)

    gia_viste = set(f['url'] for f in fonti_web)
    for r in risultati:
        if r['url'] not in gia_viste:
            fonti_web.append({'url': r['url'], 'title': r.get('page_title', r['title']), 'query_used': query})
            gia_viste.add(r['url'])
    return web_search_tool.format_results_with_content_for_ai(risultati)


def genera_con_ricerca(prompt, operation, system=None, max_tokens=8192, effort='medium', max_ricerche=None):
    """Genera un testo con Claude, con ricerca web opzionale.

    Ritorna un dict: testo, fonti_web (pagine lette durante le ricerche), modello, ricerche.
    Solleva un'eccezione se il modello declina la richiesta o non produce testo: i chiamanti
    hanno gia' il loro comportamento di riserva.
    """
    modello = modello_rubriche()
    if max_ricerche is None:
        max_ricerche = max_ricerche_rubriche()
    usa_ricerca = max_ricerche > 0

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    if usa_ricerca:
        prompt = prompt + REGOLE_RICERCA.format(max_ricerche=max_ricerche)
    conversazione = [{"role": "user", "content": prompt}]
    fonti_web = []
    ricerche = 0

    for giro in range(max_ricerche + 2):
        params = {
            "model": modello,
            "max_tokens": max_tokens,  # il thinking adattivo rientra in questo limite
            "messages": conversazione,
        }
        params.update(thinking_params(effort))
        if system:
            params["system"] = system
        if usa_ricerca:
            params["tools"] = [STRUMENTO_RICERCA]
            if ricerche >= max_ricerche:
                # Ricerche esaurite: gli strumenti restano dichiarati ma non utilizzabili
                params["tool_choice"] = {"type": "none"}

        message = client.messages.create(**params)
        _traccia_chiamata(operation, modello, message)

        if getattr(message, 'stop_reason', None) == 'refusal':
            raise RuntimeError("Il modello ha declinato la richiesta (%s)" % operation)
        if getattr(message, 'stop_reason', None) == 'max_tokens':
            logger.warning("%s: risposta troncata a max_tokens", operation)

        richieste = [b for b in message.content if getattr(b, 'type', None) == 'tool_use']
        if not richieste:
            testo = response_text(message).strip()
            if not testo:
                raise RuntimeError("Risposta senza testo (%s)" % operation)
            logger.info("%s: generato con %s, %d ricerche, %d fonti", operation, modello, ricerche, len(fonti_web))
            return {'testo': testo, 'fonti_web': fonti_web, 'modello': modello, 'ricerche': ricerche}

        conversazione.append({"role": "assistant", "content": message.content})
        esiti = []
        for richiesta in richieste:
            if ricerche < max_ricerche:
                query = (richiesta.input or {}).get("query", "")
                logger.info("%s: ricerca web '%s'", operation, query)
                contenuto = _esegui_ricerca(query, (richiesta.input or {}).get("max_results", 2), fonti_web, operation)
                ricerche += 1
            else:
                contenuto = "Limite di ricerche raggiunto. Scrivi ora il testo con le informazioni disponibili."
            esiti.append({"type": "tool_result", "tool_use_id": richiesta.id, "content": contenuto})
        conversazione.append({"role": "user", "content": esiti})

    raise RuntimeError("Generazione non conclusa entro il numero massimo di passaggi (%s)" % operation)
