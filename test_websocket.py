"""
Tests for WebSocket consumer functionality.
"""
import pytest
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from hamcrest import assert_that, equal_to, has_key, is_not, none

from mytracks.asgi import application


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
        assert_that(welcome['type'], equal_to('welcome'))
        assert_that(welcome, has_key('server_startup'))

        await communicator.disconnect()

    async def test_location_broadcast(self):
        """Test that location updates are broadcast to connected clients."""
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        await communicator.connect()

        # Consume welcome message first
        welcome = await communicator.receive_json_from()
        assert_that(welcome['type'], equal_to('welcome'))

        # Simulate a location update being broadcast
        channel_layer = get_channel_layer()
        assert_that(channel_layer, is_not(none()))  # Type guard for Pylance
        test_location = {
            'latitude': '37.774900',
            'longitude': '-122.419400',
            'device_name': 'Test Device',
            'timestamp_unix': 1705329600
        }

        await channel_layer.group_send(
            "locations",
            {
                "type": "location_update",
                "data": test_location
            }
        )

        # Receive the message from WebSocket
        response = await communicator.receive_json_from()

        assert_that(response['type'], equal_to('location'))
        assert_that(response['data'], equal_to(test_location))

        await communicator.disconnect()

    async def test_websocket_disconnect(self):
        """Test that clients can disconnect cleanly."""
        communicator = WebsocketCommunicator(application, "/ws/locations/")
        await communicator.connect()

        # Consume welcome message
        _ = await communicator.receive_json_from()

        await communicator.disconnect()
        # If we get here without exceptions, disconnect worked
