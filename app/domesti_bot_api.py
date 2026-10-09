"""Admin API for domesti-bot pairing and configuration."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
from django.http import HttpResponseBase
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.domesti_bot import (
    TEST_LOCATION_DEFAULT_LAT,
    TEST_LOCATION_DEFAULT_LON,
    PairingIdInUseError,
    abort_domesti_pairing,
    activate_domesti_pairing,
    apply_config_patch,
    build_location_webhook_payload,
    locked_domesti_config,
    log_pairing_activity,
    normalized_pairing_id,
    pair_domesti_bot,
    pairing_location_urls_from_data,
    pairing_status,
    pending_probe_credentials,
    requested_protocol_version,
    send_location_webhook,
    serialize_domesti_bot_config,
    serialize_domesti_bot_pair_response,
    stage_domesti_pairing,
)
from app.domesti_bot_auth import DomestiRelayApiKeyPermission, DomestiRelayAuthCheckPermission
from app.domesti_location_request import (
    LocationRequestError,
    serialize_location_request_batch_result,
    serialize_location_request_result,
)
from app.domesti_location_request_queue import (
    domesti_location_request_lock,
    enqueue_batch_location_request,
    enqueue_device_location_request,
)
from app.domesti_relay_keys import PROTOCOL_VERSION_SPLIT
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


class DomestiBotAuthCheckView(APIView):
    """``GET /api/domesti-bot/auth-check/`` — does this outbound key authenticate? No side effects.

    Accepts the active key, or the staged key together with ``X-Domesti-Pairing-Id`` of a live pending
    pairing. domesti-bot calls it to verify a staged key before activating the pairing.
    """

    authentication_classes: list[Any] = []
    permission_classes = [DomestiRelayAuthCheckPermission]

    def get(self, request: Request) -> Response:
        config = DomestiBotConfig.get_solo()
        return Response(
            {
                "ok": True,
                "key": getattr(request, "auth_check_key", "active"),
                "protocol_version": config.protocol_version,
            }
        )


class DomestiBotPairView(APIView):
    """``POST /api/admin/domesti-bot/pair/`` — domesti-bot registers key and ingest URL."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        data = _request_data_as_str_dict(request)
        config = DomestiBotConfig.get_solo()
        update_url, test_url = pairing_location_urls_from_data(data)
        try:
            version = requested_protocol_version(data)
            if version >= PROTOCOL_VERSION_SPLIT:
                # Protocol 2 stages the keys; nothing switches until the pairing is activated.
                with locked_domesti_config() as locked:
                    return Response(stage_domesti_pairing(locked, data=data))
            with locked_domesti_config() as locked:
                pair_domesti_bot(
                    locked,
                    api_key=str(data.get("api_key", "")),
                    user_location_test_url=test_url,
                    user_location_update_url=update_url,
                    domesti_base_url=str(data.get("domesti_base_url", "") or ""),
                )
                config = locked
        except PairingIdInUseError as exc:
            return Response({"errors": [str(exc)]}, status=status.HTTP_409_CONFLICT)
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

        body = serialize_domesti_bot_pair_response(config)
        return Response(body)


def _pairing_id_from(request: Request) -> str:
    """The request's pairing id if well formed; a malformed one is treated as an unknown pairing."""
    raw = _request_data_as_str_dict(request).get("pairing_id", "") or request.query_params.get("pairing_id", "")
    return normalized_pairing_id(raw)


class DomestiBotPairActivateView(APIView):
    """``POST /api/admin/domesti-bot/pair/activate/`` — promote a staged pairing (idempotent per pairing id)."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        pairing_id = _pairing_id_from(request).strip()
        state, _config = activate_domesti_pairing(pairing_id)
        if state == "active":
            return Response({"status": "active", "pairing_id": pairing_id})
        code = status.HTTP_410_GONE if state == "expired" else status.HTTP_404_NOT_FOUND
        return Response({"status": state, "pairing_id": pairing_id}, status=code)


class DomestiBotPairAbortView(APIView):
    """``POST /api/admin/domesti-bot/pair/abort/`` — discard a staged pairing (best effort, idempotent)."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        pairing_id = _pairing_id_from(request).strip()
        with locked_domesti_config() as locked:
            state = abort_domesti_pairing(locked, pairing_id)
        if state == "active":
            return Response({"status": "active", "pairing_id": pairing_id}, status=status.HTTP_409_CONFLICT)
        return Response({"status": state, "pairing_id": pairing_id})


