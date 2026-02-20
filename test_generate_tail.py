"""
Test suite for the generate-tail traffic generator script.

Tests cover both HTTP and MQTT transport modes, position shifting,
tail location creation, runtime config reading, and CLI integration.
"""
import importlib.machinery
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hamcrest import (assert_that, calling, close_to, equal_to, greater_than,
                      has_entries, has_key, is_not, less_than, none, not_none)

# Import generate-tail as a module (it has a hyphen in the name and no .py extension)
_loader = importlib.machinery.SourceFileLoader(
    "generate_tail", str(Path(__file__).parent / "generate-tail")
)
spec = importlib.util.spec_from_loader("generate_tail", _loader)
assert spec is not None
generate_tail = importlib.util.module_from_spec(spec)
# Prevent auto-venv activation during test import
with patch.object(sys, "executable", str(Path(__file__).parent / ".venv" / "bin" / "python")):
    _loader.exec_module(generate_tail)

# Import the functions we want to test
Direction = generate_tail.Direction
shift_position = generate_tail.shift_position
create_tail_location = generate_tail.create_tail_location
read_mqtt_port_from_config = generate_tail.read_mqtt_port_from_config
MQTTTransport = generate_tail.MQTTTransport
format_time_full = generate_tail.format_time_full
_print_location_info = generate_tail._print_location_info
_print_summary = generate_tail._print_summary


# ============================================================
# Direction enum tests
# ============================================================


class TestDirection:
    """Tests for the Direction enum."""

    def test_all_directions_exist(self) -> None:
        assert_that(Direction.north.value, equal_to("north"))
        assert_that(Direction.south.value, equal_to("south"))
        assert_that(Direction.east.value, equal_to("east"))
        assert_that(Direction.west.value, equal_to("west"))

    def test_direction_count(self) -> None:
        assert_that(list(Direction), has_key(3).__class__)
        assert_that(len(list(Direction)), equal_to(4))


# ============================================================
# Position shifting tests
# ============================================================


class TestShiftPosition:
    """Tests for GPS position shifting logic."""

    def test_shift_north_increases_latitude(self) -> None:
        lat, lon = shift_position(37.0, -122.0, 5.0, Direction.north)
        assert_that(lat, greater_than(37.0))
        assert_that(lon, close_to(-122.0, 0.0001))

    def test_shift_south_decreases_latitude(self) -> None:
        lat, lon = shift_position(37.0, -122.0, 5.0, Direction.south)
        assert_that(lat, less_than(37.0))
        assert_that(lon, close_to(-122.0, 0.0001))

    def test_shift_east_increases_longitude(self) -> None:
        lat, lon = shift_position(37.0, -122.0, 5.0, Direction.east)
        assert_that(lat, close_to(37.0, 0.0001))
        assert_that(lon, greater_than(-122.0))

    def test_shift_west_decreases_longitude(self) -> None:
        lat, lon = shift_position(37.0, -122.0, 5.0, Direction.west)
        assert_that(lat, close_to(37.0, 0.0001))
        assert_that(lon, less_than(-122.0))

    def test_shift_distance_approximately_correct(self) -> None:
        """Verify that a 1 km shift produces roughly 1 km of displacement."""
        lat, lon = shift_position(45.0, 0.0, 1.0, Direction.north)
        # 1 degree latitude ≈ 111.32 km, so 1 km ≈ 0.00898°
        expected_delta = 1.0 / 111.32
        actual_delta = lat - 45.0
        assert_that(actual_delta, close_to(expected_delta, 0.0001))

    def test_shift_zero_km_returns_same_position(self) -> None:
        lat, lon = shift_position(37.0, -122.0, 0.0, Direction.north)
        assert_that(lat, close_to(37.0, 0.0001))
        assert_that(lon, close_to(-122.0, 0.0001))

    def test_longitude_shift_varies_with_latitude(self) -> None:
        """At higher latitudes, longitude degrees cover less distance."""
        _, lon_equator = shift_position(0.0, 0.0, 1.0, Direction.east)
        _, lon_60 = shift_position(60.0, 0.0, 1.0, Direction.east)
        # At 60° latitude, 1 km east should require a larger longitude change
        equator_delta = lon_equator
        lat60_delta = lon_60
        assert_that(lat60_delta, greater_than(equator_delta))


# ============================================================
# Tail location creation tests
# ============================================================


