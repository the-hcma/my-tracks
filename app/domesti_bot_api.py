"""Admin API for domesti-bot pairing and configuration."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.domesti_bot import (
    TEST_LOCATION_DEFAULT_LAT,
    TEST_LOCATION_DEFAULT_LON,
    apply_config_patch,
    build_location_webhook_payload,
    log_pairing_activity,
    pair_domesti_bot,
    pairing_location_urls_from_data,
    send_location_webhook,
    serialize_domesti_bot_config,
)
from app.models import Device, DomestiBotConfig


def _request_data_as_str_dict(request: Request) -> dict[str, Any]:
    """Normalize DRF request data keys to plain strings for typing clarity."""
    return {str(key): value for key, value in request.data.items()}


def _config_response(config: DomestiBotConfig) -> Response:
    return Response(serialize_domesti_bot_config(config))


def _default_test_user_id() -> str:
    user = User.objects.filter(is_staff=True, is_active=True).filter(devices__isnull=False).order_by("username").first()
    if user is not None:
        return user.username
    staff = User.objects.filter(is_staff=True, is_active=True).order_by("username").first()
    if staff is not None:
        return staff.username
    return "admin"


class DomestiBotConfigView(APIView):
    """``GET`` / ``PATCH /api/admin/domesti-bot/config/`` — staff config read/update."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        del request
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
        config = DomestiBotConfig.get_solo()
        update_url, test_url = pairing_location_urls_from_data(data)
        try:
            pair_domesti_bot(
                config,
                api_key=str(data.get("api_key", "")),
                user_location_test_url=test_url,
                user_location_update_url=update_url,
                domesti_base_url=str(data.get("domesti_base_url", "") or ""),
            )
        except ValueError as exc:
            log_pairing_activity(
                config,
                success=False,
                domesti_base_url=str(data.get("domesti_base_url", "") or ""),
                user_location_test_url=test_url,
                user_location_update_url=update_url,
                error_message=str(exc),
            )
            return Response({"errors": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        body = serialize_domesti_bot_config(config)
        return Response(
            {
                "paired_at": body["paired_at"],
                "user_location_test_url": body["user_location_test_url"],
                "user_location_update_url": body["user_location_update_url"],
                "location_updates_enabled": body["location_updates_enabled"],
                "api_key_configured": body["api_key_configured"],
            }
        )


class DomestiBotTestLocationUpdateView(APIView):
    """``POST /api/admin/domesti-bot/test-location-update/`` — synthetic test via test URL only."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        config = DomestiBotConfig.get_solo()
        if not config.is_paired:
            return Response({"detail": "Not paired"}, status=status.HTTP_403_FORBIDDEN)

        data = _request_data_as_str_dict(request)
        user_id = str(data.get("user_id") or _default_test_user_id()).strip()
        if not User.objects.filter(username=user_id, is_active=True).exists():
            return Response(
                {"errors": [f"Unknown user_id: {user_id}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lat_raw = data.get("lat", TEST_LOCATION_DEFAULT_LAT)
        lon_raw = data.get("lon", TEST_LOCATION_DEFAULT_LON)
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except TypeError, ValueError:
            return Response({"errors": ["lat and lon must be numbers"]}, status=status.HTTP_400_BAD_REQUEST)

        device = Device.objects.filter(owner__username=user_id).order_by("-last_seen").first()
        device_id = device.device_id if device is not None else "test-device"
        payload = build_location_webhook_payload(
            lat=lat,
            lon=lon,
            user_id=user_id,
            device_id=device_id,
        )
        try:
            entry = send_location_webhook(config, payload=payload, source="test")
        except ValueError as exc:
            return Response({"errors": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        ok = bool(entry["success"])
        status_code = entry["http_status"]
        response_preview = str(entry["response_preview"])
        post_url = str(entry["post_url"])
        if ok:
            message = f"Test location update succeeded (HTTP {status_code})."
        else:
            message = (
                f"Test location update failed for {post_url}: "
                f"HTTP {status_code if status_code is not None else 'n/a'} — {response_preview}"
            )
        return Response(
            {
                "ok": ok,
                "post_url": post_url,
                "status_code": status_code,
                "elapsed_ms": entry["elapsed_ms"],
                "response_preview": response_preview,
                "message": message,
            }
        )


class DomestiBotRevealApiKeyView(APIView):
    """``GET /api/admin/domesti-bot/reveal-api-key/`` — staff-only decrypted API key for Admin UI."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        del request
        config = DomestiBotConfig.get_solo()
        if not config.is_paired:
            return Response({"detail": "Not paired"}, status=status.HTTP_403_FORBIDDEN)
        api_key = config.get_api_key()
        if not api_key:
            return Response({"detail": "API key not configured"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"api_key": api_key})
