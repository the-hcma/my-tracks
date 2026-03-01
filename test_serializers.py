"""
Test suite for my_tracks serializers.

Covers DeviceSerializer, LocationSerializer, UserSerializer,
UserProfileSerializer, ChangePasswordSerializer, and certificate serializers.
"""
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from hamcrest import (assert_that, calling, contains_string, equal_to,
                      greater_than, has_entries, has_key, has_length,
                      instance_of, is_, is_not, none, not_none, raises)
from rest_framework import serializers, status
from rest_framework.test import APIRequestFactory

from my_tracks.models import (CertificateAuthority, ClientCertificate, Device,
                               Location, ServerCertificate, UserProfile)
from my_tracks.serializers import (CertificateAuthoritySerializer,
                                    ChangePasswordSerializer,
                                    ClientCertificateSerializer,
                                    DeviceSerializer, LocationSerializer,
                                    ServerCertificateSerializer,
                                    UserProfileSerializer, UserSerializer)

factory = APIRequestFactory()


@pytest.fixture
def device(db: Any) -> Device:
    """Create a device for serializer tests."""
    return Device.objects.create(device_id="phone1", name="My Phone", mqtt_user="alice")


@pytest.fixture
def device_no_mqtt(db: Any) -> Device:
    """Create a device without an mqtt_user."""
    return Device.objects.create(device_id="phone2", name="No MQTT Phone")


@pytest.fixture
def location(device: Device) -> Location:
    """Create a location attached to a device."""
    return Location.objects.create(
        device=device,
        latitude=Decimal("51.5074"),
        longitude=Decimal("-0.1278"),
        timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        accuracy=10,
        altitude=30,
        velocity=5,
        battery_level=72,
        connection_type="w",
        tracker_id="AB",
        ip_address="10.0.0.1",
    )


@pytest.fixture
def owntracks_payload() -> dict[str, Any]:
    """Minimal valid OwnTracks payload using device_id."""
    return {
        "_type": "location",
        "device_id": "phone1",
        "lat": Decimal("48.8566"),
        "lon": Decimal("2.3522"),
        "tst": 1718450000,
        "acc": 8,
        "alt": 35,
        "vel": 3,
        "batt": 65,
        "conn": "w",
        "tid": "AB",
    }


@pytest.fixture
def ca(db: Any) -> CertificateAuthority:
    """Create a test Certificate Authority."""
    return CertificateAuthority.objects.create(
        common_name="Test Root CA",
        certificate_pem="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
        encrypted_private_key=b"encrypted-key-bytes",
        fingerprint="AA:BB:CC:DD",
        key_size=4096,
        not_valid_before=timezone.now() - timedelta(days=1),
        not_valid_after=timezone.now() + timedelta(days=365),
        is_active=True,
    )


@pytest.fixture
def server_cert(ca: CertificateAuthority) -> ServerCertificate:
    """Create a test server certificate."""
    return ServerCertificate.objects.create(
        issuing_ca=ca,
        common_name="mqtt.example.com",
        certificate_pem="-----BEGIN CERTIFICATE-----\nserver\n-----END CERTIFICATE-----",
        encrypted_private_key=b"server-key",
        fingerprint="11:22:33:44",
        san_entries=["mqtt.example.com", "192.168.1.1"],
        key_size=4096,
        not_valid_before=timezone.now() - timedelta(days=1),
        not_valid_after=timezone.now() + timedelta(days=365),
        is_active=True,
    )


@pytest.fixture
def client_cert(ca: CertificateAuthority, user: User) -> ClientCertificate:
    """Create a test client certificate."""
    return ClientCertificate.objects.create(
        user=user,
        issuing_ca=ca,
        common_name="testuser",
        certificate_pem="-----BEGIN CERTIFICATE-----\nclient\n-----END CERTIFICATE-----",
        encrypted_private_key=b"client-key",
        fingerprint="55:66:77:88",
        serial_number="ABCDEF01",
        key_size=4096,
        not_valid_before=timezone.now() - timedelta(days=1),
        not_valid_after=timezone.now() + timedelta(days=365),
        is_active=True,
        revoked=False,
    )


