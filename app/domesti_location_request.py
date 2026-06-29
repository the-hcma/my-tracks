"""domesti-bot on-demand reportLocation requests via relay API key."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.db.models import F
from django.db.transaction import atomic as db_atomic
from django.utils import timezone
from rest_framework import status

from app.apps import get_mqtt_broker
from app.domesti_bot import format_location_timestamp_iso
from app.models import Device, DomestiBotConfig
from app.mqtt.commands import CommandPublisher

logger = logging.getLogger(__name__)

# Per-user cooldown (default 30 s, operator-tunable in Admin Panel): applies to POST
# .../users/{id}/request-location/ (all owned devices). Limits how often domesti-bot can
# fan out reportLocation to every device for one user; echoed in admin config GET and 202s.
LOCATION_REQUEST_USER_COOLDOWN_SECONDS_DEFAULT = 30

# Per-device cooldown (default 2 s, operator-tunable in Admin Panel): applies to POST
# .../users/{id}/devices/{device_id}/request-location/. Lets domesti-bot poll individual
# devices without hammering the same phone; echoed in admin config GET and 202 responses.
LOCATION_REQUEST_DEVICE_COOLDOWN_SECONDS_DEFAULT = 2

# Shorter per-user cooldown for geofence approach monitoring (batch user endpoint only).
LOCATION_REQUEST_APPROACH_MONITORING_USER_COOLDOWN_SECONDS = 5

VALID_LOCATION_REQUEST_REASONS = frozenset(
    {
        "accuracy_streak",
        "deferred_edge",
        "boundary_proximity",
        "stale_watchdog",
        "approach_monitoring",
    }
)


@dataclass(frozen=True)
class LocationRequestResult:
    """Successful single-device reportLocation request metadata."""

    user_id: str
    device_id: str
    requested_at: datetime
    cooldown_until: datetime
    reason: str


@dataclass(frozen=True)
class LocationRequestBatchResult:
    """Successful all-devices reportLocation request metadata."""

    user_id: str
    device_ids: list[str]
    requested_at: datetime
    cooldown_until: datetime
    reason: str


class LocationRequestError(Exception):
    """Raised when a domesti-bot location request cannot be fulfilled."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.extra = extra or {}


def location_request_rate_limits(config: DomestiBotConfig) -> dict[str, Any]:
    """Rate-limit metadata for domesti-bot (admin config GET, pair, and 202 responses)."""
    return {
        "user_cooldown_seconds": user_cooldown_seconds(config),
        "device_cooldown_seconds": device_cooldown_seconds(config),
        "user_cooldown_seconds_by_reason": user_cooldown_seconds_by_reason(config),
    }


def user_cooldown_seconds_by_reason(config: DomestiBotConfig) -> dict[str, int]:
    """Per-reason overrides for the batch user request-location endpoint."""
    del config
    return {
        "approach_monitoring": LOCATION_REQUEST_APPROACH_MONITORING_USER_COOLDOWN_SECONDS,
    }


def user_cooldown_seconds_for_reason(config: DomestiBotConfig, reason: str) -> int:
    """Minimum seconds since the last batch request before ``reason`` may run again."""
    by_reason = user_cooldown_seconds_by_reason(config)
    return by_reason.get(reason, user_cooldown_seconds(config))


def user_cooldown_seconds(config: DomestiBotConfig) -> int:
    """Configured per-user minimum interval between all-device reportLocation requests."""
    return cast(int, config.location_request_user_cooldown_seconds)


def device_cooldown_seconds(config: DomestiBotConfig) -> int:
    """Configured per-device minimum interval between reportLocation requests."""
    return cast(int, config.location_request_device_cooldown_seconds)


def mqtt_device_id_for_device(device: Device) -> str:
    """Build the MQTT topic device id for an owned device."""
    mqtt_user = device.mqtt_user or device.owner.username
    return f"{mqtt_user}/{device.device_id}"


def owned_devices_for_user(user: User) -> list[Device]:
    """Return all owned devices for ``user``, newest location activity first."""
    return list(
        Device.objects.filter(owner=user).order_by(
            F("last_location_at").desc(nulls_last=True),
            "-last_seen",
        )
    )


def device_for_user(user: User, device_id: str) -> Device | None:
    """Return an owned device by bare ``device_id`` (strips ``mqtt_user/`` prefix if present)."""
    bare_device_id = device_id.strip()
    if "/" in bare_device_id:
        _, bare_device_id = bare_device_id.split("/", 1)
    return Device.objects.filter(owner=user, device_id=bare_device_id).first()


def cooldown_until_for_user(
    config: DomestiBotConfig,
    user_id: str,
    *,
    reason: str,
) -> datetime | None:
    """Return active per-user cooldown end time for ``reason``, if any."""
    last_by_user = cast(dict[str, str], config.last_location_request_at_by_user or {})
    last_raw = last_by_user.get(user_id)
    if not last_raw:
        return None
    try:
        last_requested = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(last_requested):
        last_requested = timezone.make_aware(last_requested, UTC)
    cooldown_seconds = user_cooldown_seconds_for_reason(config, reason)
    cooldown_end = last_requested + timedelta(seconds=cooldown_seconds)
    now = timezone.now()
    if cooldown_end <= now:
        return None
    return cooldown_end


