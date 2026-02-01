"""
WebSocket consumer for real-time location updates.

Broadcasts location data to connected clients when new locations are received.
"""
import json
from typing import Any

from channels.generic.websocket import AsyncWebsocketConsumer


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

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection."""
        # Remove this channel from the locations group
        await self.channel_layer.group_discard("locations", self.channel_name)

    async def location_update(self, event: dict[str, Any]) -> None:
        """
        Receive location update from channel layer and send to WebSocket.

        Args:
            event: Dictionary containing location data
        """
        # Send location data to WebSocket client
        await self.send(text_data=json.dumps({
            'type': 'location',
            'data': event['data']
        }))
