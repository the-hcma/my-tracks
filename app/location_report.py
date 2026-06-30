"""Report vs fix time for OwnTracks location rows.

``tst`` (``Location.timestamp``) is when the GPS fix occurred on the device.
``created_at`` / ``received_at`` reflect when the message was built or ingested.
Live activity and last-known use report time for ordering; fix time stays on the row
for map geography and stale-position labeling.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from app.models import Location


def format_location_datetime_for_log(ts: datetime) -> str:
    """Format a location timestamp for server log lines (local or UTC per LOG_UTC)."""
    if timezone.is_naive(ts):
        ts = timezone.make_aware(ts, UTC)
    if os.environ.get("LOG_UTC"):
        return ts.astimezone(UTC).strftime("%Y%m%d-%H:%M:%S")
    return ts.astimezone(settings.SYSTEM_TIMEZONE).strftime("%Y%m%d-%H:%M:%S")


def location_report_log_fragment(*, reported_at: datetime, fix_at: datetime) -> str:
    """Comma-prefixed report vs fix times for Location saved log lines."""
    return (
        f", report_at={format_location_datetime_for_log(reported_at)}"
        f", fix_at={format_location_datetime_for_log(fix_at)}"
    )


def location_report_log_fragment_from_location(location: Location) -> str:
    """Build report/fix log fragment from a saved Location row."""
    return location_report_log_fragment(
        reported_at=location_reported_at(location),
        fix_at=cast(datetime, location.timestamp),
    )


def location_report_log_fragment_from_mapping(data: dict[str, Any]) -> str:
    """Build report/fix log fragment from serializer output."""
    reported_unix = data.get("reported_at_unix")
    fix_unix = data.get("timestamp_unix")
    if reported_unix is None or fix_unix is None:
        return ""
    return location_report_log_fragment(
        reported_at=datetime.fromtimestamp(int(reported_unix), tz=UTC),
        fix_at=datetime.fromtimestamp(int(fix_unix), tz=UTC),
    )


def location_reported_at(location: Location) -> datetime:
    """When this location was reported (OwnTracks ``created_at`` or server ingest)."""
    if location.owntracks_created_at is not None:
        return cast(datetime, location.owntracks_created_at)
    return cast(datetime, location.received_at)


def location_reported_at_unix(location: Location) -> int:
    return int(location_reported_at(location).timestamp())


def location_fix_age_seconds(location: Location) -> int:
    """Seconds between GPS fix time and report time (0 when fix is newer than report)."""
    reported = location_reported_at(location)
    fix_at = cast(datetime, location.timestamp)
    delta = (reported - fix_at).total_seconds()
    return max(0, int(delta))


def location_report_sort_key(location: Location) -> tuple[datetime, datetime, int]:
    """Sort key for newest report: reported_at, then fix time, then row id."""
    return (location_reported_at(location), cast(datetime, location.timestamp), location.id)


def location_is_newer_report(location: Location, than: Location) -> bool:
    """True when ``location`` should replace ``than`` as the device's latest row."""
    return location_report_sort_key(location) > location_report_sort_key(than)
