"""Maintain Device.latest_location when Location rows are created."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.dispatch import receiver

from app.location_report import location_is_newer_report

if TYPE_CHECKING:
    from app.models import Location


def _latest_location_queryset(device_id: int) -> QuerySet[Location]:
    from app.models import Location

    return Location.objects.filter(device_id=device_id).order_by(
        Coalesce("owntracks_created_at", "received_at").desc(),
        "-timestamp",
        "-id",
    )


def refresh_device_latest_location(device_id: int) -> None:
    """Set device.latest_location to the row with the newest report time."""
    from app.models import Device

    latest = _latest_location_queryset(device_id).first()
    if latest is None:
        Device.objects.filter(pk=device_id).update(latest_location_id=None)
    else:
        Device.objects.filter(pk=device_id).update(latest_location_id=latest.id)


def note_location_created(location: Location) -> None:
    """Update latest_location when this row is newer than the current pointer."""
    from app.models import Device

    device = Device.objects.select_related("latest_location").filter(pk=location.device_id).first()
    if device is None:
        return

    current = device.latest_location
    if current is None or location_is_newer_report(location, current):
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
