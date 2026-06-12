"""Tests for read-path visibility: devices and locations filtered to owner + friends."""
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from hamcrest import assert_that, equal_to
from rest_framework import status
from rest_framework.test import APIClient

from app.location_latest import refresh_device_latest_location
from app.models import Device, DeviceShare, FriendRequest, Location
from app.views import CommandViewSet


@pytest.fixture
def alice(db: Any) -> User:
    return User.objects.create_user(username="alice", password="pass")


@pytest.fixture
def bob(db: Any) -> User:
    return User.objects.create_user(username="bob", password="pass")


@pytest.fixture
def charlie(db: Any) -> User:
    return User.objects.create_user(username="charlie", password="pass")


@pytest.fixture
def alice_client(alice: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=alice)
    return c


@pytest.fixture
def bob_client(bob: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=bob)
    return c


@pytest.fixture
def charlie_client(charlie: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=charlie)
    return c


@pytest.fixture
def staff_user(db: Any) -> User:
    return User.objects.create_user(username="staff", password="pass", is_staff=True)


@pytest.fixture
def staff_client(staff_user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=staff_user)
    return c


@pytest.fixture
def alice_device(alice: User) -> Device:
    return Device.objects.create(device_id="alice-phone", name="Alice Phone", owner=alice)


@pytest.fixture
def bob_device(bob: User) -> Device:
    return Device.objects.create(device_id="bob-phone", name="Bob Phone", owner=bob)


@pytest.fixture
def alice_location(alice_device: Device) -> Location:
    return Location.objects.create(
        device=alice_device,
        latitude=Decimal("51.5074"),
        longitude=Decimal("-0.1278"),
        timestamp=timezone.now(),
        accuracy=10,
    )


@pytest.fixture
def bob_location(bob_device: Device) -> Location:
    return Location.objects.create(
        device=bob_device,
        latitude=Decimal("51.5080"),
        longitude=Decimal("-0.1290"),
        timestamp=timezone.now(),
        accuracy=10,
    )


@pytest.fixture
def friendship(alice: User, bob: User) -> FriendRequest:
    return FriendRequest.objects.create(
        from_user=alice, to_user=bob, status=FriendRequest.ACCEPTED
    )


@pytest.fixture
def bob_shares_with_alice(bob_device: Device, alice: User, friendship: FriendRequest) -> DeviceShare:
    return DeviceShare.objects.create(device=bob_device, shared_with=alice)


