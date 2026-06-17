"""domesti-bot integration: config helpers, pairing, and webhook log."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse, urlunparse

from django.utils import timezone

from app.pki import decrypt_private_key, encrypt_private_key

if TYPE_CHECKING:
    from app.models import DomestiBotConfig

logger = logging.getLogger(__name__)

WEBHOOK_LOG_MAX = 5
DOMESTI_BOT_REPO_URL = "https://github.com/the-hcma/domesti-bot"
TEST_LOCATION_DEFAULT_LAT = 41.194085
TEST_LOCATION_DEFAULT_LON = -73.888365
WEBHOOK_TIMEOUT_SECONDS = 5


def validate_absolute_http_url(url: str) -> str:
    """Return a trimmed absolute http(s) URL or raise ValueError."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        msg = "URL must use http or https"
        raise ValueError(msg)
    if not parsed.netloc:
        msg = "URL must be absolute"
        raise ValueError(msg)
    return cleaned


def extract_base_url_from_location_url(location_url: str) -> str:
    """Derive domesti base origin from a user location update URL."""
    parsed = urlparse(location_url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def pairing_location_urls_from_data(data: dict[str, Any]) -> tuple[str, str]:
    """Read live/test ingest URLs from a domesti-bot pair request."""
    update_url = str(data.get("user_location_update_url", ""))
    test_url = str(data.get("user_location_test_url", ""))
    return update_url, test_url


def pair_domesti_bot(
    config: DomestiBotConfig,
    *,
    api_key: str,
    user_location_test_url: str,
    user_location_update_url: str,
    domesti_base_url: str = "",
) -> None:
    """Apply pairing payload from domesti-bot and persist."""
    key = api_key.strip()
    if not key:
        msg = "api_key is required"
        raise ValueError(msg)
    location_url = validate_absolute_http_url(user_location_update_url)
    test_url = validate_absolute_http_url(user_location_test_url)
    base = domesti_base_url.strip() or extract_base_url_from_location_url(location_url)
    validate_absolute_http_url(base)

    config.set_api_key(key)
    config.user_location_test_url = test_url
    config.user_location_update_url = location_url
    config.domesti_base_url = base
    config.paired_at = timezone.now()
    config.location_updates_enabled = True
    config.save()
    log_pairing_activity(
        config,
        success=True,
        domesti_base_url=base,
        user_location_test_url=test_url,
        user_location_update_url=location_url,
    )


def apply_config_patch(config: DomestiBotConfig, data: dict[str, Any]) -> list[str]:
    """Update editable fields when paired. Returns validation error messages."""
    if not config.is_paired:
        return ["Not paired"]

    errors: list[str] = []
    if "location_updates_enabled" in data:
        config.location_updates_enabled = bool(data["location_updates_enabled"])

    if not errors:
        config.save()
    return errors


def serialize_domesti_bot_config(config: DomestiBotConfig) -> dict[str, Any]:
    """JSON-serializable config for Admin API and panel."""
    recent_webhook_log = cast(list[dict[str, Any]], config.recent_webhook_log or [])
    return {
        "is_paired": config.is_paired,
        "domesti_base_url": config.domesti_base_url,
        "user_location_test_url": config.user_location_test_url,
        "user_location_update_url": config.user_location_update_url,
        "api_key_configured": config.api_key_configured,
        "paired_at": config.paired_at.isoformat() if config.paired_at else None,
        "location_updates_enabled": config.location_updates_enabled,
        "recent_webhook_log": recent_webhook_log[:WEBHOOK_LOG_MAX],
        "domesti_bot_repo_url": DOMESTI_BOT_REPO_URL,
    }


def location_post_url_for_source(config: DomestiBotConfig, *, source: str) -> str:
    """Return the ingest URL for live GPS relay or manual test posts."""
    if source == "test":
        test_url = config.user_location_test_url.strip()
        if not test_url:
            msg = "user_location_test_url is not configured"
            raise ValueError(msg)
        return test_url
    live_url = config.user_location_update_url.strip()
    if not live_url:
        msg = "user_location_update_url is not configured"
        raise ValueError(msg)
    return live_url


def location_relay_fingerprint(
    *,
    user_id: str,
    timestamp_iso: str,
    latitude: Decimal,
    longitude: Decimal,
) -> str:
    """Stable key for a live location fix (dedupes MQTT republishes of the same packet)."""
    return f"{user_id}|{timestamp_iso}|{latitude}|{longitude}"


def already_relayed_location(config: DomestiBotConfig, *, user_id: str, fingerprint: str) -> bool:
    """Return True when this exact fix was already delivered to domesti-bot for the user."""
    last_by_user = cast(dict[str, str], config.last_relayed_location_by_user or {})
    return last_by_user.get(user_id) == fingerprint


def record_relayed_location(config: DomestiBotConfig, *, user_id: str, fingerprint: str) -> None:
    """Remember a successfully relayed live location fix for duplicate suppression."""
    last_by_user = dict(cast(dict[str, str], config.last_relayed_location_by_user or {}))
    last_by_user[user_id] = fingerprint
    config.last_relayed_location_by_user = last_by_user
    config.save(update_fields=["last_relayed_location_by_user", "updated_at"])


def build_location_webhook_payload(
    *,
    lat: float,
    lon: float,
    user_id: str,
    accuracy_m: int | None = None,
    device_id: str = "test-device",
    mqtt_user: str | None = None,
    timestamp_iso: str | None = None,
) -> dict[str, Any]:
    """Build a domesti-bot location ingest payload."""
    payload: dict[str, Any] = {
        "user_id": user_id,
        "lat": lat,
        "lon": lon,
        "timestamp": timestamp_iso or datetime.now(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "my-tracks",
        "device_id": device_id,
        "mqtt_user": mqtt_user or user_id,
    }
    if accuracy_m is not None:
        payload["accuracy_m"] = accuracy_m
    return payload


def _record_webhook_delivery(
    config: DomestiBotConfig,
    *,
    payload: dict[str, Any],
    source: str,
    post_url: str,
    success: bool,
    http_status: int | None,
    response_preview: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    """Persist a webhook attempt in server logs and the activity ring buffer."""
    entry = {
        "sent_at": timezone.now().isoformat(),
        "success": success,
        "http_status": http_status,
        "post_url": post_url,
        "user_id": payload.get("user_id"),
        "payload": payload,
        "response_preview": response_preview,
        "source": source,
        "elapsed_ms": elapsed_ms,
    }
    if success:
        logger.info(
            "[domesti-bot] %s location webhook OK url=%s user=%s http=%s elapsed_ms=%s",
            source,
            post_url,
            payload.get("user_id"),
            http_status,
            elapsed_ms,
        )
    else:
        logger.warning(
            "[domesti-bot] %s location webhook failed url=%s user=%s http=%s elapsed_ms=%s response=%s",
            source,
            post_url,
            payload.get("user_id"),
            http_status,
            elapsed_ms,
            response_preview,
        )
    append_webhook_log_entry(config, entry)
    return entry


def record_webhook_delivery_failure(
    config: DomestiBotConfig,
    *,
    payload: dict[str, Any],
    source: str,
    post_url: str,
    error_message: str,
    http_status: int | None = None,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """Record a failed webhook attempt without performing an HTTP request."""
    return _record_webhook_delivery(
        config,
        payload=payload,
        source=source,
        post_url=post_url,
        success=False,
        http_status=http_status,
        response_preview=error_message,
        elapsed_ms=elapsed_ms,
    )


def send_location_webhook(
    config: DomestiBotConfig,
    *,
    payload: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    """POST a location payload to domesti-bot and return delivery metadata."""
    post_url = location_post_url_for_source(config, source=source)
    api_key = config.get_api_key()
    if not api_key:
        msg = "api_key is not configured"
        raise ValueError(msg)

    request = urllib.request.Request(
        post_url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Domesti-Api-Key": api_key,
        },
        method="POST",
    )
    started = time.monotonic()
    status_code: int | None = None
    body_preview = ""
    success = False
    elapsed_ms = 0
    try:
        with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            body_preview = response.read(200).decode(errors="replace")
            response_status = response.status
            status_code = response_status
            success = 200 <= response_status < 300
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        status_code = exc.code
        body_preview = exc.read(200).decode(errors="replace") if exc.fp else str(exc.reason)
        success = False
    except urllib.error.URLError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        status_code = None
        body_preview = str(exc.reason)
        success = False
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        status_code = None
        body_preview = str(exc)
        success = False
        logger.exception(
            "[domesti-bot] %s location webhook error url=%s user=%s",
            source,
            post_url,
            payload.get("user_id"),
        )

    return _record_webhook_delivery(
        config,
        payload=payload,
        source=source,
        post_url=post_url,
        success=success,
        http_status=status_code,
        response_preview=body_preview,
        elapsed_ms=elapsed_ms,
    )


def log_pairing_activity(
    config: DomestiBotConfig,
    *,
    success: bool,
    domesti_base_url: str = "",
    error_message: str = "",
    user_location_test_url: str = "",
    user_location_update_url: str = "",
) -> None:
    """Record a pairing attempt or outcome in the integration activity log."""
    if success:
        preview = f"Paired with {domesti_base_url}" if domesti_base_url else "Paired successfully"
        payload: dict[str, Any] = {
            "domesti_base_url": domesti_base_url,
            "user_location_test_url": user_location_test_url,
            "user_location_update_url": user_location_update_url,
        }
    else:
        preview = error_message or "Pairing failed"
        payload = {
            "domesti_base_url": domesti_base_url,
            "user_location_test_url": user_location_test_url,
            "user_location_update_url": user_location_update_url,
        }
    append_webhook_log_entry(
        config,
        {
            "sent_at": timezone.now().isoformat(),
            "success": success,
            "http_status": 200 if success else 400,
            "user_id": None,
            "payload": payload,
            "response_preview": preview,
            "source": "pairing",
            "elapsed_ms": 0,
        },
    )
    logger.info(
        "[domesti-bot] pairing %s base_url=%s",
        "succeeded" if success else "failed",
        domesti_base_url or "(unknown)",
    )


def append_webhook_log_entry(config: DomestiBotConfig, entry: dict[str, Any]) -> None:
    """Prepend a delivery record and keep only the most recent five."""
    current_log = cast(list[dict[str, Any]], config.recent_webhook_log or [])
    log = [entry, *current_log]
    config.recent_webhook_log = log[:WEBHOOK_LOG_MAX]
    config.save(update_fields=["recent_webhook_log", "updated_at"])


def decrypt_api_key(encrypted: bytes) -> str:
    """Decrypt stored domesti-bot API key."""
    return decrypt_private_key(encrypted).decode()


def encrypt_api_key(raw: str) -> bytes:
    """Encrypt domesti-bot API key for storage."""
    return encrypt_private_key(raw.encode())
