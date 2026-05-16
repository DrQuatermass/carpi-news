"""
URL configuration for carpi_news project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView, RedirectView
from home import views
from home.feeds import ArticoliFeedRSS, ArticoliFeedAtom, ArticoliRecentiFeed
from home.image_proxy import image_proxy_view

urlpatterns = [
    path('', views.home, name='home'),
    path('articolo/<slug:slug>/', views.dettaglio_articolo, name='dettaglio_articolo'),
    path('articolo/<slug:slug>/fonti/', views.fonti_articolo, name='fonti_articolo'),
    path('privacy-policy/', views.privacy_policy, name='privacy-policy'),
    path('about/', views.about, name='about'),
    path('pubblicita/', views.pubblicita, name='pubblicita'),
    path('caplet/', views.caplet, name='caplet'),
    path('cinema/', views.programmazione_cinema, name='programmazione_cinema'),
    path('eventi/', views.calendario_eventi, name='calendario_eventi'),

    # Link in bio Instagram: lista mobile-first degli articoli condivisi su IG
    path('instagram/', views.link_in_bio, name='link_in_bio'),

    # Chatbot API
    path('api/chatbot/', views.chatbot_api, name='chatbot_api'),
    path('chatbot/risultati/', views.chatbot_results, name='chatbot_results'),

    # Image Proxy per ottimizzazione immagini esterne
    path('image-proxy/', image_proxy_view, name='image_proxy'),

    # RSS Feeds per IFTTT e social sharing
    path('feed/rss/', ArticoliFeedRSS(), name='rss-feed'),
    path('feed/atom/', ArticoliFeedAtom(), name='atom-feed'),
    path('feed/recenti/', ArticoliRecentiFeed(), name='recenti-feed'),

    # Favicon
    path('favicon.ico', RedirectView.as_view(url='/static/home/images/portico_logo_square_512.png', permanent=True)),

    # SEO e bot management
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots'),
    path('ads.txt', TemplateView.as_view(template_name='ads.txt', content_type='text/plain'), name='ads'),

    # IndexNow verification key
    path('6a01617c502be60a3fb719998c057c18.txt', views.indexnow_key, name='indexnow_key'),

    # Sitemap URLs (SEO ottimizzato)
    path('sitemap_index.xml', views.sitemap_index, name='sitemap_index'),
    path('sitemap.xml', views.sitemap, name='sitemap'),
    path('sitemap-archive.xml', views.sitemap_archive, name='sitemap_archive'),
    path('sitemap-news.xml', views.news_sitemap, name='news_sitemap'),

    # Newsletter
    path('newsletter/', views.newsletter_subscribe, name='newsletter_subscribe'),
    path('newsletter/disiscrivi/<uuid:token>/', views.newsletter_unsubscribe, name='newsletter_unsubscribe'),
    path('newsletter/preview/', views.newsletter_preview, name='newsletter_preview'),

    # Admin panel per banner e gestione
    path('gestionale/', include('admin_panel.urls')),

    path('admin/', admin.site.urls),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
