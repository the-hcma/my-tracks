"""
MQTT Command API for OwnTracks devices.

This module provides functionality to send commands to OwnTracks devices
via MQTT. Commands are published to the device's command topic.

OwnTracks command topics follow the pattern: owntracks/{user}/{device}/cmd
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CommandType(Enum):
    """
    OwnTracks command types.

    These are the standard commands supported by the OwnTracks app.
    """

    # Request current location from device
    REPORT_LOCATION = "reportLocation"

    # Set waypoints/regions on device
    SET_WAYPOINTS = "setWaypoints"

    # Clear all waypoints on device
    CLEAR_WAYPOINTS = "clearWaypoints"

    # Set configuration on device
    SET_CONFIGURATION = "setConfiguration"

    # Request device to dump its configuration
    DUMP = "dump"

    # Restart the OwnTracks app
    RESTART = "restart"

    # Custom action (app-specific)
    ACTION = "action"


@dataclass
class Command:
    """
    Represents an OwnTracks command to be sent to a device.

    Attributes:
        command_type: The type of command to send
        payload: Additional payload data for the command
        created_at: When the command was created
    """

    command_type: CommandType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def to_mqtt_payload(self) -> bytes:
        """
        Convert the command to an MQTT payload.

        Returns:
            JSON-encoded bytes ready for MQTT publish
        """
        message: dict[str, Any] = {
            "_type": "cmd",
            "action": self.command_type.value,
        }

        # Add any additional payload fields
        message.update(self.payload)

        return json.dumps(message).encode("utf-8")

    @classmethod
    def report_location(cls) -> "Command":
        """Create a command to request current location."""
        return cls(command_type=CommandType.REPORT_LOCATION)

    @classmethod
    def set_waypoints(cls, waypoints: list[dict[str, Any]]) -> "Command":
        """
        Create a command to set waypoints on the device.

        Args:
            waypoints: List of waypoint dictionaries with keys:
                - desc: Description/name of the waypoint
                - lat: Latitude
                - lon: Longitude
                - rad: Radius in meters (optional)
                - tst: Timestamp (optional)
        """
        return cls(
            command_type=CommandType.SET_WAYPOINTS,
            payload={"waypoints": waypoints},
        )

    @classmethod
    def clear_waypoints(cls) -> "Command":
        """Create a command to clear all waypoints on the device."""
        return cls(command_type=CommandType.CLEAR_WAYPOINTS)

    @classmethod
    def set_configuration(cls, config: dict[str, Any]) -> "Command":
        """
        Create a command to set device configuration.

        Args:
            config: Configuration dictionary with OwnTracks settings
        """
        return cls(
            command_type=CommandType.SET_CONFIGURATION,
            payload={"configuration": config},
        )

    @classmethod
    def dump(cls) -> "Command":
        """Create a command to request configuration dump from device."""
        return cls(command_type=CommandType.DUMP)

    @classmethod
    def action(cls, action_name: str, params: dict[str, Any] | None = None) -> "Command":
        """
        Create a custom action command.

        Args:
            action_name: Name of the custom action
            params: Optional parameters for the action
        """
        payload: dict[str, Any] = {"name": action_name}
        if params:
            payload["params"] = params
        return cls(
            command_type=CommandType.ACTION,
            payload=payload,
        )


def get_command_topic(user: str, device: str) -> str:
    """
    Get the MQTT topic for sending commands to a device.

    Args:
        user: The OwnTracks username
        device: The device identifier

    Returns:
        The command topic string: owntracks/{user}/{device}/cmd
    """
    return f"owntracks/{user}/{device}/cmd"


def parse_device_id(device_id: str) -> tuple[str, str] | None:
    """
    Parse a device ID into user and device components.

    Device IDs are typically in the format "user/device".

    Args:
        device_id: The device ID string

    Returns:
        Tuple of (user, device) or None if parsing fails
    """
    parts = device_id.split("/", 1)
    if len(parts) != 2:
        logger.warning("Invalid device ID format: %s (expected 'user/device')", device_id)
        return None
    return parts[0], parts[1]


class CommandPublisher:
    """
    Publishes commands to OwnTracks devices via MQTT.

    This class requires an MQTT client to be provided for publishing.
    It handles command serialization and topic routing.
    """

    def __init__(self, mqtt_client: Any = None) -> None:
        """
        Initialize the command publisher.

        Args:
            mqtt_client: An MQTT client with a publish method.
                        Can be set later via set_client().
        """
        self._client = mqtt_client

    def set_client(self, mqtt_client: Any) -> None:
        """Set or update the MQTT client."""
        self._client = mqtt_client

    @property
    def is_connected(self) -> bool:
        """Check if the MQTT client is available."""
        return self._client is not None

    async def send_command(
        self,
        device_id: str,
        command: Command,
        qos: int = 1,
    ) -> bool:
        """
        Send a command to a device.

        Args:
            device_id: The device ID in "user/device" format
            command: The command to send
            qos: MQTT QoS level (default: 1 for at-least-once delivery)

        Returns:
            True if the command was published successfully, False otherwise

        Raises:
            RuntimeError: If no MQTT client is configured
        """
        if self._client is None:
            raise RuntimeError("No MQTT client configured")

        # Parse device ID
        parsed = parse_device_id(device_id)
        if parsed is None:
            return False

        user, device = parsed
        topic = get_command_topic(user, device)
        payload = command.to_mqtt_payload()

        logger.info(
            "Sending %s command to device %s on topic %s",
            command.command_type.value,
            device_id,
            topic,
        )

        try:
            # amqtt broker internal publish
            if hasattr(self._client, "internal_message_broadcast"):
                await self._client.internal_message_broadcast(topic, payload, qos)
            # Standard MQTT client publish
            elif hasattr(self._client, "publish"):
                result = self._client.publish(topic, payload, qos=qos)
                if hasattr(result, "wait_for_publish"):
                    await result.wait_for_publish()
            else:
                logger.error("Unknown MQTT client type: %s", type(self._client))
                return False

            logger.debug("Command published successfully to %s", topic)
            return True

        except Exception:
            logger.exception("Failed to publish command to %s", topic)
            return False

    async def request_location(self, device_id: str) -> bool:
        """
        Request current location from a device.

        Args:
            device_id: The device ID in "user/device" format

        Returns:
            True if the command was sent successfully
        """
        return await self.send_command(device_id, Command.report_location())

    async def set_waypoints(
        self,
        device_id: str,
        waypoints: list[dict[str, Any]],
    ) -> bool:
        """
        Set waypoints on a device.

        Args:
            device_id: The device ID in "user/device" format
            waypoints: List of waypoint dictionaries

        Returns:
            True if the command was sent successfully
        """
        return await self.send_command(device_id, Command.set_waypoints(waypoints))

    async def clear_waypoints(self, device_id: str) -> bool:
        """
        Clear all waypoints on a device.

        Args:
            device_id: The device ID in "user/device" format

        Returns:
            True if the command was sent successfully
        """
        return await self.send_command(device_id, Command.clear_waypoints())
