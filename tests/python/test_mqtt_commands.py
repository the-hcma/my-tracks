"""Tests for the MQTT command module."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hamcrest import (assert_that, contains_string, equal_to, greater_than,
                      has_entries, has_key, instance_of, is_, is_not,
                      less_than, none, not_none)

from app.mqtt.commands import (Command, CommandPublisher, CommandType,
                               get_command_topic, mqtt_payload_json_for_log,
                               parse_device_id)


class TestCommandType:
    """Tests for CommandType enum."""

    def test_report_location_value(self) -> None:
        """Test REPORT_LOCATION has correct value."""
        assert_that(CommandType.REPORT_LOCATION.value, equal_to("reportLocation"))

    def test_set_waypoints_value(self) -> None:
        """Test SET_WAYPOINTS has correct value."""
        assert_that(CommandType.SET_WAYPOINTS.value, equal_to("setWaypoints"))

    def test_clear_waypoints_value(self) -> None:
        """Test CLEAR_WAYPOINTS has correct value."""
        assert_that(CommandType.CLEAR_WAYPOINTS.value, equal_to("clearWaypoints"))

    def test_set_configuration_value(self) -> None:
        """Test SET_CONFIGURATION has correct value."""
        assert_that(CommandType.SET_CONFIGURATION.value, equal_to("setConfiguration"))

    def test_dump_value(self) -> None:
        """Test DUMP has correct value."""
        assert_that(CommandType.DUMP.value, equal_to("dump"))

    def test_restart_value(self) -> None:
        """Test RESTART has correct value."""
        assert_that(CommandType.RESTART.value, equal_to("restart"))

    def test_action_value(self) -> None:
        """Test ACTION has correct value."""
        assert_that(CommandType.ACTION.value, equal_to("action"))


class TestCommand:
    """Tests for Command dataclass."""

    def test_command_creation(self) -> None:
        """Test basic command creation."""
        cmd = Command(command_type=CommandType.REPORT_LOCATION)
        assert_that(cmd.command_type, equal_to(CommandType.REPORT_LOCATION))
        assert_that(cmd.payload, equal_to({}))
        assert_that(cmd.created_at, instance_of(datetime))

    def test_command_with_payload(self) -> None:
        """Test command creation with payload."""
        payload = {"key": "value"}
        cmd = Command(command_type=CommandType.ACTION, payload=payload)
        assert_that(cmd.payload, equal_to(payload))

    def test_to_mqtt_payload_basic(self) -> None:
        """Test serialization to MQTT payload."""
        cmd = Command(command_type=CommandType.REPORT_LOCATION)
        payload = cmd.to_mqtt_payload()

        assert_that(payload, instance_of(bytes))

        data = json.loads(payload.decode("utf-8"))
        assert_that(data, has_entries({"_type": "cmd", "action": "reportLocation"}))

    def test_to_mqtt_payload_with_extra_fields(self) -> None:
        """Test serialization includes extra payload fields."""
        cmd = Command(
            command_type=CommandType.SET_WAYPOINTS,
            payload={"waypoints": {"_type": "waypoints", "waypoints": [{"_type": "waypoint", "desc": "Home", "lat": 51.5, "lon": -0.1}]}},
        )
        payload = cmd.to_mqtt_payload()
        data = json.loads(payload.decode("utf-8"))

        assert_that(data["_type"], equal_to("cmd"))
        assert_that(data["action"], equal_to("setWaypoints"))
        assert_that(data["waypoints"]["_type"], equal_to("waypoints"))
        assert_that(len(data["waypoints"]["waypoints"]), equal_to(1))


class TestCommandFactoryMethods:
    """Tests for Command factory methods."""

    def test_report_location(self) -> None:
        """Test report_location factory method."""
        cmd = Command.report_location()
        assert_that(cmd.command_type, equal_to(CommandType.REPORT_LOCATION))
        assert_that(cmd.payload, equal_to({}))

    def test_set_waypoints(self) -> None:
        """Test set_waypoints factory method produces correct OwnTracks protocol structure."""
        waypoints = [
            {"desc": "Home", "lat": 51.5074, "lon": -0.1278, "rad": 100},
            {"desc": "Work", "lat": 51.5200, "lon": -0.0800, "rad": 50},
        ]
        cmd = Command.set_waypoints(waypoints)

        assert_that(cmd.command_type, equal_to(CommandType.SET_WAYPOINTS))
        wrapper = cmd.payload["waypoints"]
        assert_that(wrapper["_type"], equal_to("waypoints"))
        assert_that(len(wrapper["waypoints"]), equal_to(2))
        assert_that(wrapper["waypoints"][0]["_type"], equal_to("waypoint"))
        assert_that(wrapper["waypoints"][0]["desc"], equal_to("Home"))
        assert_that(wrapper["waypoints"][1]["desc"], equal_to("Work"))

    def test_set_waypoints_empty_list(self) -> None:
        """Test set_waypoints with empty list."""
        cmd = Command.set_waypoints([])
        assert_that(cmd.command_type, equal_to(CommandType.SET_WAYPOINTS))
        assert_that(cmd.payload["waypoints"]["waypoints"], equal_to([]))

    def test_clear_waypoints(self) -> None:
        """Test clear_waypoints factory method."""
        cmd = Command.clear_waypoints()
        assert_that(cmd.command_type, equal_to(CommandType.CLEAR_WAYPOINTS))
        assert_that(cmd.payload, equal_to({}))

    def test_set_configuration(self) -> None:
        """Test set_configuration factory method."""
        config = {"monitoring": 1, "locatorPriority": 2}
        cmd = Command.set_configuration(config)

        assert_that(cmd.command_type, equal_to(CommandType.SET_CONFIGURATION))
        assert_that(cmd.payload, has_entries({"configuration": config}))

    def test_dump(self) -> None:
        """Test dump factory method."""
        cmd = Command.dump()
        assert_that(cmd.command_type, equal_to(CommandType.DUMP))
        assert_that(cmd.payload, equal_to({}))

    def test_action_with_name_only(self) -> None:
        """Test action factory method with name only."""
        cmd = Command.action("myAction")
        assert_that(cmd.command_type, equal_to(CommandType.ACTION))
        assert_that(cmd.payload, has_entries({"name": "myAction"}))
        assert_that(cmd.payload, is_not(has_key("params")))

    def test_action_with_params(self) -> None:
        """Test action factory method with params."""
        params = {"speed": 100, "direction": "north"}
        cmd = Command.action("navigate", params=params)

        assert_that(cmd.command_type, equal_to(CommandType.ACTION))
        assert_that(cmd.payload, has_entries({"name": "navigate", "params": params}))


class TestGetCommandTopic:
    """Tests for get_command_topic function."""

    def test_basic_topic(self) -> None:
        """Test basic topic generation."""
        topic = get_command_topic("alice", "phone")
        assert_that(topic, equal_to("owntracks/alice/phone/cmd"))

    def test_topic_with_special_chars(self) -> None:
        """Test topic generation with special characters."""
        topic = get_command_topic("user_123", "device-1")
        assert_that(topic, equal_to("owntracks/user_123/device-1/cmd"))

    def test_topic_with_uppercase(self) -> None:
        """Test topic generation preserves case."""
        topic = get_command_topic("Alice", "Phone")
        assert_that(topic, equal_to("owntracks/Alice/Phone/cmd"))


class TestParseDeviceId:
    """Tests for parse_device_id function."""

    def test_valid_device_id(self) -> None:
        """Test parsing valid device ID."""
        result = parse_device_id("alice/phone")
        assert_that(result, equal_to(("alice", "phone")))

    def test_device_id_with_multiple_slashes(self) -> None:
        """Test parsing device ID with multiple slashes (takes first split)."""
        result = parse_device_id("alice/phone/extra")
        assert_that(result, equal_to(("alice", "phone/extra")))

    def test_invalid_device_id_no_slash(self) -> None:
        """Test parsing device ID without slash."""
        result = parse_device_id("alicephone")
        assert_that(result, none())

    def test_empty_device_id(self) -> None:
        """Test parsing empty device ID."""
        result = parse_device_id("")
        assert_that(result, none())

    def test_device_id_with_only_slash(self) -> None:
        """Test parsing device ID with only slash."""
        result = parse_device_id("/")
        # Split "/" gives ["", ""] which is length 2, so returns ("", "")
        assert_that(result, equal_to(("", "")))


class TestMqttPayloadJsonForLog:
    """Tests for mqtt_payload_json_for_log helper."""

    def test_sorts_top_level_keys(self) -> None:
        """Log helper re-encodes with sorted keys for stable output."""
        raw = b'{"action": "reportLocation", "_type": "cmd"}'
        out = mqtt_payload_json_for_log(raw)
        assert_that(out.index('"_type"'), less_than(out.index('"action"')))

    def test_invalid_utf8_falls_back(self) -> None:
        """Non-UTF-8 payload is logged as repr(bytes)."""
        raw = b"\xff\xfe not utf-8"
        out = mqtt_payload_json_for_log(raw)
        assert_that(out, contains_string('xff'))


class TestCommandPublisher:
    """Tests for CommandPublisher class."""

    def test_init_without_client(self) -> None:
        """Test initialization without client."""
        publisher = CommandPublisher()
        assert_that(publisher.is_connected, is_(False))

    def test_init_with_client(self) -> None:
        """Test initialization with client."""
        mock_client = MagicMock()
        publisher = CommandPublisher(mqtt_client=mock_client)
        assert_that(publisher.is_connected, is_(True))

    def test_set_client(self) -> None:
        """Test setting client after initialization."""
        publisher = CommandPublisher()
        assert_that(publisher.is_connected, is_(False))

        mock_client = MagicMock()
        publisher.set_client(mock_client)
        assert_that(publisher.is_connected, is_(True))

    @pytest.mark.asyncio
    async def test_send_command_no_client(self) -> None:
        """Test sending command without client raises error."""
        publisher = CommandPublisher()
        cmd = Command.report_location()

        with pytest.raises(RuntimeError, match="No MQTT client configured"):
            await publisher.send_command("alice/phone", cmd)

    @pytest.mark.asyncio
    async def test_send_command_invalid_device_id(self) -> None:
        """Test sending command with invalid device ID."""
        mock_client = MagicMock()
        publisher = CommandPublisher(mqtt_client=mock_client)
        cmd = Command.report_location()

        result = await publisher.send_command("invalid", cmd)
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_send_command_logs_full_payload_at_info(self) -> None:
        """Every outbound command logs topic, byte size, and JSON at INFO once."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()
        with patch("app.mqtt.commands.logger.info") as mock_info:
            publisher = CommandPublisher(mqtt_client=mock_client)
            await publisher.send_command("alice/phone", Command.report_location())
        mock_info.assert_called_once()
        fmt, *fmt_args = mock_info.call_args[0]
        line = fmt % tuple(fmt_args)
        assert_that(line, contains_string("[mqtt] reportLocation"))
        assert_that(line, contains_string("owntracks/alice/phone/cmd"))
        assert_that(line, contains_string("bytes="))
        assert_that(line, contains_string('"action": "reportLocation"'))

    @pytest.mark.asyncio
    async def test_send_command_with_internal_broadcast(self) -> None:
        """Test sending command via amqtt internal broadcast."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()

        publisher = CommandPublisher(mqtt_client=mock_client)
        cmd = Command.report_location()

        result = await publisher.send_command("alice/phone", cmd)

        assert_that(result, is_(True))
        mock_client.internal_message_broadcast.assert_called_once()

        # Verify the call arguments
        call_args = mock_client.internal_message_broadcast.call_args
        assert_that(call_args[0][0], equal_to("owntracks/alice/phone/cmd"))
        # Second arg is payload bytes
        payload_data = json.loads(call_args[0][1].decode("utf-8"))
        assert_that(payload_data["_type"], equal_to("cmd"))
        assert_that(payload_data["action"], equal_to("reportLocation"))
        # Third arg is QoS — default is 0 (fire-and-forget; see send_command docstring)
        assert_that(call_args[0][2], equal_to(0))

    @pytest.mark.asyncio
    async def test_send_command_with_standard_client_sync(self) -> None:
        """Test sending command via standard MQTT client (sync publish)."""
        # Create a client with only 'publish' method, not internal_message_broadcast
        mock_client = MagicMock(spec=["publish"])
        mock_result = MagicMock(spec=[])  # No wait_for_publish
        mock_client.publish = MagicMock(return_value=mock_result)

        publisher = CommandPublisher(mqtt_client=mock_client)
        cmd = Command.report_location()

        result = await publisher.send_command("alice/phone", cmd)

        assert_that(result, is_(True))
        mock_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_command_with_custom_qos(self) -> None:
        """Test sending command with custom QoS."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()

        publisher = CommandPublisher(mqtt_client=mock_client)
        cmd = Command.report_location()

        await publisher.send_command("alice/phone", cmd, qos=2)

        call_args = mock_client.internal_message_broadcast.call_args
        assert_that(call_args[0][2], equal_to(2))

    @pytest.mark.asyncio
    async def test_send_command_exception_handling(self) -> None:
        """Test exception handling during command send."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock(
            side_effect=Exception("Connection lost")
        )

        publisher = CommandPublisher(mqtt_client=mock_client)
        cmd = Command.report_location()

        result = await publisher.send_command("alice/phone", cmd)
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_send_command_unknown_client_type(self) -> None:
        """Test sending command with unknown client type."""
        # Client with neither internal_message_broadcast nor publish
        mock_client = MagicMock(spec=[])

        publisher = CommandPublisher(mqtt_client=mock_client)
        cmd = Command.report_location()

        result = await publisher.send_command("alice/phone", cmd)
        assert_that(result, is_(False))


class TestCommandPublisherHelperMethods:
    """Tests for CommandPublisher helper methods."""

    @pytest.mark.asyncio
    async def test_request_location(self) -> None:
        """Test request_location helper method."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()

        publisher = CommandPublisher(mqtt_client=mock_client)
        result = await publisher.request_location("alice/phone")

        assert_that(result, is_(True))
        call_args = mock_client.internal_message_broadcast.call_args
        payload_data = json.loads(call_args[0][1].decode("utf-8"))
        assert_that(payload_data["action"], equal_to("reportLocation"))

    @pytest.mark.asyncio
    async def test_set_waypoints(self) -> None:
        """Test set_waypoints helper method."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()

        publisher = CommandPublisher(mqtt_client=mock_client)
        waypoints = [{"desc": "Home", "lat": 51.5, "lon": -0.1}]

        result = await publisher.set_waypoints("alice/phone", waypoints)

        assert_that(result, is_(True))
        call_args = mock_client.internal_message_broadcast.call_args
        payload_data = json.loads(call_args[0][1].decode("utf-8"))
        assert_that(payload_data["action"], equal_to("setWaypoints"))
        wrapper = payload_data["waypoints"]
        assert_that(wrapper["_type"], equal_to("waypoints"))
        assert_that(wrapper["waypoints"][0]["_type"], equal_to("waypoint"))
        assert_that(wrapper["waypoints"][0]["desc"], equal_to("Home"))

    @pytest.mark.asyncio
    async def test_set_waypoints_float_precision_in_json(self) -> None:
        """JSON encoding keeps float values (shortest round-trip repr)."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()

        publisher = CommandPublisher(mqtt_client=mock_client)
        lat = 1.2345678901234567
        lon = -9.876543210987654
        waypoints = [
            {
                'desc': 'P',
                'lat': lat,
                'lon': lon,
                'rad': 250,
                'tst': 1700000000,
            },
        ]

        await publisher.set_waypoints('alice/phone', waypoints)

        call_args = mock_client.internal_message_broadcast.call_args
        raw = call_args[0][1].decode('utf-8')
        payload_data = json.loads(raw)
        wp0 = payload_data["waypoints"]["waypoints"][0]
        assert_that(wp0["lat"], equal_to(lat))
        assert_that(wp0["lon"], equal_to(lon))
        assert_that(raw, contains_string(str(lat)))
        assert_that(raw, contains_string(str(lon)))

    @pytest.mark.asyncio
    async def test_clear_waypoints(self) -> None:
        """Test clear_waypoints helper method."""
        mock_client = MagicMock()
        mock_client.internal_message_broadcast = AsyncMock()

        publisher = CommandPublisher(mqtt_client=mock_client)
        result = await publisher.clear_waypoints("alice/phone")

        assert_that(result, is_(True))
        call_args = mock_client.internal_message_broadcast.call_args
        payload_data = json.loads(call_args[0][1].decode("utf-8"))
        assert_that(payload_data["action"], equal_to("clearWaypoints"))


class TestCommandTimestamp:
    """Tests for command timestamp handling."""

    def test_created_at_is_utc(self) -> None:
        """Test that created_at timestamp is in UTC."""
        cmd = Command.report_location()
        assert_that(cmd.created_at.tzinfo, not_none())
        # Check it's close to now
        now = datetime.now(tz=UTC)
        diff = abs((now - cmd.created_at).total_seconds())
        assert_that(diff, is_(greater_than(-1)))
        assert_that(diff < 1, is_(True))

    def test_custom_created_at(self) -> None:
        """Test command with custom created_at."""
        custom_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        cmd = Command(
            command_type=CommandType.DUMP,
            created_at=custom_time,
        )
        assert_that(cmd.created_at, equal_to(custom_time))
