"""
URL configuration for my_tracks project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
"""

from django.contrib import admin
from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = [
    path('', include('web_ui.urls')),
    path('admin/', admin.site.urls),
    path('api/', include('app.urls')),
]
