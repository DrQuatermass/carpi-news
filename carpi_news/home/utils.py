def canonical_article_url(article):
    from django.urls import reverse

    return f"https://ombradelportico.it{reverse('dettaglio_articolo', args=[article.slug])}"