# ---------------------------------------------------------------------------
# DeviceSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeviceSerializer:
    """Tests for DeviceSerializer computed fields."""

    def test_location_count_no_locations(self, device: Device) -> None:
        """location_count returns 0 when no locations exist."""
        data = DeviceSerializer(device).data
        assert_that(data["location_count"], equal_to(0))

    def test_location_count_with_locations(self, device: Device) -> None:
        """location_count reflects actual number of related locations."""
        for i in range(3):
            Location.objects.create(
                device=device,
                latitude=Decimal("50.0"),
                longitude=Decimal("8.0"),
                timestamp=timezone.now() - timedelta(minutes=i),
            )
        data = DeviceSerializer(device).data
        assert_that(data["location_count"], equal_to(3))

    def test_mqtt_topic_id_with_mqtt_user(self, device: Device) -> None:
        """mqtt_topic_id returns 'user/device' when mqtt_user is set."""
        data = DeviceSerializer(device).data
        assert_that(data["mqtt_topic_id"], equal_to("alice/phone1"))

    def test_mqtt_topic_id_without_mqtt_user(self, device_no_mqtt: Device) -> None:
        """mqtt_topic_id returns empty string when mqtt_user is blank."""
        data = DeviceSerializer(device_no_mqtt).data
        assert_that(data["mqtt_topic_id"], equal_to(""))

    def test_serialized_fields_present(self, device: Device) -> None:
        """All expected fields are present in serialized output."""
        data = DeviceSerializer(device).data
        for field in ("id", "device_id", "name", "created_at", "last_seen",
                      "is_online", "location_count", "mqtt_user", "mqtt_topic_id"):
            assert_that(data, has_key(field))


# ---------------------------------------------------------------------------
# LocationSerializer — read path (serialization)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLocationSerializerRead:
    """Tests for LocationSerializer read-only / computed fields."""

    def test_device_name_custom(self, location: Location) -> None:
        """device_name returns custom name when set."""
        data = LocationSerializer(location).data
        assert_that(data["device_name"], equal_to("My Phone"))

    def test_device_name_falls_back_to_device_id(self, db: Any) -> None:
        """device_name returns device_id when name starts with 'Device '."""
        dev = Device.objects.create(device_id="fallback01", name="Device fallback01")
        loc = Location.objects.create(
            device=dev,
            latitude=Decimal("40.0"),
            longitude=Decimal("-74.0"),
            timestamp=timezone.now(),
        )
        data = LocationSerializer(loc).data
        assert_that(data["device_name"], equal_to("fallback01"))

    def test_device_id_display(self, location: Location) -> None:
        """device_id_display returns the device's device_id."""
        data = LocationSerializer(location).data
        assert_that(data["device_id_display"], equal_to("phone1"))

    def test_tid_display_with_tracker_id(self, location: Location) -> None:
        """tid_display returns the tracker_id when present."""
        data = LocationSerializer(location).data
        assert_that(data["tid_display"], equal_to("AB"))

    def test_tid_display_empty_when_no_tracker_id(self, db: Any) -> None:
        """tid_display returns empty string when tracker_id is blank."""
        dev = Device.objects.create(device_id="notid01")
        loc = Location.objects.create(
            device=dev,
            latitude=Decimal("0.0"),
            longitude=Decimal("0.0"),
            timestamp=timezone.now(),
            tracker_id="",
        )
        data = LocationSerializer(loc).data
        assert_that(data["tid_display"], equal_to(""))

    def test_timestamp_unix(self, location: Location) -> None:
        """timestamp_unix returns an integer Unix timestamp."""
        data = LocationSerializer(location).data
        expected = int(location.timestamp.timestamp())
        assert_that(data["timestamp_unix"], equal_to(expected))


