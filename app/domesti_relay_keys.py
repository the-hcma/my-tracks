"""Relay key verifiers for the domesti-bot pairing (protocol version 2).

``K_out`` is the key domesti-bot presents to My Tracks. In protocol version 2 My Tracks keeps only a keyed
HMAC-SHA-256 verifier of it (hex), so a copy of the database holds nothing that authenticates, and a forged
verifier cannot be computed without ``SECRET_KEY``. Design: ``docs/RELAY_KEY_DIRECTIONS.md`` in domesti-bot.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

PROTOCOL_VERSION_LEGACY = 1
PROTOCOL_VERSION_SPLIT = 2
# Longest key value compared; anything longer cannot be a key domesti-bot issued (it generates 43 characters).
MAX_RELAY_KEY_LENGTH = 512
# How long the previous outbound verifier keeps working after an activation, for requests already in flight.
PREVIOUS_KEY_GRACE_SECONDS = 60
# How long a staged (pending) pairing stays valid before it must be re-staged.
PENDING_PAIRING_TTL_SECONDS = 30 * 60

_PEPPER_CONTEXT = b"my-tracks/domesti-relay-verifier/v1\0"


def _pepper() -> bytes:
    return hashlib.sha256(_PEPPER_CONTEXT + str(settings.SECRET_KEY).encode("utf-8")).digest()


def relay_key_verifier(key: str) -> str:
    """Keyed HMAC-SHA-256 (hex) of a relay key; deterministic, cannot be reversed to the key."""
    return hmac.new(_pepper(), key.encode("utf-8"), hashlib.sha256).hexdigest()


def verifier_matches(presented: str, verifier: str) -> bool:
    """Constant-time check of a presented key against a stored verifier; any text, never raises."""
    if not verifier or not presented or len(presented) > MAX_RELAY_KEY_LENGTH:
        return False
    return hmac.compare_digest(relay_key_verifier(presented).encode("ascii"), verifier.encode("ascii", "replace"))


def text_equal(left: str, right: str) -> bool:
    """Constant-time equality for short identifiers such as a pairing id; any text, never raises."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def pending_pairing_is_live(pending: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """True when a staged pairing exists and has not expired."""
    if not pending:
        return False
    expires_raw = pending.get("expires_at")
    expires = parse_datetime(str(expires_raw)) if expires_raw else None
    if expires is None:
        return False
    if timezone.is_naive(expires):
        expires = timezone.make_aware(expires)
    return expires > (now or timezone.now())
