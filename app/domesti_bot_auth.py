"""Authentication helpers for domesti-bot machine-facing API routes."""

from __future__ import annotations

import secrets

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from app.models import DomestiBotConfig

DOMESTI_API_KEY_HEADER = "X-Domesti-Api-Key"


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
        if not secrets.compare_digest(provided_key, stored_key):
            self.message = "Invalid or missing domesti-bot API key"
            return False
        return True
