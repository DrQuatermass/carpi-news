"""
Parametri condivisi per le chiamate Anthropic (Messages API).

Centralizza modello, thinking ed effort così che il cambio modello sia un'unica
variabile d'ambiente (ANTHROPIC_MODEL) e non una caccia alle stringhe nel codice.

Note sui modelli dalla generazione Sonnet 5 / Opus 5 in poi:
- ``temperature``/``top_p``/``top_k`` non sono accettati (HTTP 400): la tonalità
  si controlla dal prompt.
- omettendo ``thinking`` il modello ragiona in modalità adattiva: i token di
  thinking contano dentro ``max_tokens`` e la risposta può contenere blocchi
  ``thinking`` prima del testo, quindi non si può leggere ``content[0].text``.
- l'SDK anthropic 0.64 non conosce ``output_config``: l'effort viene passato
  tramite ``extra_body``.
"""
from django.conf import settings


def anthropic_model() -> str:
    return getattr(settings, 'ANTHROPIC_MODEL', 'claude-sonnet-5')


def thinking_params(mode: str = 'medium') -> dict:
    """
    Kwargs da aggiungere a ``client.messages.create``.

    mode:
      - 'off'    : nessun thinking, risposta immediata (domande brevi, latenza).
      - 'low'    : thinking adattivo leggero.
      - 'medium' : thinking adattivo, paragonabile a Sonnet 4.6 a effort alto.
                   Scelta di default per la generazione degli articoli.
      - 'high'   : thinking adattivo pieno (effort di default dell'API).
    """
    if mode == 'off':
        return {"thinking": {"type": "disabled"}}
    if mode not in ('low', 'medium', 'high'):
        raise ValueError(f"thinking mode non valido: {mode}")
    return {
        "thinking": {"type": "adaptive"},
        "extra_body": {"output_config": {"effort": mode}},
    }


def response_text(message) -> str:
    """Concatena i soli blocchi di testo della risposta (ignora thinking/tool_use)."""
    return "".join(
        block.text for block in message.content if getattr(block, 'type', None) == 'text'
    )
