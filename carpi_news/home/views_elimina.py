"""Tasto "Elimina" nelle email di notifica: pagina di conferma, la cancellazione parte solo col POST.

Il GET non cancella nulla: i controlli antispam della posta aprono i link da soli.
Si possono eliminare solo articoli non approvati e non pubbliredazionali; la riga finisce nel
registro ArticoloEliminato (motivo 'email') e il monitor non reimporta la notizia.
"""
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from home.models import Articolo

TOKEN_SALT = 'elimina-da-email'
TOKEN_MAX_AGE = 14 * 24 * 3600


def token_elimina(articolo_id):
    return TimestampSigner(salt=TOKEN_SALT).sign(str(articolo_id))


def _articolo_id(token):
    try:
        return int(TimestampSigner(salt=TOKEN_SALT).unsign(token, max_age=TOKEN_MAX_AGE))
    except (BadSignature, SignatureExpired, ValueError):
        return None


@never_cache
def elimina_da_email(request, token):
    articolo_id = _articolo_id(token)
    if not articolo_id:
        return render(request, 'elimina_email.html', {'stato': 'link_non_valido'}, status=404)
    articolo = Articolo.objects.filter(pk=articolo_id).first()
    if not articolo:
        from home.models import ArticoloEliminato
        gia = ArticoloEliminato.objects.filter(articolo_id=articolo_id).first()
        return render(request, 'elimina_email.html', {'stato': 'gia_eliminato', 'registro': gia})
    if articolo.approvato or articolo.is_pubbliredazionale:
        return render(request, 'elimina_email.html', {'stato': 'protetto', 'articolo': articolo})

    if request.method == 'POST':
        from home.eliminazione import elimina_articolo
        titolo = articolo.titolo
        elimina_articolo(articolo, motivo='email')
        return render(request, 'elimina_email.html', {'stato': 'eliminato', 'titolo': titolo})
    return render(request, 'elimina_email.html', {'stato': 'conferma', 'articolo': articolo})
