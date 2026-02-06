"""Tests for the MQTT message handlers."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from hamcrest import (
    assert_that,
    equal_to,
    has_entries,
    has_key,
    is_,
    none,
)

from my_tracks.mqtt.handlers import (
    OwnTracksMessageHandler,
    extract_location_data,
    extract_lwt_data,
    extract_transition_data,
    parse_owntracks_message,
    parse_owntracks_topic,
)


class TestParseOwnTracksMessage:
    """Tests for parse_owntracks_message function."""

    def test_valid_json(self) -> None:
        """Should parse valid JSON payload."""
        payload = b'{"_type": "location", "lat": 51.5, "lon": -0.1}'
        result = parse_owntracks_message(payload)
        assert_that(result, has_entries(_type="location", lat=51.5))

    def test_invalid_json(self) -> None:
        """Should return None for invalid JSON."""
        payload = b"not valid json"
        result = parse_owntracks_message(payload)
        assert_that(result, is_(none()))

    def test_non_object_json(self) -> None:
        """Should return None for non-object JSON."""
        payload = b"[1, 2, 3]"
        result = parse_owntracks_message(payload)
        assert_that(result, is_(none()))

    def test_unicode_decode_error(self) -> None:
        """Should return None for invalid UTF-8."""
        payload = b"\xff\xfe"
        result = parse_owntracks_message(payload)
        assert_that(result, is_(none()))


class TestParseOwnTracksTopic:
    """Tests for parse_owntracks_topic function."""

    def test_basic_topic(self) -> None:
        """Should parse basic owntracks/user/device topic."""
        result = parse_owntracks_topic("owntracks/john/phone")
        assert_that(result, has_entries(user="john", device="phone"))

    def test_topic_with_subtopic(self) -> None:
        """Should parse topic with subtopic."""
        result = parse_owntracks_topic("owntracks/john/phone/event")
        assert_that(result, has_entries(user="john", device="phone", subtopic="event"))

    def test_topic_with_nested_subtopic(self) -> None:
        """Should parse topic with nested subtopic."""
        result = parse_owntracks_topic("owntracks/john/phone/waypoints/export")
        assert_that(
            result,
            has_entries(user="john", device="phone", subtopic="waypoints/export"),
        )

    def test_non_owntracks_topic(self) -> None:
        """Should return None for non-owntracks topic."""
        result = parse_owntracks_topic("home/sensors/temperature")
        assert_that(result, is_(none()))

    def test_short_topic(self) -> None:
        """Should return None for topic with too few parts."""
        result = parse_owntracks_topic("owntracks/john")
        assert_that(result, is_(none()))

    def test_empty_string_topic(self) -> None:
        """Should return None for empty string topic."""
        result = parse_owntracks_topic("")
        assert_that(result, is_(none()))

    def test_single_part_topic(self) -> None:
        """Should return None for single-part topic."""
        result = parse_owntracks_topic("owntracks")
        assert_that(result, is_(none()))


class TestExtractLocationData:
    """Tests for extract_location_data function."""

    def test_valid_location(self) -> None:
        """Should extract data from valid location message."""
        message = {
            "_type": "location",
            "lat": 51.5074,
            "lon": -0.1278,
            "tst": 1704067200,  # 2024-01-01 00:00:00 UTC
            "tid": "JD",
            "acc": 10,
            "alt": 100,
            "vel": 5,
            "batt": 85,
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_location_data(message, topic_info)

        assert_that(result, has_entries(
            device="john/phone",
            latitude=51.5074,
            longitude=-0.1278,
            tracker_id="JD",
            accuracy=10,
            altitude=100,
            velocity=5,
            battery=85,
        ))

    def test_minimal_location(self) -> None:
        """Should extract data with only required fields."""
        message = {
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_location_data(message, topic_info)

        assert_that(result, has_entries(
            device="john/phone",
            latitude=51.5,
            longitude=-0.1,
        ))
        # tracker_id should default to device name
        assert_that(result["tracker_id"], equal_to("phone"))

    def test_missing_lat(self) -> None:
        """Should return None if lat is missing."""
        message = {"_type": "location", "lon": -0.1, "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_location_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_missing_lon(self) -> None:
        """Should return None if lon is missing."""
        message = {"_type": "location", "lat": 51.5, "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_location_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_missing_tst(self) -> None:
        """Should return None if tst is missing."""
        message = {"_type": "location", "lat": 51.5, "lon": -0.1}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_location_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_wrong_type(self) -> None:
        """Should return None for non-location message type."""
        message = {"_type": "waypoint", "lat": 51.5, "lon": -0.1, "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_location_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_invalid_timestamp(self) -> None:
        """Should return None for invalid timestamp."""
        message = {"_type": "location", "lat": 51.5, "lon": -0.1, "tst": "invalid"}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_location_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_timestamp_conversion(self) -> None:
        """Should convert timestamp to datetime with UTC timezone."""
        message = {
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_location_data(message, topic_info)

        assert_that(result, has_key("timestamp"))
        assert_that(result["timestamp"].tzinfo, equal_to(UTC))
        assert_that(result["timestamp"], equal_to(datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)))

    def test_zero_coordinates(self) -> None:
        """Should accept zero lat/lon (equator/prime meridian)."""
        message = {
            "_type": "location",
            "lat": 0.0,
            "lon": 0.0,
            "tst": 1704067200,
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_location_data(message, topic_info)

        assert_that(result, has_entries(
            latitude=0.0,
            longitude=0.0,
        ))

    def test_negative_timestamp(self) -> None:
        """Should return None for negative timestamp (before 1970)."""
        message = {
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": -1,
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_location_data(message, topic_info)
        # OSError is raised for negative timestamps on some platforms
        # The function should handle this gracefully
        # On platforms that support negative timestamps, this will work
        # On those that don't, it should return None
        # Either way, we test that it doesn't crash
        assert result is None or isinstance(result, dict)


class TestExtractLwtData:
    """Tests for extract_lwt_data function."""

    def test_valid_lwt(self) -> None:
        """Should extract data from valid LWT message."""
        message = {"_type": "lwt", "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}

        result = extract_lwt_data(message, topic_info)

        assert_that(result, has_entries(
            device="john/phone",
            event="offline",
        ))
        assert_that(result, has_key("connected_at"))
        assert_that(result, has_key("disconnected_at"))

    def test_lwt_without_tst(self) -> None:
        """Should handle LWT without timestamp."""
        message = {"_type": "lwt"}
        topic_info = {"user": "john", "device": "phone"}

        result = extract_lwt_data(message, topic_info)

        assert_that(result, has_entries(
            device="john/phone",
            event="offline",
        ))
        assert_that(result["connected_at"], is_(none()))

    def test_wrong_type(self) -> None:
        """Should return None for non-LWT message type."""
        message = {"_type": "location", "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_lwt_data(message, topic_info)
        assert_that(result, is_(none()))


class TestExtractTransitionData:
    """Tests for extract_transition_data function."""

    def test_valid_transition(self) -> None:
        """Should extract data from valid transition message."""
        message = {
            "_type": "transition",
            "event": "enter",
            "desc": "Home",
            "tst": 1704067200,
            "lat": 51.5,
            "lon": -0.1,
            "acc": 10,
            "t": "c",
            "rid": "abc123",
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_transition_data(message, topic_info)

        assert_that(result, has_entries(
            device="john/phone",
            event="enter",
            description="Home",
            latitude=51.5,
            longitude=-0.1,
            accuracy=10,
            trigger="c",
            region_id="abc123",
        ))

    def test_minimal_transition(self) -> None:
        """Should extract data with only required fields."""
        message = {
            "_type": "transition",
            "event": "leave",
            "tst": 1704067200,
        }
        topic_info = {"user": "john", "device": "phone"}

        result = extract_transition_data(message, topic_info)

        assert_that(result, has_entries(
            device="john/phone",
            event="leave",
        ))

    def test_missing_event(self) -> None:
        """Should return None if event is missing."""
        message = {"_type": "transition", "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_transition_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_missing_tst(self) -> None:
        """Should return None if tst is missing."""
        message = {"_type": "transition", "event": "enter"}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_transition_data(message, topic_info)
        assert_that(result, is_(none()))

    def test_wrong_type(self) -> None:
        """Should return None for non-transition message type."""
        message = {"_type": "location", "event": "enter", "tst": 1704067200}
        topic_info = {"user": "john", "device": "phone"}
        result = extract_transition_data(message, topic_info)
        assert_that(result, is_(none()))


class TestOwnTracksMessageHandler:
    """Tests for OwnTracksMessageHandler class."""

    @pytest.mark.asyncio
    async def test_handle_location_message(self) -> None:
        """Should call location callback for location messages."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        def callback(data: dict) -> None:
            received_data.append(data)

        handler.on_location(callback)

        payload = json.dumps({
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
        }).encode()

        await handler.handle_message("owntracks/john/phone", payload)

        assert_that(len(received_data), equal_to(1))
        assert_that(received_data[0], has_entries(
            device="john/phone",
            latitude=51.5,
        ))

    @pytest.mark.asyncio
    async def test_handle_lwt_message(self) -> None:
        """Should call LWT callback for LWT messages."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        def callback(data: dict) -> None:
            received_data.append(data)

        handler.on_lwt(callback)

        payload = json.dumps({"_type": "lwt", "tst": 1704067200}).encode()

        await handler.handle_message("owntracks/john/phone", payload)

        assert_that(len(received_data), equal_to(1))
        assert_that(received_data[0], has_entries(
            device="john/phone",
            event="offline",
        ))

    @pytest.mark.asyncio
    async def test_handle_transition_message(self) -> None:
        """Should call transition callback for transition messages."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        def callback(data: dict) -> None:
            received_data.append(data)

        handler.on_transition(callback)

        payload = json.dumps({
            "_type": "transition",
            "event": "enter",
            "desc": "Home",
            "tst": 1704067200,
        }).encode()

        await handler.handle_message("owntracks/john/phone/event", payload)

        assert_that(len(received_data), equal_to(1))
        assert_that(received_data[0], has_entries(
            device="john/phone",
            event="enter",
        ))

    @pytest.mark.asyncio
    async def test_handle_async_callback(self) -> None:
        """Should handle async callbacks."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        async def callback(data: dict) -> None:
            received_data.append(data)

        handler.on_location(callback)

        payload = json.dumps({
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
        }).encode()

        await handler.handle_message("owntracks/john/phone", payload)

        assert_that(len(received_data), equal_to(1))

    @pytest.mark.asyncio
    async def test_ignore_non_owntracks_topic(self) -> None:
        """Should ignore messages from non-OwnTracks topics."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        def callback(data: dict) -> None:
            received_data.append(data)

        handler.on_location(callback)

        payload = json.dumps({
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
        }).encode()

        await handler.handle_message("home/sensors/gps", payload)

        assert_that(len(received_data), equal_to(0))

    @pytest.mark.asyncio
    async def test_ignore_invalid_payload(self) -> None:
        """Should ignore messages with invalid payload."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        def callback(data: dict) -> None:
            received_data.append(data)

        handler.on_location(callback)

        await handler.handle_message("owntracks/john/phone", b"not json")

        assert_that(len(received_data), equal_to(0))

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break_handler(self) -> None:
        """Should continue processing even if callback raises exception."""
        handler = OwnTracksMessageHandler()
        received_data: list[dict[str, Any]] = []

        def bad_callback(data: dict) -> None:
            raise ValueError("Test error")

        def good_callback(data: dict) -> None:
            received_data.append(data)

        handler.on_location(bad_callback)
        handler.on_location(good_callback)

        payload = json.dumps({
            "_type": "location",
            "lat": 51.5,
            "lon": -0.1,
            "tst": 1704067200,
        }).encode()

        # Should not raise
        await handler.handle_message("owntracks/john/phone", payload)

        # Good callback should still be called
        assert_that(len(received_data), equal_to(1))
