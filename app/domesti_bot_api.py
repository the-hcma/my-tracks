"""Admin API for domesti-bot pairing and configuration."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.domesti_bot import apply_config_patch, pair_domesti_bot, serialize_domesti_bot_config
from app.models import DomestiBotConfig


def _request_data_as_str_dict(request: Request) -> dict[str, Any]:
    """Normalize DRF request data keys to plain strings for typing clarity."""
    return {str(key): value for key, value in request.data.items()}


def _config_response(config: DomestiBotConfig) -> Response:
    return Response(serialize_domesti_bot_config(config))


class DomestiBotConfigView(APIView):
    """``GET`` / ``PATCH /api/admin/domesti-bot/config/`` — staff config read/update."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        return _config_response(DomestiBotConfig.get_solo())

    def patch(self, request: Request) -> Response:
        config = DomestiBotConfig.get_solo()
        if not config.is_paired:
            return Response({"detail": "Not paired"}, status=status.HTTP_403_FORBIDDEN)
        errors = apply_config_patch(config, _request_data_as_str_dict(request))
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return _config_response(config)


class DomestiBotPairView(APIView):
    """``POST /api/admin/domesti-bot/pair/`` — domesti-bot registers key and ingest URL."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        data = _request_data_as_str_dict(request)
        try:
            config = DomestiBotConfig.get_solo()
            pair_domesti_bot(
                config,
                api_key=str(data.get("api_key", "")),
                participant_location_update_url=str(data.get("participant_location_update_url", "")),
                domesti_base_url=str(data.get("domesti_base_url", "") or ""),
            )
        except ValueError as exc:
            return Response({"errors": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        body = serialize_domesti_bot_config(config)
        return Response(
            {
                "paired_at": body["paired_at"],
                "participant_location_update_url": body["participant_location_update_url"],
                "location_updates_enabled": body["location_updates_enabled"],
                "api_key_configured": body["api_key_configured"],
            }
        )
