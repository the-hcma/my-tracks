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
    if payload is None:
        logger.warning("OwnTracks message payload is None")
        return None
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


def parse_owntracks_unix_timestamp(value: Any) -> datetime | None:
    """Convert an OwnTracks Unix timestamp field to a timezone-aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except ValueError, TypeError, OSError:
        return None


def _optional_int(value: Any) -> int | None:
    """Return an int when value is coercible, otherwise None."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError, TypeError:
        return None


def extract_location_optional_fields(message: dict[str, Any]) -> dict[str, Any]:
    """
    Extract optional OwnTracks location fields for database persistence.

    Maps wire-format keys (_id, created_at, t, BSSID, etc.) to Location model fields.
    """
    fields: dict[str, Any] = {}

    if "_id" in message:
        fields["owntracks_message_id"] = str(message["_id"])[:64]

    created_at = parse_owntracks_unix_timestamp(message.get("created_at"))
    if created_at is not None:
        fields["owntracks_created_at"] = created_at

    if "t" in message:
        fields["trigger"] = str(message["t"])[:10]

    if "bs" in message:
        battery_status = _optional_int(message["bs"])
        if battery_status is not None:
            fields["battery_status"] = battery_status

    if "source" in message:
        fields["fix_source"] = str(message["source"])[:20]

    if "vac" in message:
        vertical_accuracy = _optional_int(message["vac"])
        if vertical_accuracy is not None:
            fields["vertical_accuracy"] = vertical_accuracy

    if "cog" in message:
        course = _optional_int(message["cog"])
        if course is not None:
            fields["course"] = course

    if "m" in message:
        monitoring_mode = _optional_int(message["m"])
        if monitoring_mode is not None:
            fields["monitoring_mode"] = monitoring_mode

    if "BSSID" in message:
        fields["wifi_bssid"] = str(message["BSSID"])[:32]

    if "SSID" in message:
        fields["wifi_ssid"] = str(message["SSID"])[:64]

    inregions = message.get("inregions")
    if isinstance(inregions, list):
        fields["in_regions"] = inregions

    return fields


LOCATION_OPTIONAL_MODEL_FIELDS: tuple[str, ...] = (
    "owntracks_message_id",
    "owntracks_created_at",
    "trigger",
    "battery_status",
    "fix_source",
    "vertical_accuracy",
    "course",
    "monitoring_mode",
    "wifi_bssid",
    "wifi_ssid",
    "in_regions",
)


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

    # Use device name only (not user/device)
    device_id = topic_info["device"]

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

    if "conn" in message:
        location_data["connection"] = message["conn"]

    location_data.update(extract_location_optional_fields(message))

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

    device_id = topic_info["device"]

    # tst in LWT is when the device first connected
    tst = message.get("tst")
    if tst:
        try:
            connected_at = datetime.fromtimestamp(int(tst), tz=UTC)
        except ValueError, TypeError, OSError:
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

    device_id = topic_info["device"]

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


