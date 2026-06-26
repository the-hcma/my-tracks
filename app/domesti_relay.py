"""Relay saved location updates to domesti-bot when integration is paired and enabled."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from app.domesti_bot import (
    already_relayed_location,
    build_location_webhook_payload,
    format_location_timestamp_iso,
    location_metadata_for_webhook,
    location_post_url_for_source,
    location_relay_fingerprint,
    record_relayed_location,
    record_webhook_delivery_failure,
    send_location_webhook,
)
from app.models import DomestiBotConfig

if TYPE_CHECKING:
    from app.models import Location

logger = logging.getLogger(__name__)


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
        timestamp_iso = format_location_timestamp_iso(cast(datetime, location.timestamp))
        latitude = cast(Decimal, location.latitude)
        longitude = cast(Decimal, location.longitude)
        lat = float(latitude)
        lon = float(longitude)
        user_id = owner.username
        fingerprint = location_relay_fingerprint(
            user_id=user_id,
            timestamp_iso=timestamp_iso,
            latitude=latitude,
            longitude=longitude,
        )
        if already_relayed_location(config, user_id=user_id, fingerprint=fingerprint):
            logger.debug(
                "[domesti-bot] skipping duplicate live relay user=%s timestamp=%s",
                user_id,
                timestamp_iso,
            )
            return

        payload = build_location_webhook_payload(
            lat=lat,
            lon=lon,
            user_id=user_id,
            accuracy_m=int(cast(int, accuracy_raw)) if accuracy_raw is not None else None,
            connection_type=str(location.connection_type) if location.connection_type else None,
            device_id=device.device_id,
            mqtt_user=device.mqtt_user or user_id,
            timestamp_iso=timestamp_iso,
            location_metadata=location_metadata_for_webhook(location),
        )
        post_url = location_post_url_for_source(config, source="live")
        delivery = send_location_webhook(config, payload=payload, source="live")
        if delivery["success"]:
            record_relayed_location(config, user_id=user_id, fingerprint=fingerprint)
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
