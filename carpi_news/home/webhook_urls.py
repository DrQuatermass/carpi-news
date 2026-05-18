from django.urls import path

from .views_webhooks import instagram_webhook

urlpatterns = [
    path('', instagram_webhook, name='instagram_webhook'),
]
