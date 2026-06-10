"""domesti-bot integration: config helpers, pairing, and webhook log."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse, urlunparse

from django.utils import timezone

from app.pki import decrypt_private_key, encrypt_private_key

if TYPE_CHECKING:
    from app.models import DomestiBotConfig

WEBHOOK_LOG_MAX = 5
DOMESTI_BOT_REPO_URL = "https://github.com/the-hcma/domesti-bot"


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
    domesti_base_url: str = "",
) -> None:
    """Apply pairing payload from domesti-bot and persist."""
    key = api_key.strip()
    if not key:
        msg = "api_key is required"
        raise ValueError(msg)
    location_url = validate_absolute_http_url(participant_location_update_url)
    base = domesti_base_url.strip() or extract_base_url_from_location_url(location_url)
    validate_absolute_http_url(base)

    config.set_api_key(key)
    config.participant_location_update_url = location_url
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

    if "domesti_base_url" in data:
        raw = str(data["domesti_base_url"] or "").strip()
        if raw:
            try:
                config.domesti_base_url = validate_absolute_http_url(raw)
            except ValueError as exc:
                errors.append(str(exc))
        else:
            config.domesti_base_url = ""

    if "participant_location_update_url" in data:
        raw = str(data["participant_location_update_url"] or "").strip()
        if not raw:
            errors.append("participant_location_update_url is required when paired")
        else:
            try:
                config.participant_location_update_url = validate_absolute_http_url(raw)
            except ValueError as exc:
                errors.append(str(exc))

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
        "api_key_configured": config.api_key_configured,
        "paired_at": config.paired_at.isoformat() if config.paired_at else None,
        "location_updates_enabled": config.location_updates_enabled,
        "recent_webhook_log": recent_webhook_log[:WEBHOOK_LOG_MAX],
        "domesti_bot_repo_url": DOMESTI_BOT_REPO_URL,
    }


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
