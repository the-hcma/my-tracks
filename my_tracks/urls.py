"""URL routing for tracker app."""

from django.urls import include, path, re_path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.routers import DefaultRouter

from .views import (AccountViewSet, AdminUserViewSet,
                    CertificateAuthorityViewSet, ClientCertificateViewSet,
                    CommandViewSet, CRLViewSet, DeviceViewSet, HealthViewSet,
                    LocationViewSet, ServerCertificateViewSet)


class OptionalSlashRouter(DefaultRouter):
    """Router that accepts URLs both with and without trailing slashes."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.trailing_slash = "/?"


router = OptionalSlashRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'devices', DeviceViewSet, basename='device')
router.register(r'commands', CommandViewSet, basename='command')
router.register(r'admin/users', AdminUserViewSet, basename='admin-user')
router.register(r'admin/pki/ca', CertificateAuthorityViewSet, basename='admin-ca')
router.register(r'admin/pki/server-cert', ServerCertificateViewSet, basename='admin-server-cert')
router.register(r'admin/pki/client-certs', ClientCertificateViewSet, basename='admin-client-cert')
router.register(r'admin/pki/crl', CRLViewSet, basename='admin-crl')
router.register(r'health', HealthViewSet, basename='health')

account_list = AccountViewSet.as_view({'get': 'list', 'patch': 'partial_update'})
account_change_password = AccountViewSet.as_view({'post': 'change_password'})

urlpatterns: list[URLPattern | URLResolver] = [
    re_path(r'^account/?$', account_list, name='account'),
    re_path(r'^account/change-password/?$', account_change_password, name='account-change-password'),
    path('', include(router.urls)),
]
