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

    async def connect(self) -> None:
        """Handle new WebSocket connection."""
        # Add this channel to the locations group
        await self.channel_layer.group_add("locations", self.channel_name)
        await self.accept()
        logger.info("WebSocket client connected", extra={"channel": self.channel_name})

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
        logger.info(
            "WebSocket client disconnected",
            extra={"channel": self.channel_name, "close_code": close_code}
        )

    async def location_update(self, event: dict[str, Any]) -> None:
        """
        Receive location update from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing location data
        """
        location_id = event.get('data', {}).get('id')
        logger.debug(
            "Sending location update to WebSocket client",
            extra={"channel": self.channel_name, "location_id": location_id}
        )
        # Send location data to WebSocket client
        await self.send(text_data=json.dumps({
            'type': 'location',
            'data': event['data']
        }))
