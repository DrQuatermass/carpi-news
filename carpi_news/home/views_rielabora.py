"""Pagina di conferma per il tasto "Rielabora con AI" nelle email di notifica."""
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from home.models import Articolo
from home.rielaborazione_ai import (
    articolo_id_da_token, avvia_rielaborazione, in_corso, trova_monitor,
)


@never_cache
def rielabora_da_email(request, token):
    articolo_id = articolo_id_da_token(token)
    articolo = Articolo.objects.filter(pk=articolo_id).first() if articolo_id else None
    if not articolo:
        return render(request, 'rielabora_email.html', {'stato': 'link_non_valido'}, status=404)

    monitor = trova_monitor(articolo)
    ctx = {
        'articolo': articolo,
        'regole': monitor.name if monitor else 'regole predefinite',
        'ricerca_web': monitor.enable_web_search if monitor else True,
        'stato': 'conferma',
    }

    if request.method == 'POST':
        richieste = (request.POST.get('richieste_modifica') or '').strip()
        if richieste:
            Articolo.objects.filter(pk=articolo.pk).update(richieste_modifica=richieste)
        ctx['stato'] = 'avviata' if avvia_rielaborazione(articolo.pk, richieste or None) else 'in_corso'
    elif in_corso(articolo.pk):
        ctx['stato'] = 'in_corso'
    elif not settings.RIELABORA_EMAIL_CONFERMA:
        # Un clic: la pagina invia da sola il POST via JavaScript. Il GET resta senza effetti,
        # cosi' i controlli automatici dei link (che di norma non eseguono JS) non avviano nulla.
        ctx['stato'] = 'auto'

    return render(request, 'rielabora_email.html', ctx)
