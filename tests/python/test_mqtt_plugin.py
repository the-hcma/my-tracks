"""Tests for the MQTT OwnTracks plugin."""
# pyright: reportCallIssue=none
# pyright: reportOptionalSubscript=none
# pyright: reportArgumentType=none

import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.test import TestCase
from hamcrest import (assert_that, contains_string, equal_to, has_entries,
                      has_item, has_length, is_, is_not, none, not_none)

from app.models import Device, Location, OwnTracksMessage, Transition, Waypoint
from app.mqtt.plugin import (OwnTracksPlugin, _ClientTLSInfo,
                             _extract_tls_info, get_channel_layer_lazy,
                             get_other_devices, save_location_to_db,
                             save_lwt_to_db, save_transition_to_db,
                             save_waypoints_to_db)

# Allow sync DB access in async tests for testing purposes
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"


class TestSaveLocationToDb(TestCase):
    """Tests for save_location_to_db function."""

    def test_save_valid_location(self) -> None:
        """Should save location and return serialized data."""
        location_data = {
            "device": "phone",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "tracker_id": "PH",
            "accuracy": 10,
            "altitude": 50,
            "velocity": 5,
            "battery": 85,
        }

        result = save_location_to_db(location_data)

        assert_that(result, is_not(none()))
        assert_that(result, is_not(none()))
        assert_that(result, has_entries({
            "device_id_display": "phone",
            "latitude": "51.5074000000",
            "longitude": "-0.1278000000",
        }))

        # Verify saved to database
        location = Location.objects.get(id=result["id"])
        assert_that(location.device.device_id, equal_to("phone"))
        assert_that(float(location.latitude), equal_to(51.5074))
        assert_that(float(location.longitude), equal_to(-0.1278))
        assert_that(location.tracker_id, equal_to("PH"))
        assert_that(location.battery_level, equal_to(85))

    def test_save_location_minimal(self) -> None:
        """Should save location with only required fields."""
        location_data = {
            "device": "device",
            "latitude": 40.7128,
            "longitude": -74.006,
            "timestamp": datetime(2024, 6, 15, 9, 30, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)

        assert_that(result, is_not(none()))
        assert_that(result, is_not(none()))
        assert_that(result["device_id_display"], equal_to("device"))

    def test_save_location_exception(self) -> None:
        """Should return None on database error."""
        location_data = {
            "device": "device",
            # Missing required latitude
            "longitude": -74.006,
            "timestamp": datetime.now(tz=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_(none()))

    def test_save_location_marks_device_online(self) -> None:
        """Should mark device as online when a location is saved."""
        # Create device that's offline
        device = Device.objects.create(
            device_id="user/offlinedev",
            name="Offline Device",
            is_online=False,
        )

        location_data = {
            "device": "user/offlinedev",
            "latitude": 40.7128,
            "longitude": -74.006,
            "timestamp": datetime(2024, 6, 15, 9, 30, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        # Device should now be online
        device.refresh_from_db()
        assert_that(device.is_online, equal_to(True))

    def test_save_location_device_already_online(self) -> None:
        """Should not error if device is already online."""
        Device.objects.create(
            device_id="user/onlinedev",
            name="Online Device",
            is_online=True,
        )

        location_data = {
            "device": "user/onlinedev",
            "latitude": 40.7128,
            "longitude": -74.006,
            "timestamp": datetime(2024, 6, 15, 9, 30, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="user/onlinedev")
        assert_that(device.is_online, equal_to(True))

    def test_save_location_with_client_ip(self) -> None:
        """Should store client_ip as ip_address when provided."""
        location_data = {
            "device": "phone",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "client_ip": "192.168.1.100",
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        location = Location.objects.get(id=result["id"])
        assert_that(location.ip_address, equal_to("192.168.1.100"))

    def test_save_location_without_client_ip(self) -> None:
        """Should leave ip_address as None when client_ip not provided."""
        location_data = {
            "device": "phone",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        location = Location.objects.get(id=result["id"])
        assert_that(location.ip_address, is_(none()))

    def test_save_location_stores_mqtt_user(self) -> None:
        """Should store mqtt_user on the Device when provided."""
        location_data = {
            "device": "myphone",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "mqtt_user": "alice",
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="myphone")
        assert_that(device.mqtt_user, equal_to("alice"))

    def test_save_location_without_mqtt_user(self) -> None:
        """Should leave mqtt_user empty when not provided."""
        location_data = {
            "device": "myphone2",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="myphone2")
        assert_that(device.mqtt_user, equal_to(""))

    def test_save_location_updates_mqtt_user_on_change(self) -> None:
        """Should update mqtt_user if it changes."""
        Device.objects.create(
            device_id="evolving",
            name="Evolving Device",
            mqtt_user="old_user",
        )

        location_data = {
            "device": "evolving",
            "latitude": 40.0,
            "longitude": -74.0,
            "timestamp": datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
            "mqtt_user": "new_user",
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="evolving")
        assert_that(device.mqtt_user, equal_to("new_user"))


class TestSaveLwtToDb(TestCase):
    """Tests for save_lwt_to_db function."""

    def test_save_lwt_marks_device_offline(self) -> None:
        """Should mark device as offline on LWT."""
        device = Device.objects.create(
            device_id="user/phone",
            name="Phone",
            is_online=True,
        )

        lwt_data = {
            "device": "user/phone",
            "event": "offline",
            "connected_at": datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        result = save_lwt_to_db(lwt_data)

        assert_that(result, is_not(none()))
        assert_that(result, is_not(none()))
        assert_that(result, has_entries({
            "device_id": "user/phone",
            "is_online": False,
            "event": "device_offline",
        }))

        # Verify device is offline
        device.refresh_from_db()
        assert_that(device.is_online, equal_to(False))

    def test_save_lwt_creates_message_record(self) -> None:
        """Should store the LWT as an OwnTracksMessage."""
        Device.objects.create(
            device_id="user/tablet",
            name="Tablet",
            is_online=True,
        )

        lwt_data = {
            "device": "user/tablet",
            "event": "offline",
            "connected_at": datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        save_lwt_to_db(lwt_data)

        # Verify OwnTracksMessage was created
        msg = OwnTracksMessage.objects.get(
            device__device_id="user/tablet",
            message_type="lwt",
        )
        assert_that(msg.payload["event"], equal_to("offline"))
        assert_that(msg.payload["connected_at"], equal_to("2024-01-01T10:00:00+00:00"))
        assert_that(msg.payload["disconnected_at"], equal_to("2024-01-01T12:00:00+00:00"))

    def test_save_lwt_without_connected_at(self) -> None:
        """Should handle LWT without connected_at timestamp."""
        Device.objects.create(
            device_id="user/dev2",
            name="Dev 2",
            is_online=True,
        )

        lwt_data = {
            "device": "user/dev2",
            "event": "offline",
            "connected_at": None,
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        result = save_lwt_to_db(lwt_data)

        assert_that(result, is_not(none()))
        msg = OwnTracksMessage.objects.get(device__device_id="user/dev2")
        assert_that(msg.payload["connected_at"], is_(none()))

    def test_save_lwt_unknown_device(self) -> None:
        """Should return None for unknown device."""
        lwt_data = {
            "device": "unknown/device",
            "event": "offline",
            "connected_at": None,
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        result = save_lwt_to_db(lwt_data)
        assert_that(result, is_(none()))

    def test_save_lwt_already_offline_device(self) -> None:
        """Should still process LWT even if device already offline."""
        Device.objects.create(
            device_id="user/alreadyoff",
            name="Already Off",
            is_online=False,
        )

        lwt_data = {
            "device": "user/alreadyoff",
            "event": "offline",
            "connected_at": None,
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }

        result = save_lwt_to_db(lwt_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="user/alreadyoff")
        assert_that(device.is_online, equal_to(False))

    def test_save_lwt_device_display_includes_owner(self) -> None:
        """device_display should be 'owner/device_id' when device has an owner."""
        from django.contrib.auth.models import User
        owner = User.objects.create_user(username="bob", password="pass")
        Device.objects.create(device_id="watch", name="Watch", is_online=True, owner=owner)

        result = save_lwt_to_db({
            "device": "watch",
            "event": "offline",
            "connected_at": None,
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        })

        assert_that(result, is_not(none()))
        assert result is not None
        assert_that(result["device_display"], equal_to("bob/watch"))

    def test_save_lwt_device_display_no_owner(self) -> None:
        """device_display should be bare device_id when device has no owner."""
        Device.objects.create(device_id="orphan", name="Orphan", is_online=True)

        result = save_lwt_to_db({
            "device": "orphan",
            "event": "offline",
            "connected_at": None,
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        })

        assert_that(result, is_not(none()))
        assert result is not None
        assert_that(result["device_display"], equal_to("orphan"))


@pytest.fixture
def mock_broker_context() -> MagicMock:
    """Create a mock BrokerContext for testing."""
    context = MagicMock()
    context.config = {}
    context.get_session.return_value = None
    return context


class TestOwnTracksPluginInit:
    """Tests for OwnTracksPlugin initialization."""

    def test_plugin_initializes(self, mock_broker_context: MagicMock) -> None:
        """Should initialize plugin with message handler."""
        plugin = OwnTracksPlugin(mock_broker_context)

        assert_that(plugin._handler, is_not(none()))
        assert_that(plugin._handler._location_callbacks, has_length(1))
        assert_that(plugin._handler._lwt_callbacks, has_length(1))
        assert_that(plugin._handler._transition_callbacks, has_length(1))
        assert_that(plugin._handler._waypoint_callbacks, has_length(1))


@pytest.mark.django_db
class TestOwnTracksPluginMessageHandling:
    """Tests for OwnTracksPlugin message handling."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.fixture
    def mock_message(self) -> MagicMock:
        """Create a mock ApplicationMessage."""
        message = MagicMock()
        message.topic = "owntracks/testuser/phone"
        message.data = json.dumps({
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
            "tid": "TS",
            "acc": 5,
        }).encode()
        return message

    @pytest.mark.asyncio
    async def test_ignores_non_owntracks_topic(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should ignore messages on non-owntracks topics."""
        message = MagicMock()
        message.topic = "home/sensors/temp"
        message.data = b'{"value": 22.5}'

        initial_count = Location.objects.count()

        await plugin.on_broker_message_received(
            client_id="test-client",
            message=message,
        )

        assert_that(Location.objects.count(), equal_to(initial_count))

    @pytest.mark.asyncio
    async def test_processes_location_message(
        self,
        plugin: OwnTracksPlugin,
        mock_message: MagicMock,
    ) -> None:
        """Should process location message and save to database."""
        initial_count = Location.objects.count()

        # Mock the WebSocket broadcast to avoid channel layer issues
        with patch.object(plugin, "_broadcast_location", new_callable=AsyncMock):
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=mock_message,
            )

        # Should have saved one location
        assert_that(Location.objects.count(), equal_to(initial_count + 1))

        # Verify the saved location
        location = Location.objects.latest("id")
        assert_that(location.device.device_id, equal_to("phone"))
        assert_that(float(location.latitude), equal_to(51.5))
        assert_that(float(location.longitude), equal_to(-0.1))
        assert_that(location.tracker_id, equal_to("TS"))

    @pytest.mark.asyncio
    async def test_broadcasts_location_via_websocket(
        self,
        plugin: OwnTracksPlugin,
        mock_message: MagicMock,
    ) -> None:
        """Should broadcast location to WebSocket clients."""
        broadcast_mock = AsyncMock()

        with patch.object(plugin, "_broadcast_location", broadcast_mock):
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=mock_message,
            )

        # Verify broadcast was called
        broadcast_mock.assert_called_once()
        call_args = broadcast_mock.call_args[0][0]
        assert_that(call_args, has_entries(
            device_id_display="phone",
        ))

    @pytest.mark.asyncio
    async def test_handles_lwt_message(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle LWT messages and mark device offline."""
        # Create an online device first
        from asgiref.sync import sync_to_async
        device = await sync_to_async(Device.objects.create)(
            device_id="device",
            name="Test Device",
            is_online=True,
        )

        message = MagicMock()
        message.topic = "owntracks/user/device"
        message.data = json.dumps({
            "_type": "lwt",
            "tst": 1704067200,
        }).encode()

        with patch.object(plugin, "_broadcast_device_status", new_callable=AsyncMock) as broadcast_mock:
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=message,
            )

        # Device should be marked offline
        await sync_to_async(device.refresh_from_db)()
        assert_that(device.is_online, equal_to(False))

        # Should have broadcast device status
        broadcast_mock.assert_called_once()
        call_args = broadcast_mock.call_args[0][0]
        assert_that(call_args, has_entries(
            device_id="device",
            is_online=False,
            event="device_offline",
        ))

        # OwnTracksMessage should be created
        msg_count = await sync_to_async(
            OwnTracksMessage.objects.filter(
                device=device, message_type="lwt"
            ).count
        )()
        assert_that(msg_count, equal_to(1))

    @pytest.mark.asyncio
    async def test_handles_transition_message(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle transition messages."""
        message = MagicMock()
        message.topic = "owntracks/user/device"
        message.data = json.dumps({
            "_type": "transition",
            "event": "enter",
            "desc": "Home",
            "tst": 1704067200,
            "lat": 51.5,
            "lon": -0.1,
        }).encode()

        # Should not raise - transition handling is logged but doesn't save to DB yet
        await plugin.on_broker_message_received(
            client_id="test-client",
            message=message,
        )

    @pytest.mark.asyncio
    async def test_handles_bytearray_payload(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle bytearray payload (in addition to bytes)."""
        message = MagicMock()
        message.topic = "owntracks/user/device"
        # Use bytearray instead of bytes
        message.data = bytearray(json.dumps({
            "_type": "location",
            "lat": 40.0,
            "lon": -74.0,
            "tst": 1704067200,
        }).encode())

        with patch.object(plugin, "_broadcast_location", new_callable=AsyncMock):
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=message,
            )

        # Should have saved the location
        location = Location.objects.latest("id")
        assert_that(float(location.latitude), equal_to(40.0))

    @pytest.mark.asyncio
    async def test_handles_invalid_json_gracefully(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle invalid JSON without crashing."""
        message = MagicMock()
        message.topic = "owntracks/user/device"
        message.data = b"not valid json"

        initial_count = Location.objects.count()

        # Should not raise
        await plugin.on_broker_message_received(
            client_id="test-client",
            message=message,
        )

        # No location should be saved
        assert_that(Location.objects.count(), equal_to(initial_count))

    @pytest.mark.asyncio
    async def test_stores_client_ip_from_session(
        self,
        plugin: OwnTracksPlugin,
        mock_message: MagicMock,
        mock_broker_context: MagicMock,
    ) -> None:
        """Should look up client IP from broker session and store it."""
        mock_session = MagicMock()
        mock_session.remote_address = "10.0.0.42"
        mock_broker_context.get_session.return_value = mock_session

        with patch.object(plugin, "_broadcast_location", new_callable=AsyncMock):
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=mock_message,
            )

        mock_broker_context.get_session.assert_called_once_with("test-client")
        location = Location.objects.latest("id")
        assert_that(location.ip_address, equal_to("10.0.0.42"))

    @pytest.mark.asyncio
    async def test_handles_missing_session_gracefully(
        self,
        plugin: OwnTracksPlugin,
        mock_message: MagicMock,
        mock_broker_context: MagicMock,
    ) -> None:
        """Should handle missing session (ip_address stays None)."""
        mock_broker_context.get_session.return_value = None

        with patch.object(plugin, "_broadcast_location", new_callable=AsyncMock):
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=mock_message,
            )

        location = Location.objects.latest("id")
        assert_that(location.ip_address, is_(none()))


@pytest.mark.django_db
class TestBroadcastLocation:
    """Tests for WebSocket broadcast functionality."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_broadcast_with_channel_layer(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should broadcast to channel layer when available."""
        mock_layer = AsyncMock()
        mock_layer.group_send = AsyncMock()

        location_data = {
            "id": 123,
            "device_id": "device",
            "latitude": 51.5,
            "longitude": -0.1,
        }

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
            await plugin._broadcast_location(location_data)

        mock_layer.group_send.assert_called_once()
        call_args = mock_layer.group_send.call_args
        assert_that(call_args[0][0], equal_to("locations"))
        assert_that(call_args[0][1], has_entries(
            type="location_update",
            data=location_data,
        ))

    @pytest.mark.asyncio
    async def test_broadcast_without_channel_layer(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle missing channel layer gracefully."""
        location_data = {"id": 123}

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=None):
            # Should not raise
            await plugin._broadcast_location(location_data)

    @pytest.mark.asyncio
    async def test_broadcast_handles_exception(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle broadcast exceptions gracefully."""
        mock_layer = AsyncMock()
        mock_layer.group_send = AsyncMock(side_effect=Exception("Test error"))

        location_data = {"id": 123}

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
            # Should not raise
            await plugin._broadcast_location(location_data)


@pytest.mark.django_db
class TestBroadcastDeviceStatus:
    """Tests for device status WebSocket broadcast functionality."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_broadcast_device_offline(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should broadcast device offline status to channel layer."""
        mock_layer = AsyncMock()
        mock_layer.group_send = AsyncMock()

        status_data = {
            "device_id": "user/phone",
            "is_online": False,
            "event": "device_offline",
            "disconnected_at": "2024-01-01T12:00:00+00:00",
        }

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
            await plugin._broadcast_device_status(status_data)

        mock_layer.group_send.assert_called_once()
        call_args = mock_layer.group_send.call_args
        assert_that(call_args[0][0], equal_to("locations"))
        assert_that(call_args[0][1], has_entries(
            type="device_status",
            data=status_data,
        ))

    @pytest.mark.asyncio
    async def test_broadcast_device_status_no_channel_layer(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle missing channel layer gracefully."""
        status_data = {"device_id": "user/phone", "is_online": False}

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=None):
            # Should not raise
            await plugin._broadcast_device_status(status_data)

    @pytest.mark.asyncio
    async def test_broadcast_device_status_exception(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle broadcast exceptions gracefully."""
        mock_layer = AsyncMock()
        mock_layer.group_send = AsyncMock(side_effect=Exception("Connection broken"))

        status_data = {"device_id": "user/phone", "is_online": False}

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
            # Should not raise
            await plugin._broadcast_device_status(status_data)


class TestMqttProtocolVersionCheck:
    """Tests for MQTT v3.1 detection and user-friendly error message."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create an OwnTracksPlugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    def _make_connect_packet(
        self, proto_name: str = "MQTT", proto_level: int = 4
    ) -> MagicMock:
        """Create a mock ConnectPacket with given protocol fields."""
        from amqtt.mqtt.connect import ConnectPacket

        packet = MagicMock(spec=ConnectPacket)
        packet.variable_header = MagicMock()
        packet.variable_header.proto_name = proto_name
        packet.variable_header.proto_level = proto_level
        return packet

    @pytest.mark.asyncio
    async def test_v31_mqisdp_logs_warning(self, plugin: OwnTracksPlugin) -> None:
        """MQTT v3.1 (MQIsdp/level 3) should log a warning with instructions."""
        packet = self._make_connect_packet(proto_name="MQIsdp", proto_level=3)

        with patch("app.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_called_once()
        msg = mock_logger.warning.call_args[0][0]
        assert_that(msg, contains_string("MQTT v3.1 connection detected"))
        assert_that(msg, contains_string("mqttProtocolLevel"))
        assert_that(msg, contains_string("protocol level 4"))

    @pytest.mark.asyncio
    async def test_v31_level3_with_mqtt_name_logs_warning(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """Proto level < 4 should trigger warning even with 'MQTT' name."""
        packet = self._make_connect_packet(proto_name="MQTT", proto_level=3)

        with patch("app.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_v311_does_not_log_warning(self, plugin: OwnTracksPlugin) -> None:
        """MQTT v3.1.1 (level 4) should not trigger any warning."""
        packet = self._make_connect_packet(proto_name="MQTT", proto_level=4)

        with patch("app.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_connect_packet_ignored(self, plugin: OwnTracksPlugin) -> None:
        """Non-CONNECT packets should be silently ignored."""
        packet = MagicMock()  # Not a ConnectPacket

        with patch("app.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_packet_no_variable_header(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """ConnectPacket with no variable header should not crash."""
        from amqtt.mqtt.connect import ConnectPacket

        packet = MagicMock(spec=ConnectPacket)
        packet.variable_header = None

        with patch("app.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_not_called()


class TestGetChannelLayerLazy:
    """Tests for get_channel_layer_lazy function."""

    def test_returns_channel_layer_when_available(self) -> None:
        """Should return the channel layer when get_channel_layer succeeds."""
        mock_layer = MagicMock()
        with patch("app.mqtt.plugin.get_channel_layer", return_value=mock_layer):
            result = get_channel_layer_lazy()
        assert_that(result, equal_to(mock_layer))

    def test_returns_none_on_exception(self) -> None:
        """Should return None when get_channel_layer raises an exception."""
        with patch(
            "app.mqtt.plugin.get_channel_layer",
            side_effect=Exception("No channel layer configured"),
        ):
            result = get_channel_layer_lazy()
        assert_that(result, is_(none()))


class TestSaveLwtToDbExceptionPath(TestCase):
    """Tests for save_lwt_to_db generic exception handling."""

    def test_generic_exception_returns_none(self) -> None:
        """Should return None when an unexpected exception occurs in the outer try."""
        Device.objects.create(
            device_id="user/excdevice",
            name="Exception Device",
            is_online=True,
        )
        lwt_data: dict[str, Any] = {
            "device": "user/excdevice",
            "event": "offline",
            "connected_at": None,
        }
        result = save_lwt_to_db(lwt_data)
        assert_that(result, is_(none()))


class TestHandleLocationEarlyReturn:
    """Tests for _handle_location when save_location_to_db returns None."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_does_not_broadcast_when_save_fails(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should skip broadcast when save_location_to_db returns None."""
        broadcast_mock = AsyncMock()
        location_data = {
            "device": "test",
            "latitude": 51.5,
            "longitude": -0.1,
        }
        with (
            patch("app.mqtt.plugin.save_location_to_db", return_value=None),
            patch.object(plugin, "_broadcast_location", broadcast_mock),
        ):
            await plugin._handle_location(location_data)

        broadcast_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcasts_when_save_succeeds(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should call _broadcast_location with serialized data on success."""
        serialized = {"id": 42, "device_id_display": "mydev", "latitude": "51.5"}
        broadcast_mock = AsyncMock()
        with (
            patch("app.mqtt.plugin.save_location_to_db", return_value=serialized),
            patch.object(plugin, "_broadcast_location", broadcast_mock),
        ):
            await plugin._handle_location({"device": "mydev", "latitude": 51.5, "longitude": -0.1})

        broadcast_mock.assert_called_once_with(serialized, transport="mqtt")


class TestHandleLwtEarlyReturn:
    """Tests for _handle_lwt when save_lwt_to_db returns None."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_does_not_broadcast_when_save_fails(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should skip broadcast when save_lwt_to_db returns None."""
        broadcast_mock = AsyncMock()
        lwt_data = {"device": "test", "event": "offline"}
        with (
            patch("app.mqtt.plugin.save_lwt_to_db", return_value=None),
            patch.object(plugin, "_broadcast_device_status", broadcast_mock),
        ):
            await plugin._handle_lwt(lwt_data)

        broadcast_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcasts_when_save_succeeds(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should call _broadcast_device_status with status data on success."""
        status_data = {
            "device_id": "user/phone",
            "is_online": False,
            "event": "device_offline",
            "disconnected_at": "2024-01-01T12:00:00+00:00",
        }
        broadcast_mock = AsyncMock()
        with (
            patch("app.mqtt.plugin.save_lwt_to_db", return_value=status_data),
            patch.object(plugin, "_broadcast_device_status", broadcast_mock),
        ):
            await plugin._handle_lwt({"device": "user/phone", "event": "offline"})

        broadcast_mock.assert_called_once_with(status_data, transport="mqtt")


@pytest.mark.django_db
class TestHandleTransition:
    """Tests for _handle_transition method."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_logs_transition_without_error(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle transition for unknown device without raising."""
        transition_data = {
            "device": "unknown-device",
            "event": "enter",
            "description": "Home",
        }
        # Device not found → save_transition_to_db returns None, no exception raised
        await plugin._handle_transition(transition_data)

    @pytest.mark.asyncio
    async def test_logs_transition_with_missing_keys(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle transition data with missing optional keys without raising."""
        transition_data: dict[str, Any] = {
            "device": "unknown-device-2",
        }
        await plugin._handle_transition(transition_data)


class TestSetupCallbacks:
    """Tests for _setup_callbacks method."""

    def test_registers_all_callback_types(self, mock_broker_context: MagicMock) -> None:
        """Should register location, lwt, and transition callbacks."""
        plugin = OwnTracksPlugin(mock_broker_context)
        assert_that(plugin._handler._location_callbacks, has_length(1))
        assert_that(plugin._handler._lwt_callbacks, has_length(1))
        assert_that(plugin._handler._transition_callbacks, has_length(1))

    def test_location_callback_is_handle_location(self, mock_broker_context: MagicMock) -> None:
        """Registered location callback should be _handle_location."""
        plugin = OwnTracksPlugin(mock_broker_context)
        assert_that(plugin._handler._location_callbacks[0], equal_to(plugin._handle_location))

    def test_lwt_callback_is_handle_lwt(self, mock_broker_context: MagicMock) -> None:
        """Registered LWT callback should be _handle_lwt."""
        plugin = OwnTracksPlugin(mock_broker_context)
        assert_that(plugin._handler._lwt_callbacks[0], equal_to(plugin._handle_lwt))


class TestSaveLocationToDbEdgeCases(TestCase):
    """Additional edge-case tests for save_location_to_db."""

    def test_save_location_with_all_optional_fields(self) -> None:
        """Should save location with connection_type, velocity, altitude, ip."""
        location_data = {
            "device": "full_device",
            "latitude": 48.8566,
            "longitude": 2.3522,
            "timestamp": datetime(2024, 3, 15, 14, 30, 0, tzinfo=UTC),
            "tracker_id": "FD",
            "accuracy": 15,
            "altitude": 120,
            "velocity": 30,
            "battery": 72,
            "connection": "w",
            "client_ip": "10.0.0.5",
            "mqtt_user": "alice",
        }

        result = save_location_to_db(location_data)

        assert_that(result, is_not(none()))
        location = Location.objects.get(id=result["id"])
        assert_that(location.connection_type, equal_to("w"))
        assert_that(location.velocity, equal_to(30))
        assert_that(location.altitude, equal_to(120))
        assert_that(location.ip_address, equal_to("10.0.0.5"))

    def test_save_location_creates_device_with_default_name(self) -> None:
        """Should create a new device whose name defaults to its device_id."""
        location_data = {
            "device": "newdevice99",
            "latitude": 35.6762,
            "longitude": 139.6503,
            "timestamp": datetime(2024, 5, 1, 8, 0, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="newdevice99")
        assert_that(device.name, equal_to("newdevice99"))


class TestSaveLwtToDbEdgeCases(TestCase):
    """Additional edge-case tests for save_lwt_to_db."""

    def test_exception_during_owntracks_message_create(self) -> None:
        """Should return None when OwnTracksMessage.objects.create raises."""
        Device.objects.create(
            device_id="user/errdev",
            name="Error Device",
            is_online=True,
        )
        lwt_data: dict[str, Any] = {
            "device": "user/errdev",
            "event": "offline",
            "connected_at": datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            "disconnected_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        }
        with patch.object(
            OwnTracksMessage.objects, "create", side_effect=RuntimeError("DB write failed")
        ):
            result = save_lwt_to_db(lwt_data)
        assert_that(result, is_(none()))


class TestOnBrokerMessageReceivedEdgeCases:
    """Edge-case tests for on_broker_message_received."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_handles_none_data(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle message with None data without crashing."""
        message = MagicMock()
        message.topic = "owntracks/user/phone"
        message.data = None

        await plugin.on_broker_message_received(
            client_id="test-client",
            message=message,
        )

    @pytest.mark.asyncio
    async def test_handles_empty_bytes_data(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle message with empty bytes payload."""
        message = MagicMock()
        message.topic = "owntracks/user/phone"
        message.data = b""

        await plugin.on_broker_message_received(
            client_id="test-client",
            message=message,
        )


def _make_self_signed_cert(cn: str = "testuser") -> bytes:
    """Generate a self-signed DER certificate for testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(tz=UTC))
        .not_valid_after(datetime.now(tz=UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.DER)


class TestExtractTlsInfo:
    """Tests for _extract_tls_info helper."""

    def test_extracts_cn_and_fingerprint(self) -> None:
        """Should return CN and truncated SHA-256 fingerprint from peer cert."""
        der_cert = _make_self_signed_cert("alice")
        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_ssl.getpeercert.return_value = der_cert

        result = _extract_tls_info(mock_ssl)

        assert_that(result, is_(not_none()))
        assert_that(result, is_(not_none()))
        assert_that(cast(Any, result).cn, equal_to("alice"))
        # Fingerprint is first 4 bytes of SHA-256 in hex, colon-separated
        assert_that(len(cast(Any, result).fingerprint.split(":")), equal_to(4))

    def test_returns_none_when_no_peer_cert(self) -> None:
        """Should return None when SSL has no peer certificate."""
        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_ssl.getpeercert.return_value = None

        result = _extract_tls_info(mock_ssl)

        assert_that(result, is_(none()))

    def test_cert_without_cn(self) -> None:
        """Should use 'unknown' when certificate has no CN attribute."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TestOrg")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(tz=UTC))
            .not_valid_after(datetime.now(tz=UTC) + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        der_cert = cert.public_bytes(serialization.Encoding.DER)

        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_ssl.getpeercert.return_value = der_cert

        result = _extract_tls_info(mock_ssl)

        assert_that(result, is_(not_none()))
        assert_that(result, is_(not_none()))
        assert_that(cast(Any, result).cn, equal_to("unknown"))


class TestClientTLSInfoStr:
    """Tests for _ClientTLSInfo.__str__."""

    def test_str_representation(self) -> None:
        """Should format as CN=name [fingerprint]."""
        info = _ClientTLSInfo(cn="bob", fingerprint="AA:BB:CC:DD")
        assert_that(str(info), equal_to("CN=bob [AA:BB:CC:DD]"))


class TestPluginTLSClientIdentification:
    """Tests for TLS client identification in OwnTracksPlugin."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    def test_transport_for_unknown_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return 'mqtt' for client not in cache."""
        assert_that(plugin._transport("never-seen"), equal_to("mqtt"))

    def test_transport_for_non_tls_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return 'mqtt' for client connected without TLS."""
        plugin._client_tls["plain-client"] = None
        assert_that(plugin._transport("plain-client"), equal_to("mqtt"))

    def test_transport_for_tls_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return 'mqtt-tls' for TLS client."""
        info = _ClientTLSInfo(cn="alice", fingerprint="AA:BB:CC:DD")
        plugin._client_tls["tls-client"] = info
        assert_that(plugin._transport("tls-client"), equal_to("mqtt-tls"))

    def test_transport_uses_session_ssl_object_when_cache_cleared(
        self,
        plugin: OwnTracksPlugin,
        mock_broker_context: MagicMock,
    ) -> None:
        """In-flight messages after disconnect still tag mqtt-tls when session retains ssl_object."""
        der_cert = _make_self_signed_cert("phoneuser")
        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_ssl.getpeercert.return_value = der_cert

        mock_session = MagicMock()
        mock_session.ssl_object = mock_ssl
        mock_broker_context.get_session.return_value = mock_session

        with patch.object(plugin, "_get_handler_writer_ssl", return_value=None):
            assert_that(plugin._transport("phone-123"), equal_to("mqtt-tls"))

    def test_identity_for_unknown_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return empty string for client not in cache."""
        assert_that(plugin._identity("never-seen"), equal_to(""))

    def test_identity_for_non_tls_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return empty string for non-TLS client."""
        plugin._client_tls["plain-client"] = None
        assert_that(plugin._identity("plain-client"), equal_to(""))

    def test_identity_for_tls_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return formatted identity string for TLS client."""
        info = _ClientTLSInfo(cn="alice", fingerprint="AA:BB:CC:DD")
        plugin._client_tls["tls-client"] = info
        assert_that(plugin._identity("tls-client"), equal_to(" (CN=alice [AA:BB:CC:DD])"))

    @pytest.mark.asyncio
    async def test_on_broker_client_connected_tls_with_cert(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should cache TLS info and log cert identity on TLS connection with client cert."""
        der_cert = _make_self_signed_cert("phoneuser")
        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_ssl.getpeercert.return_value = der_cert

        mock_session = MagicMock()
        mock_session.remote_address = "10.0.0.1"

        with patch.object(plugin, "_get_handler_writer_ssl", return_value=mock_ssl):
            await plugin.on_broker_client_connected(
                client_id="phone-123",
                client_session=mock_session,
            )

        assert_that(plugin._client_tls["phone-123"], is_(not_none()))
        assert_that(plugin._client_tls["phone-123"], is_(not_none()))
        assert_that(cast(Any, plugin._client_tls["phone-123"]).cn, equal_to("phoneuser"))

    @pytest.mark.asyncio
    async def test_on_broker_client_connected_tls_without_client_cert(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should cache None TLS info when TLS but no client cert presented."""
        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_ssl.getpeercert.return_value = None

        mock_session = MagicMock()
        mock_session.remote_address = "10.0.0.2"

        with patch.object(plugin, "_get_handler_writer_ssl", return_value=mock_ssl):
            await plugin.on_broker_client_connected(
                client_id="nocert-456",
                client_session=mock_session,
            )

        # Stored but with None value since SSL was present but no client cert
        assert_that("nocert-456" in plugin._client_tls, is_(True))
        assert_that(plugin._client_tls["nocert-456"], is_(none()))

    @pytest.mark.asyncio
    async def test_on_broker_client_connected_non_tls(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should cache None for non-TLS connections."""
        mock_session = MagicMock()
        mock_session.remote_address = "192.168.1.5"

        with patch.object(plugin, "_get_handler_writer_ssl", return_value=None):
            await plugin.on_broker_client_connected(
                client_id="plain-789",
                client_session=mock_session,
            )

        assert_that("plain-789" in plugin._client_tls, is_(True))
        assert_that(plugin._client_tls["plain-789"], is_(none()))

    @pytest.mark.asyncio
    async def test_on_broker_client_disconnected_cleans_up(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should remove TLS info from cache on disconnect."""
        info = _ClientTLSInfo(cn="bob", fingerprint="EE:FF:00:11")
        plugin._client_tls["disc-client"] = info

        mock_session = MagicMock()
        await plugin.on_broker_client_disconnected(
            client_id="disc-client",
            client_session=mock_session,
        )

        assert_that("disc-client" in plugin._client_tls, is_(False))

    @pytest.mark.asyncio
    async def test_on_broker_client_disconnected_missing_client(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should not error when disconnecting a client not in cache."""
        mock_session = MagicMock()
        await plugin.on_broker_client_disconnected(
            client_id="never-connected",
            client_session=mock_session,
        )

    def test_get_handler_writer_ssl_returns_none_when_no_broker(
        self,
        plugin: OwnTracksPlugin,
        mock_broker_context: MagicMock,
    ) -> None:
        """Should return None when broker internals are not accessible."""
        # Make accessing _broker_instance raise
        type(mock_broker_context)._broker_instance = property(
            lambda self: (_ for _ in ()).throw(AttributeError("no broker"))
        )
        result = plugin._get_handler_writer_ssl("test-client")
        assert_that(result, is_(none()))

    def test_get_handler_writer_ssl_returns_ssl_object(
        self,
        plugin: OwnTracksPlugin,
        mock_broker_context: MagicMock,
    ) -> None:
        """Should return SSL object from handler's writer."""
        mock_ssl = MagicMock(spec=ssl.SSLObject)
        mock_writer = MagicMock()
        mock_writer.get_ssl_info.return_value = mock_ssl

        mock_handler = MagicMock()
        mock_handler.writer = mock_writer

        mock_session = MagicMock()
        mock_broker = MagicMock()
        mock_broker._sessions = {"client-1": (mock_session, mock_handler)}
        mock_broker_context._broker_instance = mock_broker

        result = plugin._get_handler_writer_ssl("client-1")
        assert_that(result, equal_to(mock_ssl))

    def test_get_handler_writer_ssl_returns_none_for_non_tls(
        self,
        plugin: OwnTracksPlugin,
        mock_broker_context: MagicMock,
    ) -> None:
        """Should return None when writer has no SSL info."""
        mock_writer = MagicMock()
        mock_writer.get_ssl_info.return_value = None

        mock_handler = MagicMock()
        mock_handler.writer = mock_writer

        mock_session = MagicMock()
        mock_broker = MagicMock()
        mock_broker._sessions = {"client-2": (mock_session, mock_handler)}
        mock_broker_context._broker_instance = mock_broker

        result = plugin._get_handler_writer_ssl("client-2")
        assert_that(result, is_(none()))


@pytest.mark.django_db
class TestSaveTransitionToDb:
    """Tests for save_transition_to_db function."""

    @pytest.fixture
    def user_and_device(self, django_user_model: Any) -> tuple[Any, Device]:
        user = django_user_model.objects.create_user(username="alice-tr", password="pass")
        device = Device.objects.create(device_id="phone-tr", name="phone", owner=user)
        return user, device

    def test_saves_transition_with_matching_waypoint(self, user_and_device: tuple[Any, Device]) -> None:
        """Should create Transition with FK when rid matches a Waypoint."""
        user, device = user_and_device
        wp = Waypoint.objects.create(
            user=user, label="Home", latitude=51.5, longitude=-0.1, radius=100, rid="rid-123",
        )
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        result = save_transition_to_db({
            "device": "phone-tr",
            "event": "enter",
            "region_id": "rid-123",
            "description": "Home",
            "timestamp": ts,
            "latitude": 51.5,
            "longitude": -0.1,
            "accuracy": 10,
        })

        assert_that(result, not_none())
        assert result is not None
        assert_that(result["event"], equal_to("enter"))
        assert_that(result["waypoint_label"], equal_to("Home"))
        transition = Transition.objects.get(pk=result["id"])
        assert_that(transition.waypoint, equal_to(wp))
        assert_that(transition.device, equal_to(device))

    def test_saves_transition_without_matching_waypoint(self, user_and_device: tuple[Any, Device]) -> None:
        """Should create Transition with null waypoint FK when rid has no match."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        result = save_transition_to_db({
            "device": "phone-tr",
            "event": "leave",
            "region_id": "unknown-rid",
            "description": "Unknown place",
            "timestamp": ts,
        })

        assert_that(result, not_none())
        assert result is not None
        assert_that(result["waypoint_label"], is_(none()))
        transition = Transition.objects.get(pk=result["id"])
        assert_that(transition.waypoint, is_(none()))

    def test_returns_none_for_unknown_device(self) -> None:
        """Should return None when device does not exist."""
        result = save_transition_to_db({
            "device": "no-such-device",
            "event": "enter",
            "region_id": "rid-123",
            "description": "Home",
            "timestamp": datetime.now(tz=UTC),
        })
        assert_that(result, is_(none()))
        assert_that(Device.objects.filter(device_id="no-such-device").exists(), is_(False))

    def test_saves_transition_device_display_includes_owner(self, user_and_device: tuple[Any, Device]) -> None:
        """device_display should be 'owner/device_id' when device has an owner."""
        user, device = user_and_device
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        result = save_transition_to_db({
            "device": "phone-tr",
            "event": "enter",
            "region_id": "rid-abc",
            "description": "Work",
            "timestamp": ts,
        })

        assert_that(result, is_not(none()))
        assert result is not None
        assert_that(result["device_display"], equal_to(f"{user.username}/phone-tr"))

    def test_saves_transition_device_display_no_owner(self) -> None:
        """device_display should be bare device_id when device has no owner."""
        Device.objects.create(device_id="lonely", name="Lonely")
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        result = save_transition_to_db({
            "device": "lonely",
            "event": "leave",
            "region_id": "rid-xyz",
            "description": "Nowhere",
            "timestamp": ts,
        })

        assert_that(result, is_not(none()))
        assert result is not None
        assert_that(result["device_display"], equal_to("lonely"))


@pytest.mark.django_db
class TestSaveWaypointsToDb:
    """Tests for save_waypoints_to_db function."""

    @pytest.fixture
    def user_and_device(self, django_user_model: Any) -> tuple[Any, Device]:
        user = django_user_model.objects.create_user(username="alice-wp", password="pass")
        device = Device.objects.create(device_id="phone-wp", name="phone", owner=user)
        return user, device

    def test_creates_new_waypoints(self, user_and_device: tuple[Any, Device]) -> None:
        """Should create Waypoint records for new content."""
        user, device = user_and_device
        result = save_waypoints_to_db({
            "device": "phone-wp",
            "waypoints": [
                {"desc": "Home", "lat": 51.5, "lon": -0.1, "rad": 100},
                {"desc": "Work", "lat": 51.52, "lon": -0.08, "rad": 50},
            ],
        })

        assert_that(result, equal_to(2))
        assert_that(Waypoint.objects.count(), equal_to(2))
        wp = Waypoint.objects.get(label="Home")
        assert_that(float(wp.latitude), equal_to(51.5))
        assert_that(wp.user, equal_to(user))

    def test_skips_duplicate_waypoint(self, user_and_device: tuple[Any, Device]) -> None:
        """Should skip and not count a waypoint with identical content (same content hash)."""
        user, device = user_and_device
        result1 = save_waypoints_to_db({
            "device": "phone-wp",
            "waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1, "rad": 100}],
        })
        assert_that(result1, equal_to(1))
        assert_that(Waypoint.objects.count(), equal_to(1))

        result2 = save_waypoints_to_db({
            "device": "phone-wp",
            "waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1, "rad": 100}],
        })
        assert_that(result2, equal_to(0))
        assert_that(Waypoint.objects.count(), equal_to(1))

    def test_creates_android_waypoints_without_rid(self, user_and_device: tuple[Any, Device]) -> None:
        """Should create waypoints from Android devices that send no rid field."""
        user, device = user_and_device
        result = save_waypoints_to_db({
            "device": "phone-wp",
            "waypoints": [
                {"desc": "Android geofence", "lat": 51.5, "lon": -0.1, "rad": 150},
            ],
        })
        assert_that(result, equal_to(1))
        wp = Waypoint.objects.get(label="Android geofence")
        assert_that(wp.radius, equal_to(150))

    def test_returns_zero_for_unknown_device(self) -> None:
        """Should return 0 when device does not exist."""
        result = save_waypoints_to_db({
            "device": "no-such-device",
            "waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1, "rad": 100}],
        })
        assert_that(result, equal_to(0))
        assert_that(Waypoint.objects.count(), equal_to(0))

    def test_returns_zero_when_device_has_no_owner(self, user_and_device: tuple[Any, Device]) -> None:
        """Should return 0 when device has no owner."""
        _, device = user_and_device
        device.owner = None
        device.save()

        result = save_waypoints_to_db({
            "device": "phone-wp",
            "waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1, "rad": 100}],
        })
        assert_that(result, equal_to(0))

    def test_skips_waypoints_missing_lat_or_lon(self, user_and_device: tuple[Any, Device]) -> None:
        """Should skip waypoints with missing lat or lon."""
        result = save_waypoints_to_db({
            "device": "phone-wp",
            "waypoints": [
                {"desc": "No lat", "lon": -0.1, "rad": 100},
                {"desc": "Good", "lat": 51.5, "lon": -0.1, "rad": 100},
            ],
        })
        assert_that(result, equal_to(1))
        assert_that(Waypoint.objects.filter(label="No lat").exists(), is_(False))


@pytest.mark.django_db
class TestBroadcastTransition:
    """Tests for _broadcast_transition WebSocket broadcast."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_broadcast_transition_to_channel_layer(self, plugin: OwnTracksPlugin) -> None:
        """Should broadcast transition event to channel layer."""
        mock_layer = AsyncMock()
        mock_layer.group_send = AsyncMock()

        transition_data = {
            "id": 1, "device_id": "phone", "event": "enter",
            "region_id": "rid-1", "description": "Home",
            "timestamp": "2024-01-15T12:00:00+00:00",
            "waypoint_label": "Home",
        }

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
            await plugin._broadcast_transition(transition_data)

        mock_layer.group_send.assert_called_once()
        call_args = mock_layer.group_send.call_args
        assert_that(call_args[0][0], equal_to("locations"))
        assert_that(call_args[0][1], has_entries(type="transition_event", data=transition_data))

    @pytest.mark.asyncio
    async def test_broadcast_transition_no_channel_layer(self, plugin: OwnTracksPlugin) -> None:
        """Should not raise when channel layer is unavailable."""
        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=None):
            await plugin._broadcast_transition({"id": 1})

    @pytest.mark.asyncio
    async def test_handle_transition_message_saves_to_db(
        self, plugin: OwnTracksPlugin,
    ) -> None:
        """Should save Transition when device publishes transition message."""
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="alice2", password="pass")
        Device.objects.create(device_id="alice2phone", name="alice2phone", owner=user)

        message = MagicMock()
        message.topic = "owntracks/alice2/alice2phone"
        message.data = json.dumps({
            "_type": "transition",
            "event": "enter",
            "desc": "Home",
            "tst": 1704067200,
            "rid": "rid-home",
            "lat": 51.5,
            "lon": -0.1,
            "acc": 10,
        }).encode()

        with patch.object(plugin, "_broadcast_transition", new_callable=AsyncMock):
            await plugin.on_broker_message_received(client_id="client", message=message)

        device = Device.objects.get(device_id="alice2phone")
        assert_that(Transition.objects.filter(device=device).count(), equal_to(1))
        t = Transition.objects.get(device=device)
        assert_that(t.event, equal_to("enter"))
        assert_that(t.region_id, equal_to("rid-home"))

    @pytest.mark.asyncio
    async def test_handle_waypoints_message_upserts_waypoints(
        self, plugin: OwnTracksPlugin,
    ) -> None:
        """Should upsert Waypoints when device publishes waypoints message."""
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="alice3", password="pass")
        Device.objects.create(device_id="tablet", name="tablet", owner=user)

        message = MagicMock()
        message.topic = "owntracks/alice3/tablet"
        message.data = json.dumps({
            "_type": "waypoints",
            "waypoints": [
                {"_type": "waypoint", "desc": "Home", "lat": 51.5, "lon": -0.1, "rad": 100, "rid": "rid-a"},
                {"_type": "waypoint", "desc": "Work", "lat": 51.52, "lon": -0.08, "rad": 50, "rid": "rid-b"},
            ],
        }).encode()

        await plugin.on_broker_message_received(client_id="client", message=message)

        assert_that(Waypoint.objects.count(), equal_to(2))
        assert_that(Waypoint.objects.get(label="Home").latitude, equal_to(51.5))


@pytest.mark.django_db
class TestBroadcastWaypoints:
    """Tests for _broadcast_waypoints WebSocket broadcast."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_broadcast_waypoints_to_channel_layer(self, plugin: OwnTracksPlugin) -> None:
        """Should broadcast waypoint sync event to channel layer."""
        mock_layer = AsyncMock()
        mock_layer.group_send = AsyncMock()

        waypoint_data = {"device_display": "alice/phone", "new_count": 2}

        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
            await plugin._broadcast_waypoints(waypoint_data)

        mock_layer.group_send.assert_called_once()
        call_args = mock_layer.group_send.call_args
        assert_that(call_args[0][0], equal_to("locations"))
        assert_that(call_args[0][1], has_entries(type="waypoint_event", data=waypoint_data))

    @pytest.mark.asyncio
    async def test_broadcast_waypoints_no_channel_layer(self, plugin: OwnTracksPlugin) -> None:
        """Should not raise when channel layer is unavailable."""
        with patch("app.mqtt.plugin.get_channel_layer_lazy", return_value=None):
            await plugin._broadcast_waypoints({"device_display": "alice/phone", "new_count": 1})


@pytest.mark.django_db
class TestHandleCmdFromDevice:
    """Tests for OwnTracksPlugin._handle_cmd_from_device."""

    @pytest.fixture
    def plugin(self, mock_broker_context: MagicMock) -> OwnTracksPlugin:
        """Create plugin instance for testing."""
        return OwnTracksPlugin(mock_broker_context)

    @pytest.mark.asyncio
    async def test_cmd_logs_observed_action(self, plugin: OwnTracksPlugin) -> None:
        """Should log the observed cmd action at DEBUG level."""
        cmd_data = {
            "action": "reportLocation",
            "user": "hcma",
            "device": "pixel7pro",
            "topic": "owntracks/hcma/pixel7pro/cmd",
            "message": {"_type": "cmd", "action": "reportLocation"},
            "transport": "mqtt-tls",
            "mqtt_user": "hcma",
        }

        with patch("app.mqtt.plugin.logger") as mock_logger, \
             patch("app.mqtt.plugin.get_other_devices", return_value=[]):
            await plugin._handle_cmd_from_device(cmd_data)

        mock_logger.debug.assert_called()
        debug_msg = mock_logger.debug.call_args_list[0][0][0]
        assert_that(debug_msg, contains_string("Observed cmd action"))

    @pytest.mark.asyncio
    async def test_cmd_registered_as_plugin_callback(
        self, mock_broker_context: MagicMock
    ) -> None:
        """Plugin should register a cmd callback on init."""
        plugin = OwnTracksPlugin(mock_broker_context)
        assert_that(plugin._handler._cmd_callbacks, has_length(1))

    @pytest.mark.asyncio
    async def test_full_flow_cmd_message_invokes_callback(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """End-to-end: a cmd MQTT message on any /cmd topic invokes the callback."""
        message = MagicMock()
        message.topic = "owntracks/hcma/pixel7pro/cmd"
        message.data = json.dumps({
            "_type": "cmd",
            "action": "reportLocation",
        }).encode()

        with patch("app.mqtt.plugin.logger") as mock_logger, \
             patch("app.mqtt.plugin.get_other_devices", return_value=[]):
            await plugin.on_broker_message_received(
                client_id="test-client",
                message=message,
            )

        debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
        assert_that(
            any("Observed cmd action" in c for c in debug_calls),
            is_(True),
        )

    @pytest.mark.asyncio
    async def test_report_location_relayed_to_other_devices(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """reportLocation on requester's own topic relays to all other devices."""
        cmd_data = {
            "action": "reportLocation",
            "user": "hcma",
            "device": "pixel7pro",
            "topic": "owntracks/hcma/pixel7pro/cmd",
            "message": {"_type": "cmd", "action": "reportLocation"},
            "transport": "mqtt",
            "mqtt_user": "hcma",
        }
        other_devices = [("kristen", "pixel7"), ("kristen", "tablet")]

        with patch("app.mqtt.plugin.get_other_devices", return_value=other_devices), \
             patch("app.mqtt.plugin.CommandPublisher") as mock_publisher_cls:
            mock_publisher = AsyncMock()
            mock_publisher.send_command = AsyncMock(return_value=True)
            mock_publisher_cls.return_value = mock_publisher

            await plugin._handle_cmd_from_device(cmd_data)

        assert_that(mock_publisher.send_command.call_count, equal_to(2))
        called_ids = {call.args[0] for call in mock_publisher.send_command.call_args_list}
        assert_that(called_ids, equal_to({"kristen/pixel7", "kristen/tablet"}))

    @pytest.mark.asyncio
    async def test_report_location_not_relayed_when_no_other_devices(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """reportLocation relay is skipped when there are no other devices."""
        cmd_data = {
            "action": "reportLocation",
            "user": "hcma",
            "device": "pixel7pro",
            "topic": "owntracks/hcma/pixel7pro/cmd",
            "message": {"_type": "cmd", "action": "reportLocation"},
            "transport": "mqtt",
            "mqtt_user": "hcma",
        }

        with patch("app.mqtt.plugin.get_other_devices", return_value=[]), \
             patch("app.mqtt.plugin.CommandPublisher") as mock_publisher_cls:
            await plugin._handle_cmd_from_device(cmd_data)

        mock_publisher_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_report_location_cmd_not_relayed(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """Only reportLocation triggers relay; other actions are not forwarded."""
        cmd_data = {
            "action": "dump",
            "user": "hcma",
            "device": "pixel7pro",
            "topic": "owntracks/hcma/pixel7pro/cmd",
            "message": {"_type": "cmd", "action": "dump"},
            "transport": "mqtt",
            "mqtt_user": "hcma",
        }

        with patch("app.mqtt.plugin.get_other_devices") as mock_get, \
             patch("app.mqtt.plugin.CommandPublisher") as mock_publisher_cls:
            await plugin._handle_cmd_from_device(cmd_data)

        mock_get.assert_not_called()
        mock_publisher_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_report_location_on_friend_topic_not_relayed(
        self, plugin: OwnTracksPlugin
    ) -> None:
        """reportLocation on a friend's /cmd topic (new app behaviour) is not relayed."""
        # topic_user (kristen) != mqtt_user (hcma) — new master branch behaviour
        cmd_data = {
            "action": "reportLocation",
            "user": "kristen",
            "device": "pixel7",
            "topic": "owntracks/kristen/pixel7/cmd",
            "message": {"_type": "cmd", "action": "reportLocation"},
            "transport": "mqtt",
            "mqtt_user": "hcma",
        }

        with patch("app.mqtt.plugin.get_other_devices") as mock_get, \
             patch("app.mqtt.plugin.CommandPublisher") as mock_publisher_cls:
            await plugin._handle_cmd_from_device(cmd_data)

        mock_get.assert_not_called()
        mock_publisher_cls.assert_not_called()


class TestGetOtherDevices(TestCase):
    """Tests for get_other_devices DB helper."""

    def test_excludes_requesting_user_devices(self) -> None:
        """Should not return devices owned by the requesting user."""
        from django.contrib.auth.models import User
        user_a = User.objects.create_user(username="hcma_god", password="x")
        user_b = User.objects.create_user(username="kristen_god", password="x")
        Device.objects.create(device_id="pixel7pro_god", mqtt_user="hcma_god", owner=user_a)
        Device.objects.create(device_id="pixel7_god", mqtt_user="kristen_god", owner=user_b)

        result = get_other_devices("hcma_god")

        assert_that(result, has_item(("kristen_god", "pixel7_god")))
        assert_that(result, is_not(has_item(("hcma_god", "pixel7pro_god"))))

    def test_excludes_devices_with_no_mqtt_user(self) -> None:
        """Devices with no mqtt_user are excluded (topic cannot be constructed)."""
        Device.objects.create(device_id="mystery_god", mqtt_user="")

        result = get_other_devices("anyone")

        device_ids = [d[1] for d in result]
        assert_that(device_ids, is_not(has_item("mystery_god")))

    def test_excludes_requester_and_includes_others(self) -> None:
        """Returns only other users' devices, not the requesting user's."""
        from django.contrib.auth.models import User
        user_a = User.objects.create_user(username="solo_god", password="x")
        Device.objects.create(device_id="solo_device_god", mqtt_user="solo_god", owner=user_a)

        result = get_other_devices("solo_god")

        assert_that(result, is_not(has_item(("solo_god", "solo_device_god"))))