class TestCreateTailLocation:
    """Tests for creating tail locations from source data."""

    @pytest.fixture
    def sample_location(self) -> dict[str, Any]:
        return {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "timestamp_unix": 1700000000,
            "accuracy": 15,
            "altitude": 100,
            "velocity": 30,
            "battery_level": 75,
            "connection_type": "m",
        }

    def test_creates_owntracks_format(self, sample_location: dict[str, Any]) -> None:
        result = create_tail_location(
            sample_location, "test-tail", 3.5, Direction.east, randomize=False
        )
        assert_that(result, has_entries({
            "_type": "location",
            "tst": 1700000000,
            "tid": "il",
            "acc": 15,
            "alt": 100,
            "vel": 30,
            "batt": 75,
            "conn": "m",
        }))

    def test_shifts_position(self, sample_location: dict[str, Any]) -> None:
        result = create_tail_location(
            sample_location, "test-tail", 3.5, Direction.east, randomize=False
        )
        # Should be shifted east (longitude increases)
        assert_that(result["lon"], greater_than(-122.4194))
        assert_that(result["lat"], close_to(37.7749, 0.001))

    def test_topic_format(self, sample_location: dict[str, Any]) -> None:
        result = create_tail_location(
            sample_location, "my-device", 3.5, Direction.east, randomize=False
        )
        assert_that(result["topic"], equal_to("owntracks/user/my-device"))

    def test_tid_uses_last_two_chars(self, sample_location: dict[str, Any]) -> None:
        result = create_tail_location(
            sample_location, "abc", 3.5, Direction.east, randomize=False
        )
        assert_that(result["tid"], equal_to("bc"))

    def test_tid_short_device(self, sample_location: dict[str, Any]) -> None:
        result = create_tail_location(
            sample_location, "x", 3.5, Direction.east, randomize=False
        )
        assert_that(result["tid"], equal_to("x"))

    def test_randomize_varies_offset(self, sample_location: dict[str, Any]) -> None:
        """With randomize=True, repeated calls should produce slightly different positions."""
        results = [
            create_tail_location(
                sample_location, "t", 3.5, Direction.east, randomize=True
            )["lon"]
            for _ in range(20)
        ]
        unique_values = set(results)
        # With randomization, we should get multiple distinct values
        assert_that(len(unique_values), greater_than(1))

    def test_no_randomize_gives_consistent_results(
        self, sample_location: dict[str, Any]
    ) -> None:
        results = [
            create_tail_location(
                sample_location, "t", 3.5, Direction.east, randomize=False
            )["lon"]
            for _ in range(5)
        ]
        unique_values = set(results)
        assert_that(len(unique_values), equal_to(1))

    def test_missing_optional_fields_use_defaults(self) -> None:
        minimal_location: dict[str, Any] = {
            "latitude": 37.0,
            "longitude": -122.0,
        }
        result = create_tail_location(
            minimal_location, "test", 1.0, Direction.north, randomize=False
        )
        assert_that(result["acc"], equal_to(10))
        assert_that(result["alt"], equal_to(0))
        assert_that(result["vel"], equal_to(0))
        assert_that(result["batt"], equal_to(50))
        assert_that(result["conn"], equal_to("w"))


# ============================================================
# Runtime config reading tests
# ============================================================


