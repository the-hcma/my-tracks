"""
MQTT message handlers for OwnTracks.

This module provides handlers for processing OwnTracks MQTT messages,
including location updates, transitions, waypoints, and other message types.
"""

import inspect
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def parse_owntracks_message(payload: bytes) -> dict[str, Any] | None:
    """
    Parse an OwnTracks MQTT message payload.

    Args:
        payload: Raw bytes from MQTT message

    Returns:
        Parsed JSON dictionary, or None if parsing fails
    """
    try:
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            logger.warning("OwnTracks message is not a JSON object: %s", type(data))
            return None
        return data
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Failed to parse OwnTracks message: %s", e)
        return None


def parse_owntracks_topic(topic: str) -> dict[str, str] | None:
    """
    Parse an OwnTracks MQTT topic to extract user and device.

    OwnTracks topics follow the pattern: owntracks/{user}/{device}[/{subtopic}]

    Args:
        topic: MQTT topic string

    Returns:
        Dictionary with 'user', 'device', and optional 'subtopic' keys,
        or None if the topic doesn't match OwnTracks format
    """
    parts = topic.split("/")

    if len(parts) < 3 or parts[0] != "owntracks":
        return None

    result = {
        "user": parts[1],
        "device": parts[2],
    }

    if len(parts) > 3:
        result["subtopic"] = "/".join(parts[3:])

    return result


def extract_location_data(
    message: dict[str, Any],
    topic_info: dict[str, str],
) -> dict[str, Any] | None:
    """
    Extract location data from an OwnTracks location message.

    Args:
        message: Parsed OwnTracks message
        topic_info: Parsed topic information

    Returns:
        Dictionary with normalized location data ready for database storage,
        or None if the message is not a valid location message
    """
    msg_type = message.get("_type")

    if msg_type != "location":
        return None

    # Required fields
    lat = message.get("lat")
    lon = message.get("lon")
    tst = message.get("tst")

    if lat is None or lon is None or tst is None:
        logger.warning("Location message missing required fields: lat=%s, lon=%s, tst=%s", lat, lon, tst)
        return None

    # Convert timestamp to datetime
    try:
        timestamp = datetime.fromtimestamp(int(tst), tz=UTC)
    except (ValueError, TypeError, OSError) as e:
        logger.warning("Invalid timestamp in location message: %s - %s", tst, e)
        return None

    # Build device ID from topic info
    device_id = f"{topic_info['user']}/{topic_info['device']}"

    # Use tid (tracker ID) if available, otherwise use device name
    tracker_id = message.get("tid", topic_info["device"])

    # Extract optional fields
    location_data: dict[str, Any] = {
        "device": device_id,
        "latitude": float(lat),
        "longitude": float(lon),
        "timestamp": timestamp,
        "tracker_id": tracker_id,
    }

    # Optional fields - only add if present and valid
    if "acc" in message:
        location_data["accuracy"] = message["acc"]

    if "alt" in message:
        location_data["altitude"] = message["alt"]

    if "vel" in message:
        location_data["velocity"] = message["vel"]

    if "batt" in message:
        location_data["battery"] = message["batt"]

    if "bs" in message:
        location_data["battery_status"] = message["bs"]

    if "conn" in message:
        location_data["connection"] = message["conn"]

    if "t" in message:
        location_data["trigger"] = message["t"]

    return location_data


def extract_lwt_data(
    message: dict[str, Any],
    topic_info: dict[str, str],
) -> dict[str, Any] | None:
    """
    Extract Last Will and Testament data from an OwnTracks LWT message.

    LWT messages are published by the broker when a device disconnects.

    Args:
        message: Parsed OwnTracks message
        topic_info: Parsed topic information

    Returns:
        Dictionary with device offline information,
        or None if the message is not a valid LWT message
    """
    msg_type = message.get("_type")

    if msg_type != "lwt":
        return None

    device_id = f"{topic_info['user']}/{topic_info['device']}"

    # tst in LWT is when the device first connected
    tst = message.get("tst")
    if tst:
        try:
            connected_at = datetime.fromtimestamp(int(tst), tz=UTC)
        except (ValueError, TypeError, OSError):
            connected_at = None
    else:
        connected_at = None

    return {
        "device": device_id,
        "event": "offline",
        "connected_at": connected_at,
        "disconnected_at": datetime.now(tz=UTC),
    }


