from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),

    # Banner URLs
    path('banners/', views.banner_list, name='banner_list'),
    path('banners/create/', views.banner_create, name='banner_create'),
    path('banners/<int:banner_id>/edit/', views.banner_edit, name='banner_edit'),
    path('banners/<int:banner_id>/delete/', views.banner_delete, name='banner_delete'),
    path('banners/<int:banner_id>/payment/', views.banner_payment, name='banner_payment'),
    path('banner/<int:banner_id>/payment/success/', views.banner_payment_success, name='banner_payment_success'),
    path('banner/<int:banner_id>/payment/cancel/', views.banner_payment_cancel, name='banner_payment_cancel'),

    # Public URLs
    path('banner/<int:banner_id>/click/', views.banner_click, name='banner_click'),
    path('banners/preview/layout/', views.banner_preview_layout, name='banner_preview_layout'),
]