def cooldown_until_for_device(config: DomestiBotConfig, mqtt_device_id: str) -> datetime | None:
    """Return active per-device cooldown end time, if any."""
    last_by_device = cast(dict[str, str], config.last_location_request_at_by_device or {})
    last_raw = last_by_device.get(mqtt_device_id)
    if not last_raw:
        return None
    try:
        last_requested = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(last_requested):
        last_requested = timezone.make_aware(last_requested, UTC)
    cooldown_end = last_requested + timedelta(seconds=device_cooldown_seconds(config))
    now = timezone.now()
    if cooldown_end <= now:
        return None
    return cooldown_end


def record_location_request(config: DomestiBotConfig, *, user_id: str, requested_at: datetime) -> None:
    """Persist the latest per-user request timestamp."""
    last_by_user = dict(cast(dict[str, str], config.last_location_request_at_by_user or {}))
    last_by_user[user_id] = format_location_timestamp_iso(requested_at)
    config.last_location_request_at_by_user = last_by_user
    config.save(update_fields=["last_location_request_at_by_user", "updated_at"])


def record_device_location_request(
    config: DomestiBotConfig,
    *,
    mqtt_device_id: str,
    requested_at: datetime,
) -> None:
    """Persist the latest per-device request timestamp."""
    last_by_device = dict(cast(dict[str, str], config.last_location_request_at_by_device or {}))
    last_by_device[mqtt_device_id] = format_location_timestamp_iso(requested_at)
    config.last_location_request_at_by_device = last_by_device
    config.save(update_fields=["last_location_request_at_by_device", "updated_at"])


def clear_location_request(
    config: DomestiBotConfig,
    *,
    user_id: str,
    requested_at: datetime,
) -> None:
    """Remove a per-user reservation when publish fails (only if still ours)."""
    last_by_user = dict(cast(dict[str, str], config.last_location_request_at_by_user or {}))
    current = last_by_user.get(user_id)
    if current is None:
        return
    if current != format_location_timestamp_iso(requested_at):
        return
    del last_by_user[user_id]
    config.last_location_request_at_by_user = last_by_user
    config.save(update_fields=["last_location_request_at_by_user", "updated_at"])


def clear_device_location_request(
    config: DomestiBotConfig,
    *,
    mqtt_device_id: str,
    requested_at: datetime,
) -> None:
    """Remove a per-device reservation when publish fails (only if still ours)."""
    last_by_device = dict(cast(dict[str, str], config.last_location_request_at_by_device or {}))
    current = last_by_device.get(mqtt_device_id)
    if current is None:
        return
    if current != format_location_timestamp_iso(requested_at):
        return
    del last_by_device[mqtt_device_id]
    config.last_location_request_at_by_device = last_by_device
    config.save(update_fields=["last_location_request_at_by_device", "updated_at"])


@contextmanager
def _locked_domesti_config(config: DomestiBotConfig) -> Iterator[DomestiBotConfig]:
    with db_atomic():  # type: ignore[reportGeneralTypeIssues]
        yield DomestiBotConfig.objects.select_for_update().get(pk=config.pk)


def _command_publisher() -> CommandPublisher:
    broker = get_mqtt_broker()
    if broker is not None and broker.is_running and broker.amqtt_broker is not None:
        return CommandPublisher(mqtt_client=broker.amqtt_broker)
    return CommandPublisher()


def _validate_reason(reason: str) -> None:
    if reason not in VALID_LOCATION_REQUEST_REASONS:
        msg = f"Expected reason in {sorted(VALID_LOCATION_REQUEST_REASONS)}, got {reason!r}"
        raise LocationRequestError(msg, status_code=status.HTTP_400_BAD_REQUEST)


