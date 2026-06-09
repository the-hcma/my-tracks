"""Tests for per-user WebSocket broadcast group selection."""

from typing import Any

import pytest
from django.contrib.auth.models import User
from hamcrest import assert_that, has_item, not_

from app.models import Device, DeviceShare, FriendRequest
from app.ws_broadcast import STAFF_WS_GROUP, device_location_ws_groups, user_ws_group


@pytest.fixture
def alice(db: Any) -> User:
    return User.objects.create_user(username="alice", password="pass")


@pytest.fixture
def bob(db: Any) -> User:
    return User.objects.create_user(username="bob", password="pass")


@pytest.fixture
def bob_device(bob: User) -> Device:
    return Device.objects.create(device_id="bob-phone", name="Bob Phone", owner=bob, mqtt_user="bob_mqtt")


class TestDeviceLocationWsGroups:
    def test_owner_and_staff_receive_updates(self, bob: User, bob_device: Device) -> None:
        groups = device_location_ws_groups(bob_device)
        assert_that(groups, has_item(user_ws_group(bob.id)))
        assert_that(groups, has_item(STAFF_WS_GROUP))

    def test_shared_friend_receives_updates(self, alice: User, bob: User, bob_device: Device) -> None:
        FriendRequest.objects.create(from_user=bob, to_user=alice, status=FriendRequest.ACCEPTED)
        DeviceShare.objects.create(device=bob_device, shared_with=alice)
        groups = device_location_ws_groups(bob_device)
        assert_that(groups, has_item(user_ws_group(alice.id)))
        assert_that(groups, has_item(user_ws_group(bob.id)))

    def test_unshared_friend_does_not_receive_updates(self, alice: User, bob: User, bob_device: Device) -> None:
        FriendRequest.objects.create(from_user=bob, to_user=alice, status=FriendRequest.ACCEPTED)
        groups = device_location_ws_groups(bob_device)
        assert_that(groups, not_(has_item(user_ws_group(alice.id))))
