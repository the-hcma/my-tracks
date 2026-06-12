"""Maintain Device.latest_location when Location rows are created."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models.signals import post_save
from django.dispatch import receiver

if TYPE_CHECKING:
    from app.models import Location


def refresh_device_latest_location(device_id: int) -> None:
    """Set device.latest_location to the row with max timestamp."""
    from app.models import Device, Location

    latest = Location.objects.filter(device_id=device_id).order_by("-timestamp", "-id").first()
    if latest is None:
        Device.objects.filter(pk=device_id).update(latest_location_id=None)
    else:
        Device.objects.filter(pk=device_id).update(latest_location_id=latest.id)


def note_location_created(location: Location) -> None:
    """Update latest_location if this row is newer than the current pointer."""
    from app.models import Device

    device = Device.objects.select_related("latest_location").filter(pk=location.device_id).first()
    if device is None:
        return

    current = device.latest_location
    if current is None:
        Device.objects.filter(pk=location.device_id).update(latest_location_id=location.id)
        return

    if location.timestamp > current.timestamp or (location.timestamp == current.timestamp and location.id > current.id):
        Device.objects.filter(pk=location.device_id).update(latest_location_id=location.id)


@receiver(post_save, sender="my_tracks.Location")
def on_location_created(
    sender: type[Location],
    instance: Location,
    created: bool,
    **kwargs: Any,
) -> None:
    """Keep Device.latest_location in sync when a new Location row is inserted."""
    del sender, kwargs
    if created:
        note_location_created(instance)