class TestDeviceVisibility:
    def test_owner_sees_own_device(
        self, alice_client: APIClient, alice_device: Device
    ) -> None:
        response = alice_client.get("/api/devices/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        ids = [d["device_id"] for d in response.data["results"]]
        assert_that("alice-phone" in ids, equal_to(True))

    def test_friend_sees_shared_device(
        self,
        alice_client: APIClient,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        response = alice_client.get("/api/devices/")
        ids = [d["device_id"] for d in response.data["results"]]
        assert_that("bob-phone" in ids, equal_to(True))

    def test_friend_does_not_see_unshared_device(
        self,
        alice_client: APIClient,
        bob_device: Device,
        friendship: FriendRequest,
    ) -> None:
        # Bob has not shared his device with Alice
        response = alice_client.get("/api/devices/")
        ids = [d["device_id"] for d in response.data["results"]]
        assert_that("bob-phone" in ids, equal_to(False))

    def test_unrelated_user_does_not_see_device(
        self,
        charlie_client: APIClient,
        alice_device: Device,
    ) -> None:
        response = charlie_client.get("/api/devices/")
        ids = [d["device_id"] for d in response.data["results"]]
        assert_that("alice-phone" in ids, equal_to(False))

    def test_device_detail_accessible_to_friend(
        self,
        alice_client: APIClient,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        response = alice_client.get("/api/devices/bob-phone/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    def test_device_detail_denied_to_unrelated_user(
        self,
        charlie_client: APIClient,
        alice_device: Device,
    ) -> None:
        response = charlie_client.get("/api/devices/alice-phone/")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


class TestLocationVisibility:
    def test_owner_sees_own_location_history(
        self,
        alice_client: APIClient,
        alice_location: Location,
    ) -> None:
        response = alice_client.get("/api/locations/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["count"], equal_to(1))

    def test_friend_sees_shared_device_locations(
        self,
        alice_client: APIClient,
        bob_location: Location,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        response = alice_client.get("/api/locations/")
        assert_that(response.data["count"], equal_to(1))

    def test_friend_does_not_see_unshared_device_locations(
        self,
        alice_client: APIClient,
        bob_location: Location,
        friendship: FriendRequest,
    ) -> None:
        response = alice_client.get("/api/locations/")
        assert_that(response.data["count"], equal_to(0))

    def test_unrelated_user_sees_no_locations(
        self,
        charlie_client: APIClient,
        alice_location: Location,
    ) -> None:
        response = charlie_client.get("/api/locations/")
        assert_that(response.data["count"], equal_to(0))

    def test_device_filter_returns_404_for_unshared_device(
        self,
        alice_client: APIClient,
        bob_device: Device,
        bob_location: Location,
    ) -> None:
        response = alice_client.get("/api/locations/?device=bob-phone")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_device_filter_works_for_shared_device(
        self,
        alice_client: APIClient,
        bob_location: Location,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        response = alice_client.get("/api/locations/?device=bob-phone")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["count"], equal_to(1))

    def test_device_filter_returns_400_for_ambiguous_plain_device_id(
        self,
        alice_client: APIClient,
        alice: User,
        bob: User,
        friendship: FriendRequest,
    ) -> None:
        alice_phone = Device.objects.create(device_id="phone", name="Alice Phone", owner=alice)
        bob_phone = Device.objects.create(device_id="phone", name="Bob Phone", owner=bob)
        DeviceShare.objects.create(device=bob_phone, shared_with=alice)
        Location.objects.create(
            device=alice_phone,
            latitude=Decimal("51.5074"),
            longitude=Decimal("-0.1278"),
            timestamp=timezone.now(),
        )

        response = alice_client.get("/api/locations/?device=phone")
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Ambiguous device ID 'phone'; use owner/device_id"))

    def test_last_known_returns_400_for_ambiguous_plain_device_id(
        self,
        alice_client: APIClient,
        alice: User,
        bob: User,
        friendship: FriendRequest,
    ) -> None:
        Device.objects.create(device_id="phone", name="Alice Phone", owner=alice)
        bob_phone = Device.objects.create(device_id="phone", name="Bob Phone", owner=bob)
        DeviceShare.objects.create(device=bob_phone, shared_with=alice)

        response = alice_client.get("/api/locations/last-known/?device=phone")
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Ambiguous device ID 'phone'; use owner/device_id"))

    def test_device_locations_action_accessible_to_friend(
        self,
        alice_client: APIClient,
        bob_location: Location,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        response = alice_client.get("/api/devices/bob-phone/locations/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    def test_device_locations_action_denied_to_unrelated(
        self,
        charlie_client: APIClient,
        alice_device: Device,
        alice_location: Location,
    ) -> None:
        response = charlie_client.get("/api/devices/alice-phone/locations/")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_friend_can_poll_shared_device(
        self,
        alice_client: APIClient,
        bob_device: Device,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        bob_device.mqtt_user = "bob_mqtt"
        bob_device.save()
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)
        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = alice_client.post(
                "/api/commands/report-location/",
                {"device_id": "bob_mqtt/bob-phone"},
                format="json",
            )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("bob_mqtt/bob-phone"))


class TestLastKnownLocations:
    def test_location_create_maintains_device_latest_location(
        self,
        alice_device: Device,
    ) -> None:
        older = timezone.now() - timezone.timedelta(hours=1)
        newer = timezone.now()
        Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.0"),
            longitude=Decimal("-0.1"),
            timestamp=older,
        )
        alice_latest = Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.1"),
            longitude=Decimal("-0.2"),
            timestamp=newer,
        )

        alice_device.refresh_from_db()
        assert_that(alice_device.latest_location_id, equal_to(alice_latest.id))

    def test_refresh_device_latest_location_backfills_pointer(
        self,
        alice_device: Device,
    ) -> None:
        older = timezone.now() - timezone.timedelta(hours=1)
        newer = timezone.now()
        Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.0"),
            longitude=Decimal("-0.1"),
            timestamp=older,
        )
        alice_latest = Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.1"),
            longitude=Decimal("-0.2"),
            timestamp=newer,
        )
        Device.objects.filter(pk=alice_device.pk).update(latest_location_id=None)

        refresh_device_latest_location(alice_device.pk)

        alice_device.refresh_from_db()
        assert_that(alice_device.latest_location_id, equal_to(alice_latest.id))

    def test_staff_last_known_returns_all_devices(
        self,
        staff_client: APIClient,
        db: Any,
    ) -> None:
        now = timezone.now()
        expected_ids: list[int] = []
        for index in range(10):
            owner = User.objects.create_user(username=f"user{index}", password="pass")
            device = Device.objects.create(device_id=f"phone-{index}", owner=owner)
            location = Location.objects.create(
                device=device,
                latitude=Decimal("51.0") + Decimal(index) / Decimal("100"),
                longitude=Decimal("-0.1"),
                timestamp=now + timezone.timedelta(seconds=index),
            )
            expected_ids.append(location.id)

        expected_device_names = {f"user{index}/phone-{index}" for index in range(10)}

        response = staff_client.get("/api/locations/last-known/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.json()["results"]
        created_results = [row for row in results if row["device_name"] in expected_device_names]
        assert_that(len(created_results), equal_to(10))
        assert_that(sorted(row["id"] for row in created_results), equal_to(sorted(expected_ids)))

    def test_returns_latest_per_visible_device(
        self,
        alice_client: APIClient,
        alice_device: Device,
        bob_device: Device,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        older = timezone.now() - timezone.timedelta(hours=1)
        newer = timezone.now()
        Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.0"),
            longitude=Decimal("-0.1"),
            timestamp=older,
        )
        alice_latest = Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.1"),
            longitude=Decimal("-0.2"),
            timestamp=newer,
        )
        bob_latest = Location.objects.create(
            device=bob_device,
            latitude=Decimal("52.0"),
            longitude=Decimal("-0.3"),
            timestamp=newer,
        )

        response = alice_client.get("/api/locations/last-known/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.json()["results"]
        assert_that(len(results), equal_to(2))
        by_name = {row["device_name"]: row["id"] for row in results}
        assert_that(by_name["alice/alice-phone"], equal_to(alice_latest.id))
        assert_that(by_name["bob/bob-phone"], equal_to(bob_latest.id))

    def test_returns_stale_latest_outside_recent_activity_window(
        self,
        alice_client: APIClient,
        alice_device: Device,
        bob_device: Device,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        """Last-known returns true DB latest even when a device has no recent pings."""
        recent = timezone.now()
        stale = timezone.now() - timezone.timedelta(days=30)
        Location.objects.create(
            device=alice_device,
            latitude=Decimal("51.0"),
            longitude=Decimal("-0.1"),
            timestamp=recent,
        )
        bob_stale = Location.objects.create(
            device=bob_device,
            latitude=Decimal("52.0"),
            longitude=Decimal("-0.3"),
            timestamp=stale,
        )

        response = alice_client.get("/api/locations/last-known/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        by_name = {row["device_name"]: row["id"] for row in response.json()["results"]}
        assert_that(by_name["bob/bob-phone"], equal_to(bob_stale.id))

    def test_excludes_unshared_devices(
        self,
        alice_client: APIClient,
        bob_device: Device,
        bob_location: Location,
        friendship: FriendRequest,
    ) -> None:
        response = alice_client.get("/api/locations/last-known/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["results"], equal_to([]))

    def test_device_filter_accepts_owner_device_id(
        self,
        alice_client: APIClient,
        bob_location: Location,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        response = alice_client.get("/api/locations/last-known/?device=bob/bob-phone")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.json()["results"]
        assert_that(len(results), equal_to(1))
        assert_that(results[0]["device_name"], equal_to("bob/bob-phone"))

    def test_device_filter_404_for_inaccessible_device(
        self,
        alice_client: APIClient,
        bob_device: Device,
        bob_location: Location,
    ) -> None:
        response = alice_client.get("/api/locations/last-known/?device=bob-phone")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


class TestDeviceNameInApi:
    def test_device_list_includes_canonical_device_name(
        self,
        alice_client: APIClient,
        alice_device: Device,
    ) -> None:
        response = alice_client.get("/api/devices/")
        device = response.data["results"][0]
        assert_that(device["device_name"], equal_to("alice/alice-phone"))
