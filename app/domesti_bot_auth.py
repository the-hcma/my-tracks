"""Authentication helpers for domesti-bot machine-facing API routes."""

from __future__ import annotations

import hmac

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from app.models import DomestiBotConfig

DOMESTI_API_KEY_HEADER = "X-Domesti-Api-Key"
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
        stored_key = config.get_api_key()
        if not stored_key or not provided_key:
            self.message = "Invalid or missing domesti-bot API key"
            return False
        if not relay_api_keys_match(provided_key, stored_key):
            self.message = "Invalid or missing domesti-bot API key"
            return False
        return True
