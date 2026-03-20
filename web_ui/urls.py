"""URL configuration for the Web UI application."""

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

app_name = 'web_ui'

urlpatterns = [
    path('', views.home, name='home'),
    path('profile/', views.profile, name='profile'),
    path('profile/download-cert/', views.download_my_cert, name='download_my_cert'),
    path('profile/download-ca/', views.download_ca_cert, name='download_ca_cert'),
    path('geofences/', views.geofences, name='geofences'),
    path('admin-panel/', views.admin_panel, name='admin_panel'),
    path('admin-panel/smtp-test/', views.smtp_test, name='smtp_test'),
    path('about/', views.about, name='about'),
    path('health/', views.health, name='health'),
    path('network-info/', views.network_info, name='network_info'),
    path('login/', LoginView.as_view(template_name='web_ui/login.html'), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