def extract_waypoint_data(
    message: dict[str, Any],
    topic_info: dict[str, str],
) -> dict[str, Any] | None:
    """
    Extract waypoint list data from an OwnTracks '_type: waypoints' message.

    Args:
        message: Parsed OwnTracks message
        topic_info: Parsed topic information

    Returns:
        Dictionary with device ID and list of waypoint dicts,
        or None if the message is not a valid waypoints message
    """
    if message.get("_type") != "waypoints":
        return None

    raw_waypoints = message.get("waypoints", [])
    if not isinstance(raw_waypoints, list):
        logger.warning("Waypoints message has non-list 'waypoints' field")
        return None

    waypoints = [
        {
            "desc": wp.get("desc", ""),
            "lat": wp.get("lat"),
            "lon": wp.get("lon"),
            "rad": wp.get("rad", 100),
        }
        for wp in raw_waypoints
        if isinstance(wp, dict) and wp.get("lat") is not None and wp.get("lon") is not None
    ]

    return {
        "device": topic_info["device"],
        "waypoints": waypoints,
    }


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
        self._waypoint_callbacks: list[LocationCallback] = []
        self._cmd_callbacks: list[LocationCallback] = []

    def on_location(self, callback: LocationCallback) -> None:
        """Register a callback for location messages."""
        self._location_callbacks.append(callback)

    def on_lwt(self, callback: LocationCallback) -> None:
        """Register a callback for LWT (offline) messages."""
        self._lwt_callbacks.append(callback)

    def on_transition(self, callback: LocationCallback) -> None:
        """Register a callback for transition messages."""
        self._transition_callbacks.append(callback)

    def on_waypoint(self, callback: LocationCallback) -> None:
        """Register a callback for incoming waypoint list messages."""
        self._waypoint_callbacks.append(callback)

    def on_cmd(self, callback: LocationCallback) -> None:
        """Register a callback for cmd messages from devices."""
        self._cmd_callbacks.append(callback)

    async def handle_message(
        self,
        topic: str,
        payload: bytes,
        *,
        client_ip: str | None = None,
        transport: str = "mqtt",
        tls_identity: str = "",
        tls_cn: str = "",
    ) -> None:
        """
        Handle an incoming MQTT message.

        Args:
            topic: MQTT topic
            payload: Message payload bytes
            client_ip: IP address of the MQTT client (from broker session)
            transport: Transport label for logging (``mqtt`` or ``mqtt-tls``)
            tls_identity: TLS identity suffix, e.g. ``" (CN=alice [AA:BB])"``
            tls_cn: Raw CN from the client's TLS certificate (Django username)
        """
        topic_info = parse_owntracks_topic(topic)
        if not topic_info:
            logger.debug("Ignoring non-OwnTracks topic: %s", topic)
            return

        message = parse_owntracks_message(payload)
        if not message:
            return

        msg_type = message.get("_type")
        logger.debug("Received OwnTracks %s message from %s", msg_type, topic)

        mqtt_user = topic_info.get("user", "")

        if msg_type == "location":
            await self._handle_location(
                message,
                topic_info,
                client_ip=client_ip,
                mqtt_user=mqtt_user,
                transport=transport,
                tls_identity=tls_identity,
                tls_cn=tls_cn,
            )
        elif msg_type == "lwt":
            await self._handle_lwt(message, topic_info, transport=transport, mqtt_user=mqtt_user)
        elif msg_type == "transition":
            await self._handle_transition(
                message,
                topic_info,
                transport=transport,
                tls_identity=tls_identity,
                mqtt_user=mqtt_user,
            )
        elif msg_type == "waypoints":
            await self._handle_waypoints(message, topic_info, transport=transport, mqtt_user=mqtt_user)
        elif msg_type == "cmd":
            await self._handle_cmd(
                message,
                topic_info,
                topic=topic,
                transport=transport,
                mqtt_user=mqtt_user,
                tls_cn=tls_cn,
            )
        else:
            logger.debug(
                "Unhandled OwnTracks message type: %s, payload: %s",
                msg_type,
                json.dumps(message, indent=2, sort_keys=True),
            )

    async def _handle_location(
        self,
        message: dict[str, Any],
        topic_info: dict[str, str],
        *,
        client_ip: str | None = None,
        mqtt_user: str = "",
        transport: str = "mqtt",
        tls_identity: str = "",
        tls_cn: str = "",
    ) -> None:
        """Handle a location message."""
        location_data = extract_location_data(message, topic_info)
        if not location_data:
            return

        if client_ip:
            location_data["client_ip"] = client_ip
        if mqtt_user:
            location_data["mqtt_user"] = mqtt_user
        if tls_cn:
            location_data["tls_cn"] = tls_cn
        location_data["transport"] = transport
        location_data["tls_identity"] = tls_identity

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
        *,
        transport: str = "mqtt",
        mqtt_user: str = "",
    ) -> None:
        """Handle an LWT message."""
        lwt_data = extract_lwt_data(message, topic_info)
        if not lwt_data:
            return

        lwt_data["transport"] = transport
        if mqtt_user:
            lwt_data["mqtt_user"] = mqtt_user

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
        *,
        transport: str = "mqtt",
        tls_identity: str = "",
        mqtt_user: str = "",
    ) -> None:
        """Handle a transition message."""
        transition_data = extract_transition_data(message, topic_info)
        if not transition_data:
            return

        transition_data["transport"] = transport
        transition_data["tls_identity"] = tls_identity
        if mqtt_user:
            transition_data["mqtt_user"] = mqtt_user

        for callback in self._transition_callbacks:
            try:
                result = callback(transition_data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in transition callback")

    async def _handle_cmd(
        self,
        message: dict[str, Any],
        topic_info: dict[str, str],
        *,
        topic: str = "",
        transport: str = "mqtt",
        mqtt_user: str = "",
        tls_cn: str = "",
    ) -> None:
        """Handle a cmd message published by a device."""
        action = message.get("action", "")
        logger.debug(
            "Received OwnTracks cmd action=%r from topic=%s, payload: %s",
            action,
            topic,
            json.dumps(message, indent=2, sort_keys=True),
        )

        cmd_data: dict[str, Any] = {
            "action": action,
            "user": topic_info["user"],
            "device": topic_info["device"],
            "topic": topic,
            "message": message,
            "transport": transport,
            "mqtt_user": mqtt_user,
            # For mqtt-tls, this is the authenticated publisher identity and is a
            # better indicator of "who sent the cmd" than the topic path.
            "tls_cn": tls_cn,
        }

        for callback in self._cmd_callbacks:
            try:
                result = callback(cmd_data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in cmd callback")

    async def _handle_waypoints(
        self,
        message: dict[str, Any],
        topic_info: dict[str, str],
        *,
        transport: str = "mqtt",
        mqtt_user: str = "",
    ) -> None:
        """Handle an incoming waypoint list message from a device."""
        waypoint_data = extract_waypoint_data(message, topic_info)
        if not waypoint_data:
            return

        waypoint_data["transport"] = transport
        if mqtt_user:
            waypoint_data["mqtt_user"] = mqtt_user

        for callback in self._waypoint_callbacks:
            try:
                result = callback(waypoint_data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Error in waypoint callback")