class TestReadMqttPortFromConfig:
    """Tests for reading MQTT port from runtime config file."""

    def test_returns_none_when_no_config(self, tmp_path: Path) -> None:
        with patch.object(generate_tail, "RUNTIME_CONFIG", tmp_path / "nonexistent.json"):
            result = read_mqtt_port_from_config()
            assert_that(result, none())

    def test_reads_mqtt_port(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 1883}))
        with patch.object(generate_tail, "RUNTIME_CONFIG", config_file):
            result = read_mqtt_port_from_config()
            assert_that(result, equal_to(1883))

    def test_prefers_actual_mqtt_port(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "mqtt_port": 0,
            "actual_mqtt_port": 54321,
        }))
        with patch.object(generate_tail, "RUNTIME_CONFIG", config_file):
            result = read_mqtt_port_from_config()
            assert_that(result, equal_to(54321))

    def test_returns_none_for_disabled_port(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": -1}))
        with patch.object(generate_tail, "RUNTIME_CONFIG", config_file):
            result = read_mqtt_port_from_config()
            assert_that(result, none())

    def test_handles_malformed_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json{{{")
        with patch.object(generate_tail, "RUNTIME_CONFIG", config_file):
            result = read_mqtt_port_from_config()
            assert_that(result, none())


# ============================================================
# MQTTTransport tests
# ============================================================


class TestMQTTTransport:
    """Tests for the MQTTTransport wrapper class."""

    def test_init_sets_host_and_port(self) -> None:
        transport = MQTTTransport("myhost", 1883)
        assert_that(transport.host, equal_to("myhost"))
        assert_that(transport.port, equal_to(1883))
        assert_that(transport._connected, equal_to(False))

    @pytest.mark.asyncio
    async def test_connect_builds_uri_without_auth(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        transport.client = AsyncMock()
        await transport.connect()
        transport.client.connect.assert_awaited_once_with("mqtt://localhost:1883/")
        assert_that(transport._connected, equal_to(True))

    @pytest.mark.asyncio
    async def test_connect_builds_uri_with_auth(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        transport.client = AsyncMock()
        await transport.connect("user1", "pass1")
        transport.client.connect.assert_awaited_once_with("mqtt://user1:pass1@localhost:1883/")
        assert_that(transport._connected, equal_to(True))

    @pytest.mark.asyncio
    async def test_publish_returns_false_when_not_connected(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        result = await transport.publish("test/topic", {"_type": "location"})
        assert_that(result, equal_to(False))

    @pytest.mark.asyncio
    async def test_publish_sends_json_payload(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        transport.client = AsyncMock()
        transport._connected = True

        payload = {"_type": "location", "lat": 37.0, "lon": -122.0}
        result = await transport.publish("owntracks/user/dev", payload)

        assert_that(result, equal_to(True))
        transport.client.publish.assert_awaited_once()
        call_args = transport.client.publish.call_args
        assert_that(call_args[0][0], equal_to("owntracks/user/dev"))
        # Verify the payload is valid JSON
        published_data = json.loads(call_args[0][1])
        assert_that(published_data, has_entries({"_type": "location", "lat": 37.0}))

    @pytest.mark.asyncio
    async def test_publish_returns_false_on_exception(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        transport.client = AsyncMock()
        transport.client.publish.side_effect = RuntimeError("Connection lost")
        transport._connected = True

        result = await transport.publish("test/topic", {"_type": "location"})
        assert_that(result, equal_to(False))

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        transport.client = AsyncMock()
        transport._connected = True

        await transport.disconnect()
        transport.client.disconnect.assert_awaited_once()
        assert_that(transport._connected, equal_to(False))

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self) -> None:
        transport = MQTTTransport("localhost", 1883)
        transport.client = AsyncMock()
        transport._connected = False

        await transport.disconnect()
        transport.client.disconnect.assert_not_awaited()


# ============================================================
# Format helpers tests
# ============================================================


class TestFormatTimeFull:
    """Tests for timestamp formatting."""

    def test_formats_unix_timestamp(self) -> None:
        result = format_time_full(1700000000)
        assert "UTC:" in result
        assert "Local" in result
        assert "2023" in result  # Nov 14, 2023

    def test_contains_both_timezones(self) -> None:
        result = format_time_full(0)
        assert "UTC: 1970-01-01" in result


# ============================================================
# Print helpers tests
# ============================================================


class TestPrintHelpers:
    """Tests for output formatting helpers."""

    def test_print_location_info_no_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        original = {"latitude": 37.0, "longitude": -122.0}
        tail_loc = {"lat": 37.01, "lon": -121.99, "tst": 1700000000}
        _print_location_info(1, 5, original, tail_loc, "src", "tl")
        captured = capsys.readouterr()
        assert "[1/5]" in captured.out
        assert "src" in captured.out
        assert "tl" in captured.out

    def test_print_summary_dry_run(self, capsys: pytest.CaptureFixture[str]) -> None:
        _print_summary(10, 0, 0, dry_run=True)
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        assert "10" in captured.out

    def test_print_summary_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        _print_summary(10, 10, 0, dry_run=False)
        captured = capsys.readouterr()
        assert "Sent: 10" in captured.out
        assert "Failed: 0" in captured.out

    def test_print_summary_with_failures_raises_exit(self) -> None:
        import click
        with pytest.raises(click.exceptions.Exit):
            _print_summary(10, 7, 3, dry_run=False)


# ============================================================
# HTTP send tests
# ============================================================


class TestSendLocationHTTP:
    """Tests for HTTP location sending."""

    send_location_http = staticmethod(generate_tail.send_location_http)

    @patch("urllib.request.urlopen")
    def test_send_success(self, mock_urlopen: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = self.send_location_http(
            "http://localhost:8080",
            {"_type": "location", "lat": 37.0, "lon": -122.0},
        )
        assert_that(result, equal_to(True))

    @patch("urllib.request.urlopen")
    def test_send_failure(self, mock_urlopen: MagicMock) -> None:
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = self.send_location_http(
            "http://localhost:8080",
            {"_type": "location", "lat": 37.0, "lon": -122.0},
        )
        assert_that(result, equal_to(False))