class DomestiBotPairStateView(APIView):
    """``GET /api/admin/domesti-bot/pair/state/?pairing_id=`` — ``active``, ``staged``, ``expired`` or ``unknown``."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        pairing_id = _pairing_id_from(request).strip()
        return Response({"status": pairing_status(DomestiBotConfig.get_solo(), pairing_id), "pairing_id": pairing_id})


class DomestiBotTestLocationUpdateView(APIView):
    """``POST /api/admin/domesti-bot/test-location-update/`` — synthetic test via test URL only."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        config = DomestiBotConfig.get_solo()
        data = _request_data_as_str_dict(request)
        # With a pairing_id the test goes to the staged pairing's URL with its staged key, so domesti-bot can
        # probe a pairing before activating it (the active pairing is untouched).
        probe_requested = bool(str(data.get("pairing_id", "") or "").strip())
        probe_id = normalized_pairing_id(data.get("pairing_id"))
        probe = pending_probe_credentials(config, probe_id) if probe_id else None
        if probe_requested and probe is None:
            return Response(
                {"errors": ["No usable staged pairing for that pairing_id"]}, status=status.HTTP_404_NOT_FOUND
            )
        if probe is None and not config.is_paired:
            return Response({"detail": "Not paired"}, status=status.HTTP_403_FORBIDDEN)

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
            entry = send_location_webhook(
                config,
                payload=payload,
                source="test",
                api_key=probe[0] if probe else None,
                post_url=probe[1] if probe else None,
            )
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


def _location_request_context(request: Request) -> tuple[str, str | None, str | None]:
    data = _request_data_as_str_dict(request)
    reason = str(data.get("reason", "")).strip()
    rule_id_raw = data.get("rule_id")
    geofence_id_raw = data.get("geofence_id")
    rule_id = str(rule_id_raw).strip() if rule_id_raw not in (None, "") else None
    geofence_id = str(geofence_id_raw).strip() if geofence_id_raw not in (None, "") else None
    return reason, rule_id, geofence_id


def _location_request_error_response(exc: LocationRequestError) -> Response:
    body: dict[str, Any] = {"detail": exc.detail}
    body.update(exc.extra)
    return Response(body, status=exc.status_code)


class DomestiBotRequestAllLocationsView(APIView):
    """``POST /api/domesti-bot/users/{user_id}/request-location/`` — queue reportLocation on all devices."""

    authentication_classes: list[type] = []
    permission_classes = [DomestiRelayApiKeyPermission]

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        with domesti_location_request_lock():
            return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request, user_id: str) -> Response:
        reason, rule_id, geofence_id = _location_request_context(request)
        config = DomestiBotConfig.get_solo()
        try:
            result = enqueue_batch_location_request(
                config,
                user_id=user_id,
                reason=reason,
                rule_id=rule_id,
                geofence_id=geofence_id,
            )
        except LocationRequestError as exc:
            return _location_request_error_response(exc)

        return Response(
            serialize_location_request_batch_result(result, config=config),
            status=status.HTTP_202_ACCEPTED,
        )


class DomestiBotRequestDeviceLocationView(APIView):
    """``POST /api/domesti-bot/users/{user_id}/devices/{device_id}/request-location/`` — one device."""

    authentication_classes: list[type] = []
    permission_classes = [DomestiRelayApiKeyPermission]

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        with domesti_location_request_lock():
            return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request, user_id: str, device_id: str) -> Response:
        reason, rule_id, geofence_id = _location_request_context(request)
        config = DomestiBotConfig.get_solo()
        try:
            result = enqueue_device_location_request(
                config,
                user_id=user_id,
                device_id=device_id,
                reason=reason,
                rule_id=rule_id,
                geofence_id=geofence_id,
            )
        except LocationRequestError as exc:
            return _location_request_error_response(exc)

        return Response(
            serialize_location_request_result(result, config=config),
            status=status.HTTP_202_ACCEPTED,
        )
