"""
Custom middleware for security headers including Content Security Policy (CSP)
"""

class SecurityHeadersMiddleware:
    """
    Aggiunge header di sicurezza alle risposte HTTP
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Escludi le pagine di preview admin e pagine in preview_mode dalle restrizioni iframe
        is_preview_page = (
            request.path.startswith('/gestionale/banners/preview/') or
            request.GET.get('preview_mode') == '1'
        )

        # Pagine di pagamento PayPal necessitano di form-action più permissivo
        is_payment_page = '/payment' in request.path and ('/gestionale/banner' in request.path or '/gestionale/pubbliredazionale' in request.path)

        # Cache headers per file statici
        if request.path.startswith('/static/'):
            # File statici: cache per 1 anno
            if any(request.path.endswith(ext) for ext in ['.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.woff', '.woff2', '.ttf', '.eot']):
                response['Cache-Control'] = 'public, max-age=31536000, immutable'
        elif request.path.startswith('/media/'):
            # Media files: cache per 1 settimana
            response['Cache-Control'] = 'public, max-age=604800'

        # Content Security Policy (CSP) per prevenire XSS
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com https://www.google-analytics.com https://ssl.google-analytics.com https://pagead2.googlesyndication.com https://adservice.google.com https://news.google.com https://tpc.googlesyndication.com https://googleads.g.doubleclick.net https://www.gstatic.com https://partner.googleadservices.com https://fundingchoicesmessages.google.com https://cse.google.com https://ep2.adtrafficquality.google",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://adservice.google.com https://www.gstatic.com https://news.google.com",
            "img-src 'self' data: https: http:",  # Permetti immagini da qualsiasi fonte HTTPS
            "font-src 'self' https://fonts.gstatic.com https://www.gstatic.com",
            "connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://stats.g.doubleclick.net https://region1.google-analytics.com https://region1.analytics.google.com https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net https://adservice.google.com https://news.google.com https://ep1.adtrafficquality.google https://ep2.adtrafficquality.google https://fundingchoicesmessages.google.com",
            "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com https://tpc.googlesyndication.com https://googleads.g.doubleclick.net https://td.doubleclick.net https://www.google.com https://cse.google.com https://fundingchoicesmessages.google.com",
            "child-src 'self' https://www.youtube.com https://googleads.g.doubleclick.net",
            "object-src 'none'",
            "base-uri 'self'",
        ]

        # form-action: permetti PayPal per pagine di pagamento
        if is_payment_page:
            csp_directives.append("form-action 'self' https://www.paypal.com https://www.sandbox.paypal.com")
        else:
            csp_directives.append("form-action 'self'")

        # frame-ancestors: permetti 'self' per le pagine di preview admin
        if is_preview_page:
            csp_directives.append("frame-ancestors 'self'")
        else:
            csp_directives.append("frame-ancestors 'none'")

        # upgrade-insecure-requests solo in produzione
        if not is_preview_page:
            csp_directives.append("upgrade-insecure-requests")

        response['Content-Security-Policy'] = "; ".join(csp_directives)

        # Altri header di sicurezza
        response['X-Content-Type-Options'] = 'nosniff'

        # X-Frame-Options: permetti SAMEORIGIN per preview, altrimenti DENY
        if is_preview_page:
            response['X-Frame-Options'] = 'SAMEORIGIN'
        else:
            response['X-Frame-Options'] = 'DENY'

        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

        return response
