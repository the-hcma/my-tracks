"""URL routing for tracker app."""
from typing import List

from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.routers import DefaultRouter

from .views import DeviceViewSet, LocationViewSet

router = DefaultRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'devices', DeviceViewSet, basename='device')

urlpatterns: List[URLPattern | URLResolver] = [
    path('', include(router.urls)),
]
