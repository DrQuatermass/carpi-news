from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Banner URLs
    path('banners/', views.banner_list, name='banner_list'),
    path('banners/create/', views.banner_create, name='banner_create'),
    path('banners/<int:banner_id>/edit/', views.banner_edit, name='banner_edit'),
    path('banners/<int:banner_id>/delete/', views.banner_delete, name='banner_delete'),
    path('banners/<int:banner_id>/payment/', views.banner_payment, name='banner_payment'),

    # Public URLs
    path('banner/<int:banner_id>/click/', views.banner_click, name='banner_click'),
]
