"""
Tests for WebSocket consumer functionality.
"""

from typing import Any, cast

import pytest
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from hamcrest import assert_that, equal_to, has_key, is_not, none

from config.asgi import application


@pytest.mark.django_db
@pytest.mark.asyncio
class TestLocationConsumer:
    """Test cases for LocationConsumer WebSocket functionality."""

    async def test_websocket_connect(self):
        """Test that clients can connect to the WebSocket and receive welcome."""
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        connected, _ = await communicator.connect()
        assert_that(connected, equal_to(True))

        # Should receive welcome message with server startup timestamp
        welcome = await communicator.receive_json_from()
        assert_that(welcome["type"], equal_to("welcome"))
        assert_that(welcome, has_key("server_startup"))

        await communicator.disconnect()

    async def test_location_broadcast(self):
        """Test that location updates reach authenticated subscribers."""
        from channels.db import database_sync_to_async
        from django.contrib.auth.models import User

        from app.ws_broadcast import user_ws_group

        user = await database_sync_to_async(User.objects.create_user)(username="alice_ws", password="pass")
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        cast(Any, communicator.scope)["user"] = user
        await communicator.connect()

        # Consume welcome message first
        welcome = await communicator.receive_json_from()
        assert_that(welcome["type"], equal_to("welcome"))

        channel_layer = get_channel_layer()
        assert_that(channel_layer, is_not(none()))
        test_location = {
            "latitude": "37.774900",
            "longitude": "-122.419400",
            "device_name": "Test Device",
            "timestamp_unix": 1705329600,
        }

        await cast(Any, channel_layer).group_send(
            user_ws_group(user.id), {"type": "location_update", "data": test_location}
        )

        response = await communicator.receive_json_from()

        assert_that(response["type"], equal_to("location"))
        assert_that(response["data"], equal_to(test_location))

        await communicator.disconnect()

    async def test_websocket_disconnect(self):
        """Test that clients can disconnect cleanly."""
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        await communicator.connect()

        # Consume welcome message
        _ = await communicator.receive_json_from()

        await communicator.disconnect()
        # If we get here without exceptions, disconnect worked

    async def test_device_status_broadcast(self):
        """Test that device status changes reach authenticated subscribers."""
        from channels.db import database_sync_to_async
        from django.contrib.auth.models import User

        from app.ws_broadcast import user_ws_group

        user = await database_sync_to_async(User.objects.create_user)(username="status_ws", password="pass")
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        cast(Any, communicator.scope)["user"] = user
        await communicator.connect()

        welcome = await communicator.receive_json_from()
        assert_that(welcome["type"], equal_to("welcome"))

        channel_layer = get_channel_layer()
        assert_that(channel_layer, is_not(none()))
        test_status = {
            "device_id": "user/phone",
            "is_online": False,
            "event": "device_offline",
            "disconnected_at": "2024-01-01T12:00:00+00:00",
        }

        await cast(Any, channel_layer).group_send(
            user_ws_group(user.id), {"type": "device_status", "data": test_status}
        )

        response = await communicator.receive_json_from()

        assert_that(response["type"], equal_to("device_status"))
        assert_that(response["data"], equal_to(test_status))

        await communicator.disconnect()

    async def test_waypoint_event_broadcast(self):
        """Test that waypoint sync events reach authenticated staff subscribers."""
        from channels.db import database_sync_to_async
        from django.contrib.auth.models import User

        from app.ws_broadcast import STAFF_WS_GROUP

        user = await database_sync_to_async(User.objects.create_user)(
            username="staff_ws", password="pass", is_staff=True
        )
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        cast(Any, communicator.scope)["user"] = user
        await communicator.connect()

        welcome = await communicator.receive_json_from()
        assert_that(welcome["type"], equal_to("welcome"))

        channel_layer = get_channel_layer()
        assert_that(channel_layer, is_not(none()))
        test_data = {"device_display": "alice/phone", "new_count": 1}

        await cast(Any, channel_layer).group_send(
            STAFF_WS_GROUP,
            {
                "type": "waypoint_event",
                "data": test_data,
            },
        )

        response = await communicator.receive_json_from()
        assert_that(response["type"], equal_to("waypoint_event"))
        assert_that(response["data"], equal_to(test_data))

        await communicator.disconnect()
