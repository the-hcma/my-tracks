"""URL routing for tracker app."""

from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.routers import DefaultRouter

from .views import CommandViewSet, DeviceViewSet, LocationViewSet

router = DefaultRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'devices', DeviceViewSet, basename='device')
router.register(r'commands', CommandViewSet, basename='command')

urlpatterns: list[URLPattern | URLResolver] = [
    path('', include(router.urls)),
]
