"""
WebSocket consumer for real-time location updates.

Broadcasts location data to connected clients when new locations are received.
"""

import json
import logging
from typing import Any

from channels.generic.websocket import AsyncWebsocketConsumer

from app import STARTUP_TIMESTAMP
from app.ip import get_ws_client_ip
from app.ws_broadcast import STAFF_WS_GROUP, user_ws_group

logger = logging.getLogger(__name__)


class LocationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time location updates.

    Clients connect to receive instant notifications when new location
    data is received by the server.
    """

    def get_client_ip(self) -> str:
        """Extract client IP address from WebSocket scope."""
        return get_ws_client_ip(self.scope) or "unknown"

    def get_client_port(self) -> int | None:
        """Extract client port from WebSocket scope."""
        client = self.scope.get("client")
        if client and len(client) > 1:
            return client[1]
        return None

    def get_client_address(self) -> str:
        """Get formatted client address (IP:port)."""
        ip = self.get_client_ip()
        port = self.get_client_port()
        if port:
            return f"{ip}:{port}"
        return ip

    async def connect(self) -> None:
        """Handle new WebSocket connection."""
        user = self.scope.get("user")
        if user is not None and user.is_authenticated:
            # Staff receive all device updates via the staff group only; joining
            # user_{id} as well would duplicate every owner fix on one connection.
            if user.is_staff:
                await self.channel_layer.group_add(STAFF_WS_GROUP, self.channel_name)
            else:
                await self.channel_layer.group_add(user_ws_group(user.id), self.channel_name)
        await self.accept()

        client_addr = self.get_client_address()
        logger.info(
            "[ws] Client connected from %s",
            client_addr,
            extra={"channel": self.channel_name, "client_address": client_addr},
        )

        # Send welcome message with server startup timestamp
        # Clients use this to detect backend restarts and refresh the page
        await self.send(text_data=json.dumps({"type": "welcome", "server_startup": STARTUP_TIMESTAMP}))

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection."""
        user = self.scope.get("user")
        if user is not None and user.is_authenticated:
            if user.is_staff:
                await self.channel_layer.group_discard(STAFF_WS_GROUP, self.channel_name)
            else:
                await self.channel_layer.group_discard(user_ws_group(user.id), self.channel_name)

        client_addr = self.get_client_address()
        logger.info(
            "[ws] Client disconnected from %s",
            client_addr,
            extra={"channel": self.channel_name, "client_address": client_addr, "close_code": close_code},
        )

    async def location_update(self, event: dict[str, Any]) -> None:
        """
        Receive location update from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing location data
        """
        location_id = event.get("data", {}).get("id")
        client_addr = self.get_client_address()
        logger.debug(
            "[ws] Sending location update to client at %s",
            client_addr,
            extra={"channel": self.channel_name, "client_address": client_addr, "location_id": location_id},
        )
        # Send location data to WebSocket client
        await self.send(text_data=json.dumps({"type": "location", "data": event["data"]}))

    async def device_status(self, event: dict[str, Any]) -> None:
        """
        Receive device status change from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing device status data (online/offline)
        """
        device_id = event.get("data", {}).get("device_id")
        is_online = event.get("data", {}).get("is_online")
        client_addr = self.get_client_address()
        logger.debug(
            "[ws] Sending device status to client at %s: device=%s, online=%s",
            client_addr,
            device_id,
            is_online,
        )
        await self.send(text_data=json.dumps({"type": "device_status", "data": event["data"]}))

    async def transition_event(self, event: dict[str, Any]) -> None:
        """
        Receive geofence transition event from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing transition data (device, event, region, waypoint)
        """
        await self.send(text_data=json.dumps({"type": "transition", "data": event["data"]}))

    async def waypoint_event(self, event: dict[str, Any]) -> None:
        """
        Receive waypoint sync event from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing waypoint data (device_display, new_count)
        """
        await self.send(text_data=json.dumps({"type": "waypoint_event", "data": event["data"]}))