def extract_transition_data(
    message: dict[str, Any],
    topic_info: dict[str, str],
) -> dict[str, Any] | None:
    """
    Extract transition (enter/leave region) data from an OwnTracks message.

    Args:
        message: Parsed OwnTracks message
        topic_info: Parsed topic information

    Returns:
        Dictionary with transition information,
        or None if the message is not a valid transition message
    """
    msg_type = message.get("_type")

    if msg_type != "transition":
        return None

    device_id = f"{topic_info['user']}/{topic_info['device']}"

    event = message.get("event")  # 'enter' or 'leave'
    desc = message.get("desc")  # Region name
    tst = message.get("tst")

    if not event or not tst:
        logger.warning("Transition message missing required fields")
        return None

    try:
        timestamp = datetime.fromtimestamp(int(tst), tz=UTC)
    except (ValueError, TypeError, OSError) as e:
        logger.warning("Invalid timestamp in transition message: %s", e)
        return None

    transition_data: dict[str, Any] = {
        "device": device_id,
        "event": event,
        "description": desc,
        "timestamp": timestamp,
    }

    # Optional location data
    if "lat" in message and "lon" in message:
        transition_data["latitude"] = message["lat"]
        transition_data["longitude"] = message["lon"]

    if "acc" in message:
        transition_data["accuracy"] = message["acc"]

    if "t" in message:
        transition_data["trigger"] = message["t"]

    if "rid" in message:
        transition_data["region_id"] = message["rid"]

    return transition_data


# Type alias for callbacks that can be sync or async
LocationCallback = Callable[[dict[str, Any]], Any]


class OwnTracksMessageHandler:
    """
    Handler for processing OwnTracks MQTT messages.

    This class processes incoming MQTT messages and routes them
    to the appropriate handlers based on message type.
    """

    def __init__(self) -> None:
        """Initialize the message handler."""
        self._location_callbacks: list[LocationCallback] = []
        self._lwt_callbacks: list[LocationCallback] = []
        self._transition_callbacks: list[LocationCallback] = []

    def on_location(self, callback: LocationCallback) -> None:
        """Register a callback for location messages."""
        self._location_callbacks.append(callback)

    def on_lwt(self, callback: LocationCallback) -> None:
        """Register a callback for LWT (offline) messages."""
        self._lwt_callbacks.append(callback)

    def on_transition(self, callback: LocationCallback) -> None:
        """Register a callback for transition messages."""
        self._transition_callbacks.append(callback)

    async def handle_message(self, topic: str, payload: bytes) -> None:
        """
        Handle an incoming MQTT message.

        Args:
            topic: MQTT topic
            payload: Message payload bytes
        """
        # Parse topic
        topic_info = parse_owntracks_topic(topic)
        if not topic_info:
            logger.debug("Ignoring non-OwnTracks topic: %s", topic)
            return

        # Parse message
        message = parse_owntracks_message(payload)
        if not message:
            return

        msg_type = message.get("_type")
        logger.debug("Received OwnTracks %s message from %s", msg_type, topic)

        # Route to appropriate handler
        if msg_type == "location":
            await self._handle_location(message, topic_info)
        elif msg_type == "lwt":
            await self._handle_lwt(message, topic_info)
        elif msg_type == "transition":
            await self._handle_transition(message, topic_info)
        else:
            logger.debug("Unhandled OwnTracks message type: %s", msg_type)

    async def _handle_location(
        self,
        message: dict[str, Any],
        topic_info: dict[str, str],
    ) -> None:
        """Handle a location message."""
        location_data = extract_location_data(message, topic_info)
        if not location_data:
            return

        for callback in self._location_callbacks:
            try:
                result = callback(location_data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in location callback")

    async def _handle_lwt(
        self,
        message: dict[str, Any],
        topic_info: dict[str, str],
    ) -> None:
        """Handle an LWT message."""
        lwt_data = extract_lwt_data(message, topic_info)
        if not lwt_data:
            return

        for callback in self._lwt_callbacks:
            try:
                result = callback(lwt_data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in LWT callback")

    async def _handle_transition(
        self,
        message: dict[str, Any],
        topic_info: dict[str, str],
    ) -> None:
        """Handle a transition message."""
        transition_data = extract_transition_data(message, topic_info)
        if not transition_data:
            return

        for callback in self._transition_callbacks:
            try:
                result = callback(transition_data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in transition callback")
