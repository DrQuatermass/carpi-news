"""
Middleware per aggiungere header di cache ottimali ai file statici e media
"""
import re
from django.utils.cache import patch_cache_control


class StaticMediaCacheMiddleware:
    """
    Aggiunge header di cache appropriati per file statici e media
    """

    def __init__(self, get_response):
        self.get_response = get_response

        # Pattern per file statici che dovrebbero avere cache lunga
        self.cache_patterns = [
            (re.compile(r'\.(jpg|jpeg|png|gif|webp|svg|ico)$', re.I), 365 * 24 * 60 * 60),  # Immagini: 1 anno
            (re.compile(r'\.(css|js)$', re.I), 30 * 24 * 60 * 60),  # CSS/JS: 30 giorni
            (re.compile(r'\.(woff|woff2|ttf|eot)$', re.I), 365 * 24 * 60 * 60),  # Fonts: 1 anno
            (re.compile(r'\.(pdf|txt)$', re.I), 7 * 24 * 60 * 60),  # Documenti: 7 giorni
        ]

    def __call__(self, request):
        response = self.get_response(request)

        # Applica cache solo a file statici e media
        path = request.path
        if path.startswith('/static/') or path.startswith('/media/'):
            # Controlla ogni pattern
            for pattern, max_age in self.cache_patterns:
                if pattern.search(path):
                    # Aggiungi header di cache
                    patch_cache_control(
                        response,
                        public=True,
                        max_age=max_age,
                        immutable=True  # Browser non rivalidano (perfetto per file con hash/versione)
                    )
                    break

        return response
