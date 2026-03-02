"""Tests for the MQTT OwnTracks plugin."""

import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.test import TestCase
from hamcrest import (assert_that, contains_string, equal_to, has_entries,
                      has_length, is_, is_not, none, not_none, starts_with)

from my_tracks.models import Device, Location, OwnTracksMessage
from my_tracks.mqtt.plugin import (OwnTracksPlugin, _ClientTLSInfo,
                                   _extract_tls_info, get_channel_layer_lazy,
                                   save_location_to_db, save_lwt_to_db)

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

        with patch("my_tracks.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
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

        with patch("my_tracks.mqtt.plugin.get_channel_layer_lazy", return_value=None):
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

        with patch("my_tracks.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
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

        with patch("my_tracks.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
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

        with patch("my_tracks.mqtt.plugin.get_channel_layer_lazy", return_value=None):
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

        with patch("my_tracks.mqtt.plugin.get_channel_layer_lazy", return_value=mock_layer):
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

        with patch("my_tracks.mqtt.plugin.logger") as mock_logger:
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

        with patch("my_tracks.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_v311_does_not_log_warning(self, plugin: OwnTracksPlugin) -> None:
        """MQTT v3.1.1 (level 4) should not trigger any warning."""
        packet = self._make_connect_packet(proto_name="MQTT", proto_level=4)

        with patch("my_tracks.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_connect_packet_ignored(self, plugin: OwnTracksPlugin) -> None:
        """Non-CONNECT packets should be silently ignored."""
        packet = MagicMock()  # Not a ConnectPacket

        with patch("my_tracks.mqtt.plugin.logger") as mock_logger:
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

        with patch("my_tracks.mqtt.plugin.logger") as mock_logger:
            await plugin.on_mqtt_packet_received(packet=packet)

        mock_logger.warning.assert_not_called()


class TestGetChannelLayerLazy:
    """Tests for get_channel_layer_lazy function."""

    def test_returns_channel_layer_when_available(self) -> None:
        """Should return the channel layer when get_channel_layer succeeds."""
        mock_layer = MagicMock()
        with patch("my_tracks.mqtt.plugin.get_channel_layer", return_value=mock_layer):
            result = get_channel_layer_lazy()
        assert_that(result, equal_to(mock_layer))

    def test_returns_none_on_exception(self) -> None:
        """Should return None when get_channel_layer raises an exception."""
        with patch(
            "my_tracks.mqtt.plugin.get_channel_layer",
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
            patch("my_tracks.mqtt.plugin.save_location_to_db", return_value=None),
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
            patch("my_tracks.mqtt.plugin.save_location_to_db", return_value=serialized),
            patch.object(plugin, "_broadcast_location", broadcast_mock),
        ):
            await plugin._handle_location({"device": "mydev", "latitude": 51.5, "longitude": -0.1})

        broadcast_mock.assert_called_once_with(serialized)


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
            patch("my_tracks.mqtt.plugin.save_lwt_to_db", return_value=None),
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
            patch("my_tracks.mqtt.plugin.save_lwt_to_db", return_value=status_data),
            patch.object(plugin, "_broadcast_device_status", broadcast_mock),
        ):
            await plugin._handle_lwt({"device": "user/phone", "event": "offline"})

        broadcast_mock.assert_called_once_with(status_data)


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
        """Should log transition data and return without error."""
        transition_data = {
            "device": "phone",
            "event": "enter",
            "description": "Home",
        }
        await plugin._handle_transition(transition_data)

    @pytest.mark.asyncio
    async def test_logs_transition_with_missing_keys(
        self,
        plugin: OwnTracksPlugin,
    ) -> None:
        """Should handle transition data with missing optional keys."""
        transition_data: dict[str, Any] = {
            "device": "tablet",
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
        """Should create a new device with 'Device {id}' naming pattern."""
        location_data = {
            "device": "newdevice99",
            "latitude": 35.6762,
            "longitude": 139.6503,
            "timestamp": datetime(2024, 5, 1, 8, 0, 0, tzinfo=UTC),
        }

        result = save_location_to_db(location_data)
        assert_that(result, is_not(none()))

        device = Device.objects.get(device_id="newdevice99")
        assert_that(device.name, equal_to("Device newdevice99"))


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
        assert_that(result.cn, equal_to("alice"))
        # Fingerprint is first 4 bytes of SHA-256 in hex, colon-separated
        assert_that(len(result.fingerprint.split(":")), equal_to(4))

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
        assert_that(result.cn, equal_to("unknown"))


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

    def test_tls_tag_for_unknown_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return 'unknown' for client not in cache."""
        assert_that(plugin._tls_tag("never-seen"), equal_to("unknown"))

    def test_tls_tag_for_non_tls_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return 'non-TLS' for client connected without TLS."""
        plugin._client_tls["plain-client"] = None
        assert_that(plugin._tls_tag("plain-client"), equal_to("non-TLS"))

    def test_tls_tag_for_tls_client(self, plugin: OwnTracksPlugin) -> None:
        """Should return TLS info string for TLS client."""
        info = _ClientTLSInfo(cn="alice", fingerprint="AA:BB:CC:DD")
        plugin._client_tls["tls-client"] = info
        assert_that(plugin._tls_tag("tls-client"), equal_to("TLS CN=alice [AA:BB:CC:DD]"))

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
        assert_that(plugin._client_tls["phone-123"].cn, equal_to("phoneuser"))

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