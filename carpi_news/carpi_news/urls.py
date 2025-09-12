"""
URL configuration for carpi_news project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from home import views
from home.feeds import ArticoliFeedRSS, ArticoliFeedAtom, ArticoliRecentiFeed

urlpatterns = [
    path('',views.home, name='home'),
    path('articolo/<slug:slug>/', views.dettaglio_articolo, name='dettaglio-articolo'),
    path('privacy-policy/', views.privacy_policy, name='privacy-policy'),
    
    # RSS Feeds per IFTTT e social sharing
    path('feed/rss/', ArticoliFeedRSS(), name='rss-feed'),
    path('feed/atom/', ArticoliFeedAtom(), name='atom-feed'),
    path('feed/recenti/', ArticoliRecentiFeed(), name='recenti-feed'),
    
    # SEO e bot management
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots'),
    
    path('admin/', admin.site.urls),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
