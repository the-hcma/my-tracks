"""URL routing for tracker app."""

from django.urls import include, path, re_path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.routers import DefaultRouter

from .admin_sync_export import AdminUsersWithDevicesExportView, AdminWaypointsExportView
from .domesti_bot_api import DomestiBotConfigView, DomestiBotPairView
from .views import (
    AccountViewSet,
    AdminUserViewSet,
    CertificateAuthorityViewSet,
    ClientCertificateViewSet,
    CommandViewSet,
    CRLViewSet,
    DeviceShareViewSet,
    DeviceViewSet,
    FriendRequestViewSet,
    FriendViewSet,
    HealthViewSet,
    LocationViewSet,
    ServerCertificateViewSet,
)


class OptionalSlashRouter(DefaultRouter):
    """Router that accepts URLs both with and without trailing slashes."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.trailing_slash = "/?"


router = OptionalSlashRouter()
router.register(r"locations", LocationViewSet, basename="location")
router.register(r"devices", DeviceViewSet, basename="device")
router.register(r"commands", CommandViewSet, basename="command")
router.register(r"admin/users", AdminUserViewSet, basename="admin-user")
router.register(r"admin/pki/ca", CertificateAuthorityViewSet, basename="admin-ca")
router.register(r"admin/pki/server-cert", ServerCertificateViewSet, basename="admin-server-cert")
router.register(r"admin/pki/client-certs", ClientCertificateViewSet, basename="admin-client-cert")
router.register(r"admin/pki/crl", CRLViewSet, basename="admin-crl")
router.register(r"health", HealthViewSet, basename="health")
# friends/requests must be registered before friends to avoid shadowing
router.register(r"friends/requests", FriendRequestViewSet, basename="friend-request")
router.register(r"friends", FriendViewSet, basename="friend")

account_list = AccountViewSet.as_view({"get": "list", "patch": "partial_update"})
account_change_password = AccountViewSet.as_view({"post": "change_password"})

# DeviceShareViewSet has two URL params so it needs manual wiring.
device_share_list = DeviceShareViewSet.as_view({"get": "list", "post": "create"})
device_share_detail = DeviceShareViewSet.as_view({"delete": "destroy"})

urlpatterns: list[URLPattern | URLResolver] = [
    re_path(r"^account/?$", account_list, name="account"),
    re_path(r"^account/change-password/?$", account_change_password, name="account-change-password"),
    re_path(
        r"^admin/users-with-devices/?$",
        AdminUsersWithDevicesExportView.as_view(),
        name="admin-users-with-devices-export",
    ),
    re_path(
        r"^admin/waypoints/?$",
        AdminWaypointsExportView.as_view(),
        name="admin-waypoints-export",
    ),
    re_path(
        r"^admin/domesti-bot/config/?$",
        DomestiBotConfigView.as_view(),
        name="admin-domesti-bot-config",
    ),
    re_path(
        r"^admin/domesti-bot/pair/?$",
        DomestiBotPairView.as_view(),
        name="admin-domesti-bot-pair",
    ),
    re_path(r"^friends/(?P<user_id>\d+)/shares/?$", device_share_list, name="device-share-list"),
    re_path(
        r"^friends/(?P<user_id>\d+)/shares/(?P<device_id>[^/]+)/?$",
        device_share_detail,
        name="device-share-detail",
    ),
    path("", include(router.urls)),
]
