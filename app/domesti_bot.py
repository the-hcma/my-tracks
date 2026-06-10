"""domesti-bot integration: config helpers, pairing, and webhook log."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timezone as dt_timezone
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
    """Derive domesti base origin from a participant location update URL."""
    parsed = urlparse(location_url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def pair_domesti_bot(
    config: DomestiBotConfig,
    *,
    api_key: str,
    participant_location_update_url: str,
    participant_location_test_url: str,
    domesti_base_url: str = "",
) -> None:
    """Apply pairing payload from domesti-bot and persist."""
    key = api_key.strip()
    if not key:
        msg = "api_key is required"
        raise ValueError(msg)
    location_url = validate_absolute_http_url(participant_location_update_url)
    test_url = validate_absolute_http_url(participant_location_test_url)
    base = domesti_base_url.strip() or extract_base_url_from_location_url(location_url)
    validate_absolute_http_url(base)

    config.set_api_key(key)
    config.participant_location_update_url = location_url
    config.participant_location_test_url = test_url
    config.domesti_base_url = base
    config.paired_at = timezone.now()
    config.location_updates_enabled = True
    config.save()


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
        "participant_location_update_url": config.participant_location_update_url,
        "participant_location_test_url": config.participant_location_test_url,
        "api_key_configured": config.api_key_configured,
        "paired_at": config.paired_at.isoformat() if config.paired_at else None,
        "location_updates_enabled": config.location_updates_enabled,
        "recent_webhook_log": recent_webhook_log[:WEBHOOK_LOG_MAX],
        "domesti_bot_repo_url": DOMESTI_BOT_REPO_URL,
    }


def location_post_url_for_source(config: DomestiBotConfig, *, source: str) -> str:
    """Return the ingest URL for live GPS relay or manual test posts."""
    if source == "test":
        test_url = config.participant_location_test_url.strip()
        if not test_url:
            msg = "participant_location_test_url is not configured"
            raise ValueError(msg)
        return test_url
    live_url = config.participant_location_update_url.strip()
    if not live_url:
        msg = "participant_location_update_url is not configured"
        raise ValueError(msg)
    return live_url


def build_location_webhook_payload(
    *,
    participant_id: str,
    lat: float,
    lon: float,
    device_id: str = "test-device",
    mqtt_user: str | None = None,
) -> dict[str, Any]:
    """Build a domesti-bot location ingest payload."""
    return {
        "participant_id": participant_id,
        "lat": lat,
        "lon": lon,
        "timestamp": datetime.now(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "my-tracks",
        "device_id": device_id,
        "mqtt_user": mqtt_user or participant_id,
    }


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
    try:
        with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            body_preview = response.read(200).decode(errors="replace")
            status_code = response.status
            success = 200 <= status_code < 300
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

    entry = {
        "sent_at": timezone.now().isoformat(),
        "success": success,
        "http_status": status_code,
        "participant_id": payload.get("participant_id"),
        "payload": payload,
        "response_preview": body_preview,
        "source": source,
        "elapsed_ms": elapsed_ms,
    }
    append_webhook_log_entry(config, entry)
    return entry


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
