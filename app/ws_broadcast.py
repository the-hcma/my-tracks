"""
WebSocket group helpers for per-user location and device status delivery.

Location updates are sent to the device owner, users with an explicit
DeviceShare grant, and staff (``staff`` group).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import Device

logger = logging.getLogger(__name__)

STAFF_WS_GROUP = "staff"


def user_ws_group(user_id: int) -> str:
    return f"user_{user_id}"


def device_location_ws_groups(device: Device) -> list[str]:
    """Return channel-layer group names that should receive updates for a device."""
    from app.models import DeviceShare

    groups: set[str] = {STAFF_WS_GROUP}
    if device.owner_id:
        groups.add(user_ws_group(device.owner_id))
    shared_with_ids = DeviceShare.objects.filter(device=device).values_list("shared_with_id", flat=True)
    for shared_with_id in shared_with_ids:
        groups.add(user_ws_group(shared_with_id))
    return sorted(groups)


async def broadcast_to_groups(
    channel_layer: Any,
    groups: list[str],
    *,
    message_type: str,
    data: dict[str, Any],
) -> None:
    """Send the same payload to each WebSocket group."""
    for group in groups:
        await channel_layer.group_send(
            group,
            {
                "type": message_type,
                "data": data,
            },
        )


async def broadcast_device_event(
    channel_layer: Any,
    device: Device,
    *,
    message_type: str,
    data: dict[str, Any],
) -> None:
    from asgiref.sync import sync_to_async

    # thread_sensitive=False: callers (e.g. MQTT plugin) run outside Django/ASGI request lifecycle.
    groups = await sync_to_async(device_location_ws_groups, thread_sensitive=False)(device)
    await broadcast_to_groups(channel_layer, groups, message_type=message_type, data=data)
    logger.info(
        "[ws] Broadcast %s for device %s to groups %s",
        message_type,
        device.device_id,
        groups,
    )


def broadcast_device_event_sync(
    device: Device,
    *,
    message_type: str,
    data: dict[str, Any],
) -> None:
    """Synchronous wrapper for HTTP views and other sync callers."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("[ws] WebSocket broadcast skipped: no channel layer")
        return
    async_to_sync(broadcast_device_event)(
        channel_layer,
        device,
        message_type=message_type,
        data=data,
    )
