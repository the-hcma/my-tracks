"""Relay saved location updates to domesti-bot when integration is paired and enabled."""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django.utils import timezone

from app.domesti_bot import (
    build_location_webhook_payload,
    location_post_url_for_source,
    record_webhook_delivery_failure,
    send_location_webhook,
)
from app.models import DomestiBotConfig

if TYPE_CHECKING:
    from app.models import Location

logger = logging.getLogger(__name__)


def _format_timestamp(ts: datetime) -> str:
    if timezone.is_naive(ts):
        ts = timezone.make_aware(ts, timezone.utc)
    return ts.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def relay_location_to_domesti_bot(location: Location) -> None:
    """POST a saved location to domesti-bot when live relay is enabled. Never raises."""
    device = location.device
    owner = device.owner
    if owner is None:
        return

    config: DomestiBotConfig | None = None
    payload: dict[str, Any] | None = None
    post_url = ""
    try:
        config = DomestiBotConfig.get_solo()
        if not config.is_paired or not config.location_updates_enabled:
            return

        accuracy_raw = location.accuracy
        payload = build_location_webhook_payload(
            lat=float(cast(Decimal, location.latitude)),
            lon=float(cast(Decimal, location.longitude)),
            user_id=owner.username,
            accuracy_m=int(cast(int, accuracy_raw)) if accuracy_raw is not None else None,
            device_id=device.device_id,
            mqtt_user=device.mqtt_user or owner.username,
            timestamp_iso=_format_timestamp(cast(datetime, location.timestamp)),
        )
        post_url = location_post_url_for_source(config, source="live")
        send_location_webhook(config, payload=payload, source="live")
    except Exception as exc:
        if config is not None and payload is not None:
            try:
                record_webhook_delivery_failure(
                    config,
                    payload=payload,
                    source="live",
                    post_url=post_url or location_post_url_for_source(config, source="live"),
                    error_message=str(exc),
                )
            except Exception:
                logger.exception(
                    "[domesti-bot] failed to record live relay failure in activity log device=%s owner=%s",
                    device.device_id,
                    owner.username,
                )
        logger.exception(
            "[domesti-bot] live relay failed (ignored) device=%s owner=%s",
            device.device_id,
            owner.username,
        )
