"""
Context processors per template tags globali
"""


def canonical_url(request):
    """
    Aggiunge get_canonical_url() al context di tutti i template
    """
    # Dominio canonico
    canonical_domain = 'ombradelportico.it'

    # Path pulito
    path = request.path

    # Per homepage con filtri categoria, includi il parametro
    if path == '/' and request.GET.get('categoria'):
        categoria = request.GET.get('categoria')
        return {
            'canonical_url': f"https://{canonical_domain}/?categoria={categoria}"
        }

    # URL canonico standard (senza query params)
    return {
        'canonical_url': f"https://{canonical_domain}{path}"
    }
