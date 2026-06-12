"""Canonical device identifiers shared across API, WebSocket, and notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Device


def device_name_for(device: Device) -> str:
    """Return the canonical device key: ``owner/device_id`` when owned, else ``device_id``."""
    if device.owner_id and device.owner:
        return f"{device.owner.username}/{device.device_id}"
    return str(device.device_id)
