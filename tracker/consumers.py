"""
WebSocket consumer for real-time location updates.

Broadcasts location data to connected clients when new locations are received.
"""
import json
import logging
from typing import Any

from channels.generic.websocket import AsyncWebsocketConsumer

from tracker import STARTUP_TIMESTAMP

logger = logging.getLogger(__name__)


class LocationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time location updates.

    Clients connect to receive instant notifications when new location
    data is received by the server.
    """

    def get_client_ip(self) -> str:
        """Extract client IP address from WebSocket scope."""
        # Check for X-Forwarded-For header (if behind proxy)
        headers = dict(self.scope.get('headers', []))
        x_forwarded_for = headers.get(b'x-forwarded-for')
        if x_forwarded_for:
            return x_forwarded_for.decode().split(',')[0].strip()

        # Fall back to direct client address
        client = self.scope.get('client')
        if client:
            return client[0]
        return 'unknown'

    def get_client_port(self) -> int | None:
        """Extract client port from WebSocket scope."""
        client = self.scope.get('client')
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
        # Add this channel to the locations group
        await self.channel_layer.group_add("locations", self.channel_name)
        await self.accept()

        client_addr = self.get_client_address()
        logger.info(
            f"WebSocket client connected from {client_addr}",
            extra={"channel": self.channel_name, "client_address": client_addr}
        )

        # Send welcome message with server startup timestamp
        # Clients use this to detect backend restarts and refresh the page
        await self.send(text_data=json.dumps({
            'type': 'welcome',
            'server_startup': STARTUP_TIMESTAMP
        }))

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection."""
        # Remove this channel from the locations group
        await self.channel_layer.group_discard("locations", self.channel_name)

        client_addr = self.get_client_address()
        logger.info(
            f"WebSocket client disconnected from {client_addr}",
            extra={"channel": self.channel_name, "client_address": client_addr, "close_code": close_code}
        )

    async def location_update(self, event: dict[str, Any]) -> None:
        """
        Receive location update from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing location data
        """
        location_id = event.get('data', {}).get('id')
        client_addr = self.get_client_address()
        logger.debug(
            f"Sending location update to WebSocket client at {client_addr}",
            extra={"channel": self.channel_name, "client_address": client_addr, "location_id": location_id}
        )
        # Send location data to WebSocket client
        await self.send(text_data=json.dumps({
            'type': 'location',
            'data': event['data']
        }))
