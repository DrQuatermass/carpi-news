from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Banner URLs
    path('banners/create/', views.banner_create, name='banner_create'),
    path('banners/<int:banner_id>/edit/', views.banner_edit, name='banner_edit'),
    path('banners/<int:banner_id>/delete/', views.banner_delete, name='banner_delete'),
    path('banners/<int:banner_id>/toggle-status/', views.banner_toggle_status, name='banner_toggle_status'),
    path('banners/<int:banner_id>/payment/', views.banner_payment, name='banner_payment'),
    path('banner/<int:banner_id>/payment/success/', views.banner_payment_success, name='banner_payment_success'),
    path('banner/<int:banner_id>/payment/cancel/', views.banner_payment_cancel, name='banner_payment_cancel'),

    # Public URLs
    path('banner/<int:banner_id>/click/', views.banner_click, name='banner_click'),
    path('banner/<int:banner_id>/impression/', views.banner_impression, name='banner_impression'),
    path('banners/preview/layout/', views.banner_preview_layout, name='banner_preview_layout'),

    # Pubbliredazionale URLs
    path('pubbliredazionale/create/', views.pubbliredazionale_create, name='pubbliredazionale_create'),
    path('pubbliredazionale/<int:pubbliredazionale_id>/interview/', views.pubbliredazionale_interview, name='pubbliredazionale_interview'),
    path('pubbliredazionale/<int:pubbliredazionale_id>/preview/', views.pubbliredazionale_preview, name='pubbliredazionale_preview'),
    path('pubbliredazionale/<int:pubbliredazionale_id>/delete/', views.pubbliredazionale_delete, name='pubbliredazionale_delete'),
    path('pubbliredazionale/<int:pubbliredazionale_id>/payment/', views.pubbliredazionale_payment, name='pubbliredazionale_payment'),
    path('pubbliredazionale/<int:pubbliredazionale_id>/payment/success/', views.pubbliredazionale_payment_success, name='pubbliredazionale_payment_success'),
    path('pubbliredazionale/<int:pubbliredazionale_id>/payment/cancel/', views.pubbliredazionale_payment_cancel, name='pubbliredazionale_payment_cancel'),

    # API Codici Promozionali
    path('validate-promo-code/', views.validate_promo_code, name='validate_promo_code'),
]
