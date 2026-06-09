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


@pytest.fixture
def friendship(alice: User, bob: User) -> FriendRequest:
    return FriendRequest.objects.create(from_user=bob, to_user=alice, status=FriendRequest.ACCEPTED)


@pytest.fixture
def bob_shares_with_alice(bob_device: Device, alice: User, friendship: FriendRequest) -> DeviceShare:
    return DeviceShare.objects.create(device=bob_device, shared_with=alice)


class TestDeviceLocationWsGroups:
    def test_owner_and_staff_receive_updates(self, bob: User, bob_device: Device) -> None:
        groups = device_location_ws_groups(bob_device)
        assert_that(groups, has_item(user_ws_group(bob.id)))
        assert_that(groups, has_item(STAFF_WS_GROUP))

    def test_shared_friend_receives_updates(
        self, alice: User, bob: User, bob_device: Device, bob_shares_with_alice: DeviceShare
    ) -> None:
        groups = device_location_ws_groups(bob_device)
        assert_that(groups, has_item(user_ws_group(alice.id)))
        assert_that(groups, has_item(user_ws_group(bob.id)))

    def test_unshared_friend_does_not_receive_updates(
        self, alice: User, bob: User, bob_device: Device, friendship: FriendRequest
    ) -> None:
        groups = device_location_ws_groups(bob_device)
        assert_that(groups, not_(has_item(user_ws_group(alice.id))))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestBroadcastDeviceEventAsync:
    async def test_broadcast_from_async_context_includes_shared_friend(
        self,
        alice: User,
        bob: User,
        bob_device: Device,
        bob_shares_with_alice: DeviceShare,
    ) -> None:
        """MQTT/HTTP async callers must resolve DeviceShare without sync ORM errors."""
        from unittest.mock import AsyncMock

        from app.ws_broadcast import broadcast_device_event, user_ws_group

        mock_layer = AsyncMock()
        await broadcast_device_event(
            mock_layer,
            bob_device,
            message_type="location_update",
            data={"id": 1},
        )

        sent_groups = [call.args[0] for call in mock_layer.group_send.call_args_list]
        assert_that(sent_groups, has_item(user_ws_group(alice.id)))
        assert_that(sent_groups, has_item(user_ws_group(bob.id)))
