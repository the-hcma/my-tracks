"""In-process FIFO queue for domesti-bot reportLocation requests."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from django.utils import timezone
from rest_framework import status

from app.domesti_bot import format_location_timestamp_iso
from app.domesti_location_request import (
    LocationRequestBatchResult,
    LocationRequestError,
    LocationRequestResult,
    cooldown_until_for_device,
    cooldown_until_for_user,
    device_cooldown_seconds,
    device_for_user,
    location_request_rate_limits,
    mqtt_device_id_for_device,
    owned_devices_for_user,
    request_all_devices_location,
    request_single_device_location,
    user_cooldown_seconds,
    user_cooldown_seconds_for_reason,
)
from app.models import DomestiBotConfig

logger = logging.getLogger(__name__)

LocationRequestJobKind = Literal["batch", "device"]


@dataclass(frozen=True)
class LocationRequestJob:
    """Work item processed sequentially by the location-request worker."""

    kind: LocationRequestJobKind
    user_id: str
    reason: str
    rule_id: str | None = None
    geofence_id: str | None = None
    device_id: str | None = None
    mqtt_device_id: str | None = None


class _LocationRequestQueueState:
    """Holder for queue worker lifecycle (no module-level mutable loose variables)."""

    def __init__(self) -> None:
        # FIFO of LocationRequestJob instances; the daemon worker thread blocks on
        # jobs.get() and runs one job at a time (see start_location_request_worker).
        self.jobs: queue.Queue[LocationRequestJob | None] = queue.Queue()
        self.inline_processing = False
        self.thread: threading.Thread | None = None
        self.started = False
        self.pending_user_requested_at: dict[str, datetime] = {}
        self.pending_user_in_flight: set[str] = set()
        self.pending_device_cooldown_until: dict[str, datetime] = {}
        self.pending_device_in_flight: set[str] = set()


_state = _LocationRequestQueueState()
_domesti_location_request_lock = threading.RLock()


def set_inline_processing(enabled: bool) -> None:
    """Run queued jobs on the calling thread (used by tests)."""
    _state.inline_processing = enabled


def start_location_request_worker() -> None:
    """Start the background worker once per process."""
    if _state.started or _state.inline_processing:
        return
    _state.started = True
    _state.thread = threading.Thread(
        target=_worker_loop,
        name="domesti-location-request",
        daemon=True,
    )
    _state.thread.start()


def stop_location_request_worker() -> None:
    """Signal the worker to exit (tests only)."""
    if not _state.started:
        return
    _state.jobs.put(None)
    if _state.thread is not None:
        _state.thread.join(timeout=5)
        if _state.thread.is_alive():
            logger.warning("domesti-bot location request worker did not stop within 5s")
            return
    _state.started = False
    _state.thread = None


def drain_location_request_queue(*, timeout_s: float = 5.0) -> None:
    """Block until queued jobs finish (tests only)."""
    if _state.inline_processing:
        return
    deadline = time.monotonic() + timeout_s
    while _state.jobs.unfinished_tasks > 0:
        if time.monotonic() >= deadline:
            msg = (
                f"Timed out after {timeout_s}s waiting for "
                f"{_state.jobs.unfinished_tasks} domesti-bot location request job(s)"
            )
            raise TimeoutError(msg)
        time.sleep(0.01)


def enqueue_batch_location_request(
    config: DomestiBotConfig,
    *,
    user_id: str,
    reason: str,
    rule_id: str | None = None,
    geofence_id: str | None = None,
) -> LocationRequestBatchResult:
    """Validate, enqueue (or run inline), and return the HTTP 202 payload."""
    from app.domesti_location_request import _active_user, _validate_reason

    _validate_reason(reason)
    user = _active_user(user_id)
    cleaned_user_id = str(user.username)
    devices = owned_devices_for_user(user)
    if not devices:
        raise LocationRequestError(
            f"No owned devices for user_id: {cleaned_user_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    job = LocationRequestJob(
        kind="batch",
        user_id=cleaned_user_id,
        reason=reason,
        rule_id=rule_id,
        geofence_id=geofence_id,
    )
    if _state.inline_processing:
        with _domesti_location_request_lock:
            _reject_if_user_cooldown_active(config, cleaned_user_id, reason=reason)
        return _execute_batch_job(config, job)

    mqtt_device_ids = [mqtt_device_id_for_device(device) for device in devices]
    requested_at = timezone.now()
    with _domesti_location_request_lock:
        _reject_if_user_cooldown_active(config, cleaned_user_id, reason=reason)
        _state.pending_user_requested_at[cleaned_user_id] = requested_at
        _state.pending_user_in_flight.add(cleaned_user_id)
        # Hand off to the daemon worker; HTTP returns 202 without waiting for MQTT.
        _state.jobs.put(job)
    cooldown_until = requested_at + timedelta(
        seconds=user_cooldown_seconds_for_reason(config, reason),
    )
    return LocationRequestBatchResult(
        user_id=cleaned_user_id,
        device_ids=mqtt_device_ids,
        requested_at=requested_at,
        cooldown_until=cooldown_until,
        reason=reason,
    )


def enqueue_device_location_request(
    config: DomestiBotConfig,
    *,
    user_id: str,
    device_id: str,
    reason: str,
    rule_id: str | None = None,
    geofence_id: str | None = None,
) -> LocationRequestResult:
    """Validate, enqueue (or run inline), and return the HTTP 202 payload."""
    from app.domesti_location_request import _active_user, _validate_reason

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

    job = LocationRequestJob(
        kind="device",
        user_id=cleaned_user_id,
        reason=reason,
        rule_id=rule_id,
        geofence_id=geofence_id,
        device_id=str(device.device_id),
        mqtt_device_id=mqtt_device_id,
    )
    if _state.inline_processing:
        with _domesti_location_request_lock:
            _reject_if_device_cooldown_active(config, mqtt_device_id)
            _reject_if_user_batch_in_flight(config, cleaned_user_id)
        return _execute_device_job(config, job)

    requested_at = timezone.now()
    cooldown_until = requested_at + timedelta(seconds=device_cooldown_seconds(config))
    with _domesti_location_request_lock:
        _reject_if_device_cooldown_active(config, mqtt_device_id)
        _reject_if_user_batch_in_flight(config, cleaned_user_id)
        _state.pending_device_cooldown_until[mqtt_device_id] = cooldown_until
        _state.pending_device_in_flight.add(mqtt_device_id)
        # Hand off to the daemon worker; HTTP returns 202 without waiting for MQTT.
        _state.jobs.put(job)
    return LocationRequestResult(
        user_id=cleaned_user_id,
        device_id=mqtt_device_id,
        requested_at=requested_at,
        cooldown_until=cooldown_until,
        reason=reason,
    )


def _reject_if_user_cooldown_active(
    config: DomestiBotConfig,
    user_id: str,
    *,
    reason: str,
) -> None:
    now = timezone.now()
    if user_id in _state.pending_user_in_flight:
        pending_requested_at = _state.pending_user_requested_at[user_id]
        pending_until = pending_requested_at + timedelta(
            seconds=user_cooldown_seconds_for_reason(config, reason),
        )
        active_cooldown = pending_until if pending_until > now else now + timedelta(seconds=1)
    else:
        active_cooldown = cooldown_until_for_user(config, user_id, reason=reason)
    if active_cooldown is None:
        return
    extra: dict[str, object] = {
        "cooldown_until": format_location_timestamp_iso(active_cooldown),
    }
    extra.update(location_request_rate_limits(config))
    raise LocationRequestError(
        "Location request cooldown active",
        status_code=status.HTTP_409_CONFLICT,
        extra=extra,
    )


def _reject_if_user_batch_in_flight(
    config: DomestiBotConfig,
    user_id: str,
) -> None:
    if user_id not in _state.pending_user_in_flight:
        return
    pending_requested_at = _state.pending_user_requested_at.get(user_id)
    if pending_requested_at is None:
        raise LocationRequestError(
            "Location request already in progress for user",
            status_code=status.HTTP_409_CONFLICT,
        )
    cooldown_until = pending_requested_at + timedelta(
        seconds=user_cooldown_seconds(config),
    )
    extra: dict[str, object] = {
        "cooldown_until": format_location_timestamp_iso(cooldown_until),
    }
    extra.update(location_request_rate_limits(config))
    raise LocationRequestError(
        "Location request cooldown active",
        status_code=status.HTTP_409_CONFLICT,
        extra=extra,
    )


def _reject_if_device_cooldown_active(
    config: DomestiBotConfig,
    mqtt_device_id: str,
) -> None:
    now = timezone.now()
    if mqtt_device_id in _state.pending_device_in_flight:
        pending_until = _state.pending_device_cooldown_until.get(mqtt_device_id)
        if pending_until is None or pending_until <= now:
            pending_until = now + timedelta(seconds=1)
        active_cooldown = pending_until
    else:
        active_cooldown = cooldown_until_for_device(config, mqtt_device_id)
    if active_cooldown is None:
        return
    raise LocationRequestError(
        "Device location request cooldown active",
        status_code=status.HTTP_409_CONFLICT,
        extra={"cooldown_until": format_location_timestamp_iso(active_cooldown)},
    )


def _clear_pending_for_job(job: LocationRequestJob) -> None:
    with _domesti_location_request_lock:
        if job.kind == "batch":
            _state.pending_user_requested_at.pop(job.user_id, None)
            _state.pending_user_in_flight.discard(job.user_id)
        elif job.mqtt_device_id is not None:
            _state.pending_device_cooldown_until.pop(job.mqtt_device_id, None)
            _state.pending_device_in_flight.discard(job.mqtt_device_id)


def _worker_loop() -> None:
    from django.db import close_old_connections

    while True:
        close_old_connections()
        job = _state.jobs.get()
        try:
            if job is None:
                return
            if job.kind == "batch":
                _process_batch_job(job)
            else:
                _process_device_job(job)
        except LocationRequestError as exc:
            logger.warning(
                "[domesti-bot] queued location request failed user=%s reason=%s detail=%s",
                job.user_id if job is not None else "",
                job.reason if job is not None else "",
                exc.detail,
            )
        except Exception:
            logger.exception(
                "[domesti-bot] queued location request crashed user=%s reason=%s",
                job.user_id if job is not None else "",
                job.reason if job is not None else "",
            )
        finally:
            if job is not None:
                _clear_pending_for_job(job)
            _state.jobs.task_done()


def _process_batch_job(job: LocationRequestJob) -> LocationRequestBatchResult:
    config = DomestiBotConfig.get_solo()
    return _execute_batch_job(config, job)


def _process_device_job(job: LocationRequestJob) -> LocationRequestResult:
    config = DomestiBotConfig.get_solo()
    return _execute_device_job(config, job)


def domesti_location_request_lock() -> threading.RLock:
    """Process-wide lock serializing domesti-bot location request HTTP handling."""
    return _domesti_location_request_lock


def _execute_batch_job(
    config: DomestiBotConfig,
    job: LocationRequestJob,
) -> LocationRequestBatchResult:
    return request_all_devices_location(
        config,
        user_id=job.user_id,
        reason=job.reason,
        rule_id=job.rule_id,
        geofence_id=job.geofence_id,
    )


def _execute_device_job(
    config: DomestiBotConfig,
    job: LocationRequestJob,
) -> LocationRequestResult:
    if job.device_id is None:
        msg = "Expected device_id on device location request job, got None"
        raise LocationRequestError(msg, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return request_single_device_location(
        config,
        user_id=job.user_id,
        device_id=job.device_id,
        reason=job.reason,
        rule_id=job.rule_id,
        geofence_id=job.geofence_id,
    )
