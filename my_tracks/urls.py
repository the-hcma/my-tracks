"""URL routing for tracker app."""

from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.routers import DefaultRouter

from .views import CommandViewSet, DeviceViewSet, LocationViewSet


class OptionalSlashRouter(DefaultRouter):
    """Router that accepts URLs both with and without trailing slashes."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.trailing_slash = "/?"


router = OptionalSlashRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'devices', DeviceViewSet, basename='device')
router.register(r'commands', CommandViewSet, basename='command')

urlpatterns: list[URLPattern | URLResolver] = [
    path('', include(router.urls)),
]
