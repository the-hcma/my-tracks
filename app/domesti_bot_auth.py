"""Authentication helpers for domesti-bot machine-facing API routes."""

from __future__ import annotations

import hmac

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from app.models import DomestiBotConfig

DOMESTI_API_KEY_HEADER = "X-Domesti-Api-Key"
DOMESTI_PAIRING_ID_HEADER = "X-Domesti-Pairing-Id"
# Longest header value compared; anything longer cannot be a key this service issued.
_MAX_API_KEY_LENGTH = 512


def relay_api_keys_match(provided_key: str, stored_key: str) -> bool:
    """Constant-time comparison that accepts any text.

    ``secrets.compare_digest`` raises ``TypeError`` for ``str`` values containing non-ASCII
    characters, which a client can send in a header, so compare the UTF-8 bytes instead.
    """
    if len(provided_key) > _MAX_API_KEY_LENGTH:
        return False
    return hmac.compare_digest(provided_key.encode("utf-8"), stored_key.encode("utf-8"))


class DomestiRelayApiKeyPermission(BasePermission):
    """Require a valid paired relay API key and remote request-location opt-in."""

    message = "Invalid or missing domesti-bot API key"

    def has_permission(self, request: Request, view: APIView) -> bool:
        del view
        config = DomestiBotConfig.get_solo()
        if not config.is_paired:
            self.message = "Not paired"
            return False
        if not config.remote_request_location_enabled:
            self.message = "Remote request-location via API key is disabled"
            return False

        provided_key = str(request.headers.get(DOMESTI_API_KEY_HEADER, "")).strip()
        if not provided_key or not config.outbound_key_matches(provided_key):
            self.message = "Invalid or missing domesti-bot API key"
            return False
        return True


class DomestiRelayAuthCheckPermission(BasePermission):
    """Accept the active outbound key, or the staged one for the live pending pairing named in the header.

    Used only by the auth-check endpoint, which lets domesti-bot verify a staged key without queuing a
    location request or activating anything. It does not require the request-location opt-in.
    """

    message = "Invalid or missing domesti-bot API key"

    def has_permission(self, request: Request, view: APIView) -> bool:
        del view
        provided_key = str(request.headers.get(DOMESTI_API_KEY_HEADER, "")).strip()
        if not provided_key:
            return False
        config = DomestiBotConfig.get_solo()
        pairing_id = str(request.headers.get(DOMESTI_PAIRING_ID_HEADER, "")).strip()
        if pairing_id and config.pending_outbound_key_matches(provided_key, pairing_id):
            request.auth_check_key = "pending"  # type: ignore[attr-defined]
            return True
        if config.is_paired and config.outbound_key_matches(provided_key):
            request.auth_check_key = "active"  # type: ignore[attr-defined]
            return True
        return False