# ---------------------------------------------------------------------------
# LocationSerializer — write path (deserialization / validate / create)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLocationSerializerWrite:
    """Tests for LocationSerializer validation and creation logic."""

    def test_valid_owntracks_payload(self, owntracks_payload: dict[str, Any]) -> None:
        """A fully-populated OwnTracks payload passes validation."""
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))

    def test_field_mapping_lat_lon_tst(self, owntracks_payload: dict[str, Any]) -> None:
        """lat, lon, tst are mapped to latitude, longitude, timestamp."""
        serializer = LocationSerializer(data=owntracks_payload)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        assert_that(vd["latitude"], equal_to(Decimal("48.8566")))
        assert_that(vd["longitude"], equal_to(Decimal("2.3522")))
        assert_that(vd["timestamp"], instance_of(datetime))

    def test_long_field_accepted(self, owntracks_payload: dict[str, Any]) -> None:
        """'long' is accepted as an alternative to 'lon'."""
        del owntracks_payload["lon"]
        owntracks_payload["long"] = Decimal("2.3522")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))
        assert_that(serializer.validated_data["longitude"], equal_to(Decimal("2.3522")))

    def test_lon_zero_is_valid(self, owntracks_payload: dict[str, Any]) -> None:
        """lon=0 (prime meridian) must not be treated as missing."""
        owntracks_payload["lon"] = Decimal("0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))
        assert_that(serializer.validated_data["longitude"], equal_to(Decimal("0")))

    def test_topic_based_device_id(self, db: Any) -> None:
        """Device is identified via the 'topic' field if device_id absent."""
        payload = {
            "_type": "location",
            "topic": "owntracks/alice/pixel",
            "lat": Decimal("52.52"),
            "lon": Decimal("13.405"),
            "tst": 1718450000,
        }
        serializer = LocationSerializer(data=payload)
        assert_that(serializer.is_valid(), is_(True))
        assert_that(serializer.validated_data["device"].device_id, equal_to("pixel"))

    def test_tid_based_device_id(self, db: Any) -> None:
        """Device is identified via 'tid' when both device_id and topic are absent."""
        payload = {
            "_type": "location",
            "tid": "XY",
            "lat": Decimal("35.6762"),
            "lon": Decimal("139.6503"),
            "tst": 1718450000,
        }
        serializer = LocationSerializer(data=payload)
        assert_that(serializer.is_valid(), is_(True))
        assert_that(serializer.validated_data["device"].device_id, equal_to("XY"))

    def test_missing_device_identification_raises(self, db: Any) -> None:
        """Validation fails when device_id, topic, and tid are all absent."""
        payload = {
            "_type": "location",
            "lat": Decimal("35.0"),
            "lon": Decimal("139.0"),
            "tst": 1718450000,
        }
        serializer = LocationSerializer(data=payload)
        assert_that(serializer.is_valid(), is_(False))
        error_text = str(serializer.errors)
        assert_that(error_text, contains_string("device_id"))

    def test_missing_lat_raises(self, owntracks_payload: dict[str, Any]) -> None:
        """Validation fails when 'lat' is missing."""
        del owntracks_payload["lat"]
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("lat"))

    def test_missing_lon_and_long_raises(self, owntracks_payload: dict[str, Any]) -> None:
        """Validation fails when both 'lon' and 'long' are missing."""
        del owntracks_payload["lon"]
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("lon"))

    def test_missing_tst_raises(self, owntracks_payload: dict[str, Any]) -> None:
        """Validation fails when 'tst' is missing."""
        del owntracks_payload["tst"]
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("tst"))

    def test_latitude_out_of_range_positive(self, owntracks_payload: dict[str, Any]) -> None:
        """Latitude > 90 is rejected."""
        owntracks_payload["lat"] = Decimal("91.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("latitude"))

    def test_latitude_out_of_range_negative(self, owntracks_payload: dict[str, Any]) -> None:
        """Latitude < -90 is rejected."""
        owntracks_payload["lat"] = Decimal("-91.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("latitude"))

    def test_longitude_out_of_range_positive(self, owntracks_payload: dict[str, Any]) -> None:
        """Longitude > 180 is rejected."""
        owntracks_payload["lon"] = Decimal("181.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("longitude"))

    def test_longitude_out_of_range_negative(self, owntracks_payload: dict[str, Any]) -> None:
        """Longitude < -180 is rejected."""
        owntracks_payload["lon"] = Decimal("-181.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("longitude"))

    def test_battery_level_over_100_rejected(self, owntracks_payload: dict[str, Any]) -> None:
        """Battery level above 100 is rejected."""
        owntracks_payload["batt"] = 101
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("battery"))

    def test_battery_level_negative_rejected(self, owntracks_payload: dict[str, Any]) -> None:
        """Battery level below 0 is rejected."""
        owntracks_payload["batt"] = -1
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("battery"))

    def test_battery_level_none_accepted(self, owntracks_payload: dict[str, Any]) -> None:
        """Omitting battery level is valid (optional field)."""
        del owntracks_payload["batt"]
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))

    def test_device_created_on_first_location(self, db: Any) -> None:
        """A new Device is created when device_id doesn't exist yet."""
        payload = {
            "_type": "location",
            "device_id": "brand_new_device",
            "lat": Decimal("10.0"),
            "lon": Decimal("20.0"),
            "tst": 1718450000,
        }
        serializer = LocationSerializer(data=payload)
        assert_that(serializer.is_valid(), is_(True))
        assert_that(Device.objects.filter(device_id="brand_new_device").exists(), is_(True))

    def test_existing_device_reused(self, device: Device, owntracks_payload: dict[str, Any]) -> None:
        """Existing device is reused rather than creating a duplicate."""
        count_before = Device.objects.count()
        serializer = LocationSerializer(data=owntracks_payload)
        serializer.is_valid(raise_exception=True)
        assert_that(Device.objects.count(), equal_to(count_before))

    def test_create_with_client_ip(self, owntracks_payload: dict[str, Any]) -> None:
        """create() stores client_ip from serializer context."""
        serializer = LocationSerializer(
            data=owntracks_payload,
            context={"client_ip": "192.168.1.42"},
        )
        serializer.is_valid(raise_exception=True)
        loc = serializer.save()
        assert_that(loc.ip_address, equal_to("192.168.1.42"))

    def test_create_without_client_ip(self, owntracks_payload: dict[str, Any]) -> None:
        """create() works when no client_ip is in context."""
        serializer = LocationSerializer(data=owntracks_payload, context={})
        serializer.is_valid(raise_exception=True)
        loc = serializer.save()
        assert_that(loc.ip_address, is_(none()))

    def test_optional_fields_stored(self, owntracks_payload: dict[str, Any]) -> None:
        """Optional OwnTracks fields (acc, alt, vel, conn) are persisted."""
        serializer = LocationSerializer(
            data=owntracks_payload, context={"client_ip": "10.0.0.1"}
        )
        serializer.is_valid(raise_exception=True)
        loc = serializer.save()
        assert_that(loc.accuracy, equal_to(8))
        assert_that(loc.altitude, equal_to(35))
        assert_that(loc.velocity, equal_to(3))
        assert_that(loc.battery_level, equal_to(65))
        assert_that(loc.connection_type, equal_to("w"))
        assert_that(loc.tracker_id, equal_to("AB"))

    def test_boundary_latitude_90(self, owntracks_payload: dict[str, Any]) -> None:
        """Latitude exactly 90 is valid."""
        owntracks_payload["lat"] = Decimal("90.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))

    def test_boundary_latitude_negative_90(self, owntracks_payload: dict[str, Any]) -> None:
        """Latitude exactly -90 is valid."""
        owntracks_payload["lat"] = Decimal("-90.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))

    def test_boundary_longitude_180(self, owntracks_payload: dict[str, Any]) -> None:
        """Longitude exactly 180 is valid."""
        owntracks_payload["lon"] = Decimal("180.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))

    def test_boundary_longitude_negative_180(self, owntracks_payload: dict[str, Any]) -> None:
        """Longitude exactly -180 is valid."""
        owntracks_payload["lon"] = Decimal("-180.0")
        serializer = LocationSerializer(data=owntracks_payload)
        assert_that(serializer.is_valid(), is_(True))


# ---------------------------------------------------------------------------
# UserSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserSerializer:
    """Tests for UserSerializer."""

    def test_serializes_user_fields(self, user: User) -> None:
        """All expected user fields appear in serialized output."""
        data = UserSerializer(user).data
        assert_that(data["username"], equal_to("testuser"))
        assert_that(data["email"], equal_to("test@example.com"))
        assert_that(data, has_key("id"))
        assert_that(data, has_key("date_joined"))
        assert_that(data, has_key("is_active"))
        assert_that(data, has_key("is_staff"))


# ---------------------------------------------------------------------------
# UserProfileSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserProfileSerializer:
    """Tests for UserProfileSerializer nested user fields."""

    def test_nested_username(self, user: User) -> None:
        """username is sourced from the related User."""
        profile = user.profile
        data = UserProfileSerializer(profile).data
        assert_that(data["username"], equal_to("testuser"))

    def test_nested_email(self, user: User) -> None:
        """email is sourced from the related User."""
        data = UserProfileSerializer(user.profile).data
        assert_that(data["email"], equal_to("test@example.com"))

    def test_nested_is_staff(self, admin_user: User) -> None:
        """is_staff is True for admin users."""
        data = UserProfileSerializer(admin_user.profile).data
        assert_that(data["is_staff"], is_(True))

    def test_timestamps_present(self, user: User) -> None:
        """created_at and updated_at are included."""
        data = UserProfileSerializer(user.profile).data
        assert_that(data, has_key("created_at"))
        assert_that(data, has_key("updated_at"))


# ---------------------------------------------------------------------------
# ChangePasswordSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangePasswordSerializer:
    """Tests for ChangePasswordSerializer current_password validation."""

    def _make_context(self, user: User) -> dict[str, Any]:
        """Build a minimal serializer context with an authenticated request."""
        request = factory.post("/fake-url/")
        request.user = user
        return {"request": request}

    def test_correct_current_password(self, user: User) -> None:
        """Validation passes when current_password matches."""
        ctx = self._make_context(user)
        serializer = ChangePasswordSerializer(
            data={"current_password": "testpass123", "new_password": "newsecure99"},
            context=ctx,
        )
        assert_that(serializer.is_valid(), is_(True))

    def test_incorrect_current_password(self, user: User) -> None:
        """Validation fails when current_password is wrong."""
        ctx = self._make_context(user)
        serializer = ChangePasswordSerializer(
            data={"current_password": "wrongpass", "new_password": "newsecure99"},
            context=ctx,
        )
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("incorrect"))

    def test_new_password_too_short(self, user: User) -> None:
        """Validation fails when new_password is shorter than min_length."""
        ctx = self._make_context(user)
        serializer = ChangePasswordSerializer(
            data={"current_password": "testpass123", "new_password": "short"},
            context=ctx,
        )
        assert_that(serializer.is_valid(), is_(False))
        assert_that(str(serializer.errors), contains_string("new_password"))


# ---------------------------------------------------------------------------
# CertificateAuthoritySerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCertificateAuthoritySerializer:
    """Tests for CertificateAuthoritySerializer."""

    def test_serializes_ca_fields(self, ca: CertificateAuthority) -> None:
        """All public CA fields are present."""
        data = CertificateAuthoritySerializer(ca).data
        assert_that(data["common_name"], equal_to("Test Root CA"))
        assert_that(data["fingerprint"], equal_to("AA:BB:CC:DD"))
        assert_that(data["key_size"], equal_to(4096))
        assert_that(data["is_active"], is_(True))
        assert_that(data, has_key("certificate_pem"))
        assert_that(data, has_key("not_valid_before"))
        assert_that(data, has_key("not_valid_after"))
        assert_that(data, has_key("created_at"))

    def test_all_fields_read_only(self, ca: CertificateAuthority) -> None:
        """Attempting to write fields via serializer does not change values."""
        serializer = CertificateAuthoritySerializer(
            ca, data={"common_name": "Hacked CA"}, partial=True
        )
        if serializer.is_valid():
            instance = serializer.save()
            assert_that(instance.common_name, equal_to("Test Root CA"))


# ---------------------------------------------------------------------------
# ServerCertificateSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestServerCertificateSerializer:
    """Tests for ServerCertificateSerializer."""

    def test_serializes_server_cert_fields(self, server_cert: ServerCertificate) -> None:
        """All expected fields including issuing_ca_name are present."""
        data = ServerCertificateSerializer(server_cert).data
        assert_that(data["common_name"], equal_to("mqtt.example.com"))
        assert_that(data["fingerprint"], equal_to("11:22:33:44"))
        assert_that(data["key_size"], equal_to(4096))
        assert_that(data["is_active"], is_(True))
        assert_that(data, has_key("san_entries"))
        assert_that(data, has_key("certificate_pem"))

    def test_issuing_ca_name(self, server_cert: ServerCertificate) -> None:
        """issuing_ca_name returns the CA's common_name."""
        data = ServerCertificateSerializer(server_cert).data
        assert_that(data["issuing_ca_name"], equal_to("Test Root CA"))


# ---------------------------------------------------------------------------
# ClientCertificateSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClientCertificateSerializer:
    """Tests for ClientCertificateSerializer."""

    def test_serializes_client_cert_fields(self, client_cert: ClientCertificate) -> None:
        """All expected fields are present."""
        data = ClientCertificateSerializer(client_cert).data
        assert_that(data["common_name"], equal_to("testuser"))
        assert_that(data["fingerprint"], equal_to("55:66:77:88"))
        assert_that(data["serial_number"], equal_to("ABCDEF01"))
        assert_that(data["key_size"], equal_to(4096))
        assert_that(data["is_active"], is_(True))
        assert_that(data["revoked"], is_(False))

    def test_issuing_ca_name(self, client_cert: ClientCertificate) -> None:
        """issuing_ca_name returns the CA's common_name."""
        data = ClientCertificateSerializer(client_cert).data
        assert_that(data["issuing_ca_name"], equal_to("Test Root CA"))

    def test_username_from_user(self, client_cert: ClientCertificate) -> None:
        """username is sourced from the related User object."""
        data = ClientCertificateSerializer(client_cert).data
        assert_that(data["username"], equal_to("testuser"))

    def test_revoked_at_null_when_not_revoked(self, client_cert: ClientCertificate) -> None:
        """revoked_at is None when certificate is not revoked."""
        data = ClientCertificateSerializer(client_cert).data
        assert_that(data["revoked_at"], is_(none()))
