"""
Context processors per template tags globali
"""


def canonical_url(request):
    """
    Aggiunge get_canonical_url() al context di tutti i template
    """
    # Dominio canonico
    canonical_domain = 'ombradelportico.it'

    # Path pulito (sempre senza query params)
    path = request.path

    # URL canonico standard (senza query params, anche per filtri categoria)
    return {
        'canonical_url': f"https://{canonical_domain}{path}"
    }