def _active_user(user_id: str) -> User:
    cleaned_user_id = user_id.strip()
    user = User.objects.filter(username=cleaned_user_id, is_active=True).first()
    if user is None:
        raise LocationRequestError(
            f"Unknown or inactive user_id: {cleaned_user_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return user


def _reserve_user_cooldown(
    config: DomestiBotConfig,
    *,
    user_id: str,
    reason: str,
) -> datetime:
    with _locked_domesti_config(config) as locked_config:
        active_cooldown = cooldown_until_for_user(locked_config, user_id, reason=reason)
        if active_cooldown is not None:
            extra: dict[str, Any] = {
                "cooldown_until": format_location_timestamp_iso(active_cooldown),
            }
            extra.update(location_request_rate_limits(locked_config))
            raise LocationRequestError(
                "Location request cooldown active",
                status_code=status.HTTP_409_CONFLICT,
                extra=extra,
            )
        requested_at = timezone.now()
        record_location_request(locked_config, user_id=user_id, requested_at=requested_at)
        return requested_at


def _reserve_device_cooldown(
    config: DomestiBotConfig,
    *,
    mqtt_device_id: str,
) -> datetime:
    with _locked_domesti_config(config) as locked_config:
        active_cooldown = cooldown_until_for_device(locked_config, mqtt_device_id)
        if active_cooldown is not None:
            raise LocationRequestError(
                "Device location request cooldown active",
                status_code=status.HTTP_409_CONFLICT,
                extra={"cooldown_until": format_location_timestamp_iso(active_cooldown)},
            )
        requested_at = timezone.now()
        record_device_location_request(
            locked_config,
            mqtt_device_id=mqtt_device_id,
            requested_at=requested_at,
        )
        return requested_at


def _publish_report_location(*, user_id: str, mqtt_device_id: str, reason: str) -> None:
    publisher = _command_publisher()
    try:
        success = async_to_sync(publisher.request_location)(
            mqtt_device_id,
            owner=user_id,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "No MQTT client configured":
            detail = "MQTT broker unavailable"
        raise LocationRequestError(
            detail,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    if not success:
        raise LocationRequestError(
            "Failed to publish reportLocation command",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    _, bare_device_id = mqtt_device_id.split("/", 1)
    logger.info(
        "[domesti-bot] reportLocation request user=%s reason=%s device=%s",
        user_id,
        reason,
        bare_device_id,
    )


def request_all_devices_location(
    config: DomestiBotConfig,
    *,
    user_id: str,
    reason: str,
    rule_id: str | None = None,
    geofence_id: str | None = None,
) -> LocationRequestBatchResult:
    """Queue reportLocation on every device owned by ``user_id``."""
    del rule_id, geofence_id

    _validate_reason(reason)
    user = _active_user(user_id)
    cleaned_user_id = str(user.username)

    devices = owned_devices_for_user(user)
    if not devices:
        raise LocationRequestError(
            f"No owned devices for user_id: {cleaned_user_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    mqtt_device_ids = [mqtt_device_id_for_device(device) for device in devices]
    requested_at = _reserve_user_cooldown(config, user_id=cleaned_user_id, reason=reason)

    try:
        for mqtt_device_id in mqtt_device_ids:
            _publish_report_location(
                user_id=cleaned_user_id,
                mqtt_device_id=mqtt_device_id,
                reason=reason,
            )
            record_device_location_request(
                config,
                mqtt_device_id=mqtt_device_id,
                requested_at=timezone.now(),
            )
    except LocationRequestError:
        with _locked_domesti_config(config) as locked_config:
            clear_location_request(
                locked_config,
                user_id=cleaned_user_id,
                requested_at=requested_at,
            )
        raise

    cooldown_until = requested_at + timedelta(seconds=user_cooldown_seconds_for_reason(config, reason))
    return LocationRequestBatchResult(
        user_id=cleaned_user_id,
        device_ids=mqtt_device_ids,
        requested_at=requested_at,
        cooldown_until=cooldown_until,
        reason=reason,
    )


def request_single_device_location(
    config: DomestiBotConfig,
    *,
    user_id: str,
    device_id: str,
    reason: str,
    rule_id: str | None = None,
    geofence_id: str | None = None,
) -> LocationRequestResult:
    """Queue reportLocation for one owned device."""
    del rule_id, geofence_id

    _validate_reason(reason)
    user = _active_user(user_id)
    cleaned_user_id = str(user.username)

    device = device_for_user(user, device_id)
    if device is None:
        raise LocationRequestError(
            f"Unknown device for user_id: {cleaned_user_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    mqtt_device_id = mqtt_device_id_for_device(device)
    requested_at = _reserve_device_cooldown(config, mqtt_device_id=mqtt_device_id)
    try:
        _publish_report_location(
            user_id=cleaned_user_id,
            mqtt_device_id=mqtt_device_id,
            reason=reason,
        )
    except LocationRequestError:
        with _locked_domesti_config(config) as locked_config:
            clear_device_location_request(
                locked_config,
                mqtt_device_id=mqtt_device_id,
                requested_at=requested_at,
            )
        raise

    cooldown_until = requested_at + timedelta(seconds=device_cooldown_seconds(config))
    return LocationRequestResult(
        user_id=cleaned_user_id,
        device_id=mqtt_device_id,
        requested_at=requested_at,
        cooldown_until=cooldown_until,
        reason=reason,
    )


def serialize_location_request_result(
    result: LocationRequestResult,
    *,
    config: DomestiBotConfig,
) -> dict[str, Any]:
    """JSON body for a successful single-device request-location response."""
    body: dict[str, Any] = {
        "user_id": result.user_id,
        "device_id": result.device_id,
        "requested_at": format_location_timestamp_iso(result.requested_at),
        "cooldown_until": format_location_timestamp_iso(result.cooldown_until),
        "reason": result.reason,
    }
    body.update(location_request_rate_limits(config))
    return body


def serialize_location_request_batch_result(
    result: LocationRequestBatchResult,
    *,
    config: DomestiBotConfig,
) -> dict[str, Any]:
    """JSON body for a successful all-devices request-location response."""
    body: dict[str, Any] = {
        "user_id": result.user_id,
        "device_ids": result.device_ids,
        "requested_at": format_location_timestamp_iso(result.requested_at),
        "cooldown_until": format_location_timestamp_iso(result.cooldown_until),
        "reason": result.reason,
    }
    body.update(location_request_rate_limits(config))
    return body
