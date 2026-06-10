"""
API views for OwnTracks location tracking.

This module provides REST API endpoints for receiving location data
from OwnTracks clients and querying stored location history.
"""

import logging
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_package_version
from typing import Any, cast

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import HttpResponse as DjangoHttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .apps import get_mqtt_broker, is_mqtt_degraded
from .auth import CommandApiKeyAuthentication, CsrfExemptSessionAuthentication
from .models import (
    CertificateAuthority,
    ClientCertificate,
    Device,
    DeviceShare,
    FriendRequest,
    Location,
    OwnTracksMessage,
    ServerCertificate,
)
from .mqtt.commands import Command, CommandPublisher
from .pki import (
    ALLOWED_KEY_SIZES,
    decrypt_private_key,
    encrypt_private_key,
    generate_ca_certificate,
    generate_client_certificate,
    generate_crl,
    generate_pkcs12,
    generate_server_certificate,
    get_certificate_expiry,
    get_certificate_fingerprint,
    get_certificate_sans,
    get_certificate_serial_number,
    get_certificate_subject,
)
from .serializers import (
    CertificateAuthoritySerializer,
    ChangePasswordSerializer,
    ClientCertificateSerializer,
    DeviceSerializer,
    DeviceShareSerializer,
    FriendRequestSerializer,
    FriendSerializer,
    FriendUserSearchSerializer,
    LocationSerializer,
    ServerCertificateSerializer,
    UserProfileSerializer,
    UserSerializer,
)
from .utils import extract_device_id

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class LocationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing location data.

    Provides endpoints for:
    - POST: Receive location data from OwnTracks clients (AllowAny — devices use their own auth)
    - GET: Query location history (requires authentication)
    - Filter by device, date range, etc.
    """

    serializer_class = LocationSerializer

    def get_permissions(self) -> list[object]:
        """Allow unauthenticated OwnTracks device POSTs; require auth for reads."""
        if self.action == "create":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self) -> QuerySet[Location]:
        """Return locations for devices owned by or shared with the current user; staff see all."""
        from django.db.models import Q

        user = self.request.user
        if not user.is_authenticated:
            return Location.objects.all()
        qs = Location.objects.select_related("device__owner")
        if user.is_staff:
            return qs
        allowed_devices = Device.objects.filter(Q(owner=user) | Q(shares__shared_with=user)).distinct()
        return qs.filter(device__in=allowed_devices)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Handle incoming location data from OwnTracks client.

        Accepts OwnTracks JSON format and creates a new location record.

        Args:
            request: HTTP request with OwnTracks JSON payload

        Returns:
            Response with 201 Created status on success

        Raises:
            ValidationError: If payload is invalid
        """
        from app.ip import get_http_client_ip

        client_ip = get_http_client_ip(request.META) or "unknown"

        logger.info("[http] Incoming location request from: %s", client_ip)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Request data: %s, Content-Type: %s", request.data, request.content_type)

        # Check message type
        msg_type = request.data.get("_type", "location")

        if msg_type != "location":
            logger.info("Received non-location message type: %s, storing", msg_type)

            # Try to identify the device
            device = None

            # Convert request.data to dict for type-safe access
            raw_data = request.data
            field_name_to_value: dict[str, Any] = {
                str(k): v for k, v in (raw_data.items() if hasattr(raw_data, "items") else [])
            }

            device_id = extract_device_id(field_name_to_value)

            if device_id:
                device, created = Device.objects.get_or_create(
                    device_id=device_id, defaults={"name": f"Device {device_id}"}
                )
                # Always log device connections (special case - always appears)
                if created:
                    logger.info("New device connected: %s from %s", device_id, client_ip)
                else:
                    logger.debug("Device reconnected: %s from %s", device_id, client_ip)

            # Store the message
            OwnTracksMessage.objects.create(
                device=device, message_type=msg_type, payload=field_name_to_value, ip_address=client_ip
            )

            # OwnTracks expects an empty JSON array response
            return Response([], status=status.HTTP_200_OK)

        # Extract device_id from request data if not explicitly set
        raw_data = request.data
        field_name_to_value: dict[str, Any] = {
            str(k): v for k, v in (raw_data.items() if hasattr(raw_data, "items") else [])
        }
        if "device_id" not in field_name_to_value:
            device_id = extract_device_id(field_name_to_value)
            if device_id:
                field_name_to_value["device_id"] = device_id
                logger.info("[http] Extracted device_id '%s' from request data", device_id)

        serializer = self.get_serializer(data=field_name_to_value, context={"client_ip": client_ip})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        location_instance = serializer.instance
        if location_instance.device.owner_id is not None:
            from app.domesti_relay import relay_location_to_domesti_bot

            relay_location_to_domesti_bot(location_instance)

        # Broadcast new location via WebSocket to owner, shared friends, and staff.
        location_data = serializer.data
        try:
            from app.ws_broadcast import broadcast_device_event_sync

            logger.info(
                "[http] Broadcasting location to WebSocket (id=%s, device=%s)",
                location_data.get("id"),
                location_data.get("device_id_display"),
            )
            broadcast_device_event_sync(
                serializer.instance.device,
                message_type="location_update",
                data=location_data,
            )
            logger.info(
                "[http] WebSocket broadcast completed for location %s",
                location_data.get("id"),
            )
        except Exception as e:
            logger.error(
                "[http] WebSocket broadcast failed",
                extra={"location_id": location_data.get("id"), "error": str(e)},
                exc_info=True,
            )

        # OwnTracks expects an empty JSON array response
        return Response([], status=status.HTTP_200_OK)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        List location history with optional filtering.

        Query parameters:
        - device: Filter by device ID
        - start_time: Unix timestamp (takes precedence over start_date)
        - start_date: ISO 8601 datetime (e.g., 2024-01-01T00:00:00Z)
        - end_time: Unix timestamp (takes precedence over end_date)
        - end_date: ISO 8601 datetime
        - limit: Maximum number of results
        - resolution: Minimum seconds between waypoints (0 = all points)

        Args:
            request: HTTP request with query parameters

        Returns:
            Paginated list of location records
        """
        queryset = self.get_queryset()

        # Filter by device — accepts "owner/device_id" or plain "device_id"; inaccessible
        # devices return 404 (same as non-existent, no existence leak).
        device_param = request.query_params.get("device")
        if device_param:
            from django.db.models import Q

            try:
                if "/" in device_param:
                    owner_username, dev_id = device_param.split("/", 1)
                    if request.user.is_staff:
                        device = Device.objects.get(owner__username=owner_username, device_id=dev_id)
                    else:
                        device = Device.objects.get(
                            Q(owner=request.user) | Q(shares__shared_with=request.user),
                            owner__username=owner_username,
                            device_id=dev_id,
                        )
                elif request.user.is_staff:
                    device = Device.objects.get(device_id=device_param)
                else:
                    device = Device.objects.filter(
                        Q(owner=request.user) | Q(shares__shared_with=request.user),
                        device_id=device_param,
                    ).get()
                queryset = queryset.filter(device=device)
            except Device.DoesNotExist:
                return Response(
                    {"error": f"Expected valid device ID, got '{device_param}' which does not exist"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Filter by date range
        start_date = request.query_params.get("start_date")
        start_time = request.query_params.get("start_time")  # Unix timestamp

        if start_time:
            try:
                start_timestamp = int(str(start_time))
                start_dt = datetime.fromtimestamp(start_timestamp, tz=UTC)
                queryset = queryset.filter(timestamp__gte=start_dt)
            except (ValueError, OSError) as e:
                return Response(
                    {"error": f"Expected Unix timestamp for start_time, got invalid value: {e}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                queryset = queryset.filter(timestamp__gte=start_dt)
            except ValueError as e:
                return Response(
                    {"error": f"Expected ISO 8601 datetime for start_date, got invalid format: {e}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        end_date = request.query_params.get("end_date")
        end_time = request.query_params.get("end_time")  # Unix timestamp

        if end_time:
            try:
                end_timestamp = int(str(end_time))
                end_dt = datetime.fromtimestamp(end_timestamp, tz=UTC)
                queryset = queryset.filter(timestamp__lte=end_dt)
            except (ValueError, OSError) as e:
                return Response(
                    {"error": f"Expected Unix timestamp for end_time, got invalid value: {e}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                queryset = queryset.filter(timestamp__lte=end_dt)
            except ValueError as e:
                return Response(
                    {"error": f"Expected ISO 8601 datetime for end_date, got invalid format: {e}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Apply resolution-based thinning (for coarse mode)
        # resolution parameter specifies minimum seconds between waypoints
        # resolution=0 means return all points (no thinning) but bypass pagination
        resolution = request.query_params.get("resolution")
        if resolution is not None:
            try:
                resolution_seconds = int(str(resolution))
                # Get all matching locations ordered by timestamp (ascending for thinning)
                all_locations = list(queryset.order_by("timestamp"))
                if all_locations:
                    if resolution_seconds > 0:
                        # Thin out to roughly one point per resolution_seconds
                        thinned = [all_locations[0]]
                        last_timestamp = all_locations[0].timestamp
                        for loc in all_locations[1:]:
                            time_diff = (loc.timestamp - last_timestamp).total_seconds()
                            if time_diff >= resolution_seconds:
                                thinned.append(loc)
                                last_timestamp = loc.timestamp
                        # Always include the last point
                        if thinned[-1] != all_locations[-1]:
                            thinned.append(all_locations[-1])
                        result_locations = thinned
                    else:
                        # resolution=0 means return all points (no thinning)
                        result_locations = all_locations
                    # Reverse to return newest first (matching -timestamp ordering)
                    result_locations.reverse()
                    # Return results directly (bypass pagination)
                    serializer = self.get_serializer(result_locations, many=True)
                    return Response(
                        {
                            "results": serializer.data,
                            "count": len(result_locations),
                            "resolution_applied": resolution_seconds,
                        }
                    )
            except ValueError:
                return Response(
                    {"error": f"Expected integer for resolution, got '{resolution}'"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class DeviceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing devices.

    Provides read-only endpoints for:
    - GET /devices/: List all devices owned by or shared with the current user
    - GET /devices/{id}/: Get device details
    - GET /devices/{id}/locations/: Get locations for specific device
    """

    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "device_id"

    def get_queryset(self) -> QuerySet[Device]:
        """Return devices owned by or shared with the current user; staff see all."""
        from django.db.models import Q

        user = self.request.user
        if user.is_staff:
            return Device.objects.all()
        return Device.objects.filter(Q(owner=user) | Q(shares__shared_with=user)).distinct()

    @action(detail=True, methods=["get"])
    def locations(self, request: Request, device_id: str | None = None) -> Response:
        """
        Get all locations for a specific device.

        Args:
            request: HTTP request
            device_id: Device identifier

        Returns:
            Paginated list of locations for the device
        """
        device = self.get_object()
        locations = device.locations.all()

        page = self.paginate_queryset(locations)
        if page is not None:
            serializer = LocationSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = LocationSerializer(locations, many=True)
        return Response(serializer.data)


class CommandViewSet(viewsets.ViewSet):
    """
    ViewSet for sending MQTT commands to OwnTracks devices.

    Provides endpoints for:
    - POST /commands/report-location/: Request device to report its location
    - POST /commands/set-waypoints/: Set waypoints on a device
    - POST /commands/clear-waypoints/: Clear waypoints from a device

    All endpoints require a device_id parameter in the request body.
    """

    # CsrfExemptSessionAuthentication accepts logged-in browser sessions without
    # requiring X-CSRFToken on JSON fetch() calls; CommandApiKeyAuthentication
    # handles automated clients that supply Authorization: Bearer <key>.
    authentication_classes = [CsrfExemptSessionAuthentication, CommandApiKeyAuthentication]
    # Require an authenticated identity (logged-in session user or valid API key).
    permission_classes = [IsAuthenticated]

    def _get_publisher(self) -> CommandPublisher:
        """Get the command publisher connected to the running MQTT broker."""
        broker = get_mqtt_broker()
        if broker is not None and broker.is_running:
            amqtt_broker = broker.amqtt_broker
            if amqtt_broker is not None:
                return CommandPublisher(mqtt_client=amqtt_broker)
            logger.warning(
                "[http] MQTT broker is running but internal publish is unavailable "
                "(likely restarting/reloading); commands temporarily disabled"
            )
        return CommandPublisher()

    def _resolve_device(self, raw_device_id: str, request: Request) -> tuple[Device, str] | None:
        """
        Look up a Device by device_id and return (device, mqtt_topic_id).

        Accepts both ``device_id`` and ``mqtt_user/device_id`` formats; the
        user-prefix portion of a slash-format input is stripped before the
        database lookup so the result always reflects the device's stored
        ``mqtt_user`` field.

        For non-staff users only devices owned by or shared with the requesting
        user are considered.  Staff may access any device.

        Returns ``None`` when no matching device is found.
        """
        from django.db.models import Q

        raw = str(raw_device_id).strip()

        def accessible_queryset() -> QuerySet[Device]:
            qs = Device.objects.select_related("owner")
            if request.user.is_authenticated and not request.user.is_staff:
                qs = qs.filter(Q(owner=request.user) | Q(shares__shared_with=request.user)).distinct()
            return qs

        device: Device | None = None
        if "/" in raw:
            owner_username, bare_device_id = raw.split("/", 1)
            try:
                device = cast(
                    Device,
                    accessible_queryset().get(
                        owner__username=owner_username,
                        device_id=bare_device_id,
                    ),
                )
            except Device.DoesNotExist:
                try:
                    device = cast(Device, accessible_queryset().get(device_id=bare_device_id))
                except Device.DoesNotExist, Device.MultipleObjectsReturned:
                    return None
        else:
            try:
                device = cast(Device, accessible_queryset().get(device_id=raw))
            except Device.DoesNotExist, Device.MultipleObjectsReturned:
                return None

        if device is None:
            return None

        bare_device_id = device.device_id

        mqtt_user = device.mqtt_user or (device.owner.username if device.owner else bare_device_id)
        return device, f"{mqtt_user}/{device.device_id}"

    @action(detail=False, methods=["post"], url_path="report-location")
    def report_location(self, request: Request) -> Response:
        """
        Request a device to report its current location.

        Request body:
            {
                "device_id": "device_id"  OR  "mqtt_user/device_id"
            }

        Returns:
            200: Command sent successfully
            400: Missing device_id or device not found
            503: MQTT broker not available
        """
        raw_device_id = request.data.get("device_id")
        if not raw_device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resolved = self._resolve_device(str(raw_device_id), request)
        if resolved is None:
            return Response(
                {"error": f"Device '{raw_device_id}' not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _device, device_id = resolved

        logger.info(
            "[http] reportLocation command requested by %s for device %s",
            request.user.username,
            device_id,
        )

        publisher = self._get_publisher()

        try:
            success = async_to_sync(publisher.send_command)(
                device_id,
                Command.report_location(),
                owner=request.user.username,
            )
        except RuntimeError as e:
            detail = str(e)
            if detail == "No MQTT client configured":
                detail = "MQTT broker restarting; try again shortly"
            logger.warning("[http] MQTT broker not available for command: %s", detail)
            return Response(
                {"error": "MQTT broker not available", "detail": detail},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if success:
            logger.info(
                "[http] reportLocation command sent to %s (requested by %s)",
                device_id,
                request.user.username,
            )
            return Response(
                {"status": "command_sent", "device_id": device_id, "command": "reportLocation"},
                status=status.HTTP_200_OK,
            )
        logger.warning("[http] reportLocation command failed for %s", device_id)
        return Response(
            {"error": "Failed to send command", "device_id": device_id},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="set-waypoints")
    def set_waypoints(self, request: Request) -> Response:
        """
        Set waypoints/regions on a device.

        Request body:
            {
                "device_id": "device_id"  OR  "mqtt_user/device_id",
                "waypoints": [
                    {
                        "desc": "Home",
                        "lat": 51.5074,
                        "lon": -0.1278,
                        "rad": 100
                    }
                ]
            }

        Returns:
            200: Command sent successfully
            400: Missing required fields, device not found, or invalid format
            503: MQTT broker not available
        """
        raw_device_id = request.data.get("device_id")
        waypoints = request.data.get("waypoints")

        if not raw_device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not waypoints or not isinstance(waypoints, list):
            return Response(
                {"error": "waypoints must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resolved = self._resolve_device(str(raw_device_id), request)
        if resolved is None:
            return Response(
                {"error": f"Device '{raw_device_id}' not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _device, device_id = resolved

        publisher = self._get_publisher()

        try:
            success = async_to_sync(publisher.send_command)(
                device_id,
                Command.set_waypoints(waypoints),
                owner=request.user.username,
            )
        except RuntimeError as e:
            detail = str(e)
            if detail == "No MQTT client configured":
                detail = "MQTT broker restarting; try again shortly"
            logger.warning("[http] MQTT broker not available: %s", detail)
            return Response(
                {"error": "MQTT broker not available", "detail": detail},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if success:
            return Response(
                {
                    "status": "command_sent",
                    "device_id": device_id,
                    "command": "setWaypoints",
                    "waypoint_count": len(waypoints),
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {"error": "Failed to send command", "device_id": device_id},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="clear-waypoints")
    def clear_waypoints(self, request: Request) -> Response:
        """
        Clear all waypoints from a device.

        Request body:
            {
                "device_id": "device_id"  OR  "mqtt_user/device_id"
            }

        Returns:
            200: Command sent successfully
            400: Missing device_id or device not found
            503: MQTT broker not available
        """
        raw_device_id = request.data.get("device_id")
        if not raw_device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resolved = self._resolve_device(str(raw_device_id), request)
        if resolved is None:
            return Response(
                {"error": f"Device '{raw_device_id}' not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _device, device_id = resolved

        publisher = self._get_publisher()

        try:
            success = async_to_sync(publisher.send_command)(
                device_id,
                Command.clear_waypoints(),
                owner=request.user.username,
            )
        except RuntimeError as e:
            detail = str(e)
            if detail == "No MQTT client configured":
                detail = "MQTT broker restarting; try again shortly"
            logger.warning("[http] MQTT broker not available: %s", detail)
            return Response(
                {"error": "MQTT broker not available", "detail": detail},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if success:
            return Response(
                {"status": "command_sent", "device_id": device_id, "command": "clearWaypoints"},
                status=status.HTTP_200_OK,
            )
        return Response(
            {"error": "Failed to send command", "device_id": device_id},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="fetch-waypoints")
    def fetch_waypoints(self, request: Request) -> Response:
        """
        Request a device to publish its current waypoints.

        Sends a 'waypoints' command to the device, which causes the phone to
        publish a '_type: waypoints' MQTT message.  The MQTT plugin automatically
        merges the returned waypoints into the server Waypoint table (upsert by rid).

        Request body:
            {
                "device_id": "device_id"  OR  "mqtt_user/device_id"
            }

        Returns:
            200: Waypoints command sent; waypoints will be merged when the phone responds
            400: Missing device_id, device not found, or invalid format
            503: MQTT broker not available
        """
        raw_device_id = request.data.get("device_id")
        if not raw_device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resolved = self._resolve_device(str(raw_device_id), request)
        if resolved is None:
            return Response(
                {"error": f"Device '{raw_device_id}' not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _device, device_id = resolved

        logger.info(
            "[http] fetchWaypoints command requested by %s for device %s",
            request.user.username,
            device_id,
        )

        publisher = self._get_publisher()

        try:
            success = async_to_sync(publisher.send_command)(
                device_id,
                Command.request_waypoints(),
                owner=request.user.username,
            )
        except RuntimeError as e:
            detail = str(e)
            if detail == "No MQTT client configured":
                detail = "MQTT broker restarting; try again shortly"
            logger.warning("[http] MQTT broker not available for waypoints command: %s", detail)
            return Response(
                {"error": "MQTT broker not available", "detail": detail},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if success:
            logger.info(
                "[http] waypoints command sent to %s (requested by %s)",
                device_id,
                request.user.username,
            )
            return Response(
                {
                    "status": "command_sent",
                    "device_id": device_id,
                    "command": "waypoints",
                    "note": "waypoints will be merged when the device responds",
                },
                status=status.HTTP_200_OK,
            )
        logger.warning("[http] waypoints command failed for %s", device_id)
        return Response(
            {"error": "Failed to send command", "device_id": device_id},
            status=status.HTTP_400_BAD_REQUEST,
        )


class AccountViewSet(viewsets.ViewSet):
    """
    Self-service account management for the authenticated user.

    Endpoints:
    - GET /api/account/ — retrieve current user profile
    - PATCH /api/account/ — update profile fields
    - POST /api/account/change-password/ — change password
    """

    permission_classes = [IsAuthenticated]

    def list(self, request: Request) -> Response:
        """Return the authenticated user's profile."""
        serializer = UserProfileSerializer(request.user.profile)
        return Response(serializer.data)

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        """Update the authenticated user's profile and user fields."""
        user = request.user
        profile = user.profile
        data: dict[str, Any] = {str(k): v for k, v in (request.data.items() if hasattr(request.data, "items") else [])}

        user_fields = {"first_name", "last_name", "email"}
        user_changed = False
        for field in user_fields:
            if field in data:
                setattr(user, field, data[field])
                user_changed = True
        if user_changed:
            user.save()

        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(UserProfileSerializer(profile).data)

    @action(detail=False, methods=["post"], url_path="change-password")
    def change_password(self, request: Request) -> Response:
        """Change the authenticated user's password."""
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        validated: dict[str, Any] = serializer.validated_data  # type: ignore[assignment]
        request.user.set_password(validated["new_password"])
        request.user.save()
        logger.info("[api] User '%s' changed their password", request.user.username)
        return Response({"detail": "Password updated successfully."})


class AdminUserViewSet(viewsets.ViewSet):
    """
    Admin-only user management.

    Endpoints:
    - GET /api/admin/users/ — list all users
    - POST /api/admin/users/ — create a new user
    - DELETE /api/admin/users/{id}/ — deactivate a user
    - POST /api/admin/users/{id}/reactivate/ — reactivate a user
    - POST /api/admin/users/{id}/toggle-admin/ — toggle admin status
    - DELETE /api/admin/users/{id}/hard-delete/ — permanently delete a user
    - POST /api/admin/users/{id}/set-password/ — set a user's password
    """

    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        """List all users."""
        users = User.objects.all().order_by("username")
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)

    def create(self, request: Request) -> Response:
        """Create a new user."""
        username = request.data.get("username")
        if not username:
            return Response(
                {"error": "username is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {"error": f"User '{username}' already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        password = request.data.get("password")
        if not password:
            return Response(
                {"error": "password is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_staff = request.data.get("is_staff", False)

        user = User.objects.create_user(
            username=username,
            email=request.data.get("email", ""),
            password=password,
            first_name=request.data.get("first_name", ""),
            last_name=request.data.get("last_name", ""),
        )
        if is_staff:
            user.is_staff = True
            user.is_superuser = True
            user.save()

        role = "admin" if is_staff else "user"
        logger.info("[http] User '%s' created '%s' (role=%s) via API", request.user.username, username, role)

        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Deactivate a user (soft delete)."""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": f"Expected valid user ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user == request.user:
            return Response(
                {"error": "Cannot deactivate your own account"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_active = False
        user.save()
        return Response(
            {"detail": f"User '{user.username}' has been deactivated."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request: Request, pk: str | None = None) -> Response:
        """Reactivate a previously deactivated user."""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": f"Expected valid user ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        user.is_active = True
        user.save()
        return Response(
            {"detail": f"User '{user.username}' has been reactivated."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="toggle-admin")
    def toggle_admin(self, request: Request, pk: str | None = None) -> Response:
        """Toggle admin/staff status for a user."""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": f"Expected valid user ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user == request.user:
            return Response(
                {"error": "Cannot change your own admin status"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_staff = not user.is_staff
        user.is_superuser = user.is_staff
        user.save()
        new_role = "admin" if user.is_staff else "user"
        return Response(
            {"detail": f"User '{user.username}' is now {new_role}.", "is_staff": user.is_staff},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["delete"], url_path="hard-delete")
    def hard_delete(self, request: Request, pk: str | None = None) -> Response:
        """Permanently delete a user and all associated data."""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": f"Expected valid user ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user == request.user:
            return Response(
                {"error": "Cannot delete your own account"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = user.username
        user.delete()
        return Response(
            {"detail": f"User '{username}' has been permanently deleted."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request: Request, pk: str | None = None) -> Response:
        """Set a new password for a user."""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": f"Expected valid user ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        password: Any = request.data.get("password")
        if not password:
            return Response(
                {"error": "password is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(str(password)) < 8:
            return Response(
                {"error": "Password must be at least 8 characters"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(str(password))
        user.save()
        logger.info("[api] Admin '%s' reset password for user '%s'", request.user.username, user.username)
        return Response(
            {"detail": f"Password for '{user.username}' has been updated."},
            status=status.HTTP_200_OK,
        )


class CertificateAuthorityViewSet(viewsets.ViewSet):
    """
    Admin-only CA certificate management.

    Endpoints:
    - GET /api/admin/pki/ca/ — retrieve the active CA certificate (public part)
    - POST /api/admin/pki/ca/ — generate a new CA certificate
    - DELETE /api/admin/pki/ca/{id}/ — revoke (deactivate) a CA
    """

    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        """Retrieve CA certificates, most recent first."""
        cas = CertificateAuthority.objects.all()
        serializer = CertificateAuthoritySerializer(cas, many=True)
        return Response(serializer.data)

    def create(self, request: Request) -> Response:
        """Generate a new self-signed CA certificate."""
        common_name: Any = request.data.get("common_name", "My Tracks CA")
        validity_days_raw: Any = request.data.get("validity_days", 3650)

        if not isinstance(common_name, str) or not common_name.strip():
            return Response(
                {"error": "Expected non-empty string for common_name"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        common_name = common_name.strip()

        try:
            validity_days = int(validity_days_raw)
        except TypeError, ValueError:
            return Response(
                {"error": f"Expected integer for validity_days, got '{validity_days_raw}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if validity_days < 1 or validity_days > 36500:
            return Response(
                {"error": f"Expected validity_days between 1 and 36500, got {validity_days}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        key_size_raw: Any = request.data.get("key_size", 4096)
        try:
            key_size = int(key_size_raw)
        except TypeError, ValueError:
            return Response(
                {"error": f"Expected integer for key_size, got '{key_size_raw}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if key_size not in ALLOWED_KEY_SIZES:
            return Response(
                {"error": f"Expected key_size in {ALLOWED_KEY_SIZES}, got {key_size}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cert_pem, key_pem = generate_ca_certificate(
            common_name=common_name,
            validity_days=validity_days,
            key_size=key_size,
        )

        encrypted_key = encrypt_private_key(key_pem)

        CertificateAuthority.objects.filter(is_active=True).update(is_active=False)

        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name=get_certificate_subject(cert_pem),
            fingerprint=get_certificate_fingerprint(cert_pem),
            key_size=key_size,
            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=validity_days),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )

        serializer = CertificateAuthoritySerializer(ca)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Revoke (deactivate) a CA certificate."""
        try:
            ca = CertificateAuthority.objects.get(pk=pk)
        except CertificateAuthority.DoesNotExist:
            return Response(
                {"error": f"Expected valid CA ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not ca.is_active:
            return Response(
                {"error": f"CA '{ca.common_name}' is already inactive"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ca.is_active = False
        ca.save()

        return Response(
            {"detail": f"CA '{ca.common_name}' has been deactivated."},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request: Request) -> Response:
        """Retrieve the currently active CA certificate."""
        ca = CertificateAuthority.objects.filter(is_active=True).first()
        if ca is None:
            return Response(
                {"error": "No active CA certificate found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CertificateAuthoritySerializer(ca)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request: Request, pk: str | None = None) -> DjangoHttpResponse | Response:
        """Download the CA certificate PEM file."""
        try:
            ca = CertificateAuthority.objects.get(pk=pk)
        except CertificateAuthority.DoesNotExist:
            return Response(
                {"error": f"Expected valid CA ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        http_response = DjangoHttpResponse(
            ca.certificate_pem,
            content_type="application/x-pem-file",
        )
        http_response["Content-Disposition"] = f'attachment; filename="{ca.common_name}.pem"'
        return http_response


class ServerCertificateViewSet(viewsets.ViewSet):
    """
    Admin-only server certificate management for MQTT TLS.

    Endpoints:
    - GET /api/admin/pki/server-cert/ — list all server certificates
    - POST /api/admin/pki/server-cert/ — generate a new server certificate
    - DELETE /api/admin/pki/server-cert/{id}/ — deactivate a server certificate
    - GET /api/admin/pki/server-cert/active/ — get the active server certificate
    - GET /api/admin/pki/server-cert/{id}/download/ — download server cert PEM
    - DELETE /api/admin/pki/server-cert/{id}/expunge/ — permanently delete inactive cert
    """

    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        """List all server certificates, most recent first."""
        certs = ServerCertificate.objects.all()
        serializer = ServerCertificateSerializer(certs, many=True)
        return Response(serializer.data)

    def create(self, request: Request) -> Response:
        """Generate a new server certificate signed by the active CA."""
        active_ca = CertificateAuthority.objects.filter(is_active=True).first()
        if active_ca is None:
            return Response(
                {"error": "No active CA certificate. Generate a CA first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        common_name: Any = request.data.get("common_name", "")
        if not isinstance(common_name, str) or not common_name.strip():
            return Response(
                {"error": "Expected non-empty string for common_name"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        common_name = common_name.strip()

        validity_days_raw: Any = request.data.get("validity_days", 1825)
        try:
            validity_days = int(validity_days_raw)
        except TypeError, ValueError:
            return Response(
                {"error": f"Expected integer for validity_days, got '{validity_days_raw}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if validity_days < 1 or validity_days > 36500:
            return Response(
                {"error": f"Expected validity_days between 1 and 36500, got {validity_days}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        key_size_raw: Any = request.data.get("key_size", 4096)
        try:
            key_size = int(key_size_raw)
        except TypeError, ValueError:
            return Response(
                {"error": f"Expected integer for key_size, got '{key_size_raw}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if key_size not in ALLOWED_KEY_SIZES:
            return Response(
                {"error": f"Expected key_size in {ALLOWED_KEY_SIZES}, got {key_size}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        san_entries: Any = request.data.get("san_entries", [])
        if not isinstance(san_entries, list):
            return Response(
                {"error": "Expected list for san_entries"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        san_list = [str(s).strip() for s in san_entries if str(s).strip()]
        if not san_list:
            return Response(
                {"error": "Expected at least one SAN entry (IP or hostname)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only add the request hostname if it is already in ALLOWED_HOSTS.
        # request.get_host() reflects the Host header, which is attacker-controlled;
        # without this check an admin could be tricked into signing a cert that
        # includes an arbitrary domain in its SAN list.
        request_host = request.get_host().split(":")[0]
        if request_host and request_host in settings.ALLOWED_HOSTS and request_host not in san_list:
            san_list.append(request_host)
            logger.info(
                "Auto-included request hostname '%s' in server certificate SANs",
                request_host,
            )

        ca_key_pem = decrypt_private_key(bytes(active_ca.encrypted_private_key))

        cert_pem, server_key_pem = generate_server_certificate(
            ca_cert_pem=active_ca.certificate_pem.encode(),
            ca_key_pem=ca_key_pem,
            common_name=common_name,
            san_entries=san_list,
            validity_days=validity_days,
            key_size=key_size,
        )

        encrypted_key = encrypt_private_key(server_key_pem)

        ServerCertificate.objects.filter(is_active=True).update(is_active=False)

        server_cert = ServerCertificate.objects.create(
            issuing_ca=active_ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name=get_certificate_subject(cert_pem),
            fingerprint=get_certificate_fingerprint(cert_pem),
            san_entries=get_certificate_sans(cert_pem),
            key_size=key_size,
            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=validity_days),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )

        serializer = ServerCertificateSerializer(server_cert)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Deactivate a server certificate."""
        try:
            cert = ServerCertificate.objects.get(pk=pk)
        except ServerCertificate.DoesNotExist:
            return Response(
                {"error": f"Expected valid server cert ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not cert.is_active:
            return Response(
                {"error": f"Server cert '{cert.common_name}' (fingerprint={cert.fingerprint}) is already inactive"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cert.is_active = False
        cert.save()
        return Response(
            {"detail": f"Server cert '{cert.common_name}' (fingerprint={cert.fingerprint}) has been deactivated."},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request: Request) -> Response:
        """Get the currently active server certificate."""
        cert = ServerCertificate.objects.filter(is_active=True).first()
        if cert is None:
            return Response(
                {"error": "No active server certificate found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ServerCertificateSerializer(cert)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request: Request, pk: str | None = None) -> DjangoHttpResponse | Response:
        """Download the server certificate PEM file."""
        try:
            cert = ServerCertificate.objects.get(pk=pk)
        except ServerCertificate.DoesNotExist:
            return Response(
                {"error": f"Expected valid server cert ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        http_response = DjangoHttpResponse(
            cert.certificate_pem,
            content_type="application/x-pem-file",
        )
        http_response["Content-Disposition"] = f'attachment; filename="{cert.common_name}-server.pem"'
        return http_response

    @action(detail=True, methods=["delete"], url_path="expunge")
    def expunge(self, request: Request, pk: str | None = None) -> Response:
        """Permanently delete an inactive server certificate."""
        try:
            cert = ServerCertificate.objects.get(pk=pk)
        except ServerCertificate.DoesNotExist:
            return Response(
                {"error": f"Expected valid server cert ID, got '{pk}' which does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if cert.is_active:
            return Response(
                {"error": "Cannot expunge an active server certificate. Deactivate it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cert_name = cert.common_name
        cert_fingerprint = cert.fingerprint
        cert.delete()
        return Response(
            {"detail": f"Server cert '{cert_name}' (fingerprint={cert_fingerprint}) permanently deleted."},
            status=status.HTTP_200_OK,
        )


class ClientCertificateViewSet(viewsets.ViewSet):
    """
    Admin-only client certificate management for MQTT TLS.

    Endpoints:
    - GET  /api/admin/pki/client-certs/           — list all client certificates
    - POST /api/admin/pki/client-certs/           — issue certificate for a user
    - POST /api/admin/pki/client-certs/{id}/revoke/ — revoke a certificate
    - DELETE /api/admin/pki/client-certs/{id}/expunge/ — permanently delete revoked cert
    - GET  /api/admin/pki/crl/                     — download current CRL
    """

    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        """List all client certificates, most recent first."""
        certs = ClientCertificate.objects.select_related("user", "issuing_ca").all()
        serializer = ClientCertificateSerializer(certs, many=True)
        return Response(serializer.data)

    def create(self, request: Request) -> Response:
        """Issue a new client certificate for a user, signed by the active CA."""
        active_ca = CertificateAuthority.objects.filter(is_active=True).first()
        if active_ca is None:
            return Response(
                {"error": "No active CA certificate. Generate a CA first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id: Any = request.data.get("user_id")
        if user_id is None:
            return Response(
                {"error": "Expected 'user_id' field"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_user = User.objects.get(pk=int(user_id))
        except User.DoesNotExist, ValueError, TypeError:
            return Response(
                {"error": f"Expected valid user ID, got '{user_id}'"},
                status=status.HTTP_404_NOT_FOUND,
            )

        validity_days_raw: Any = request.data.get("validity_days", 1825)
        try:
            validity_days = int(validity_days_raw)
        except TypeError, ValueError:
            return Response(
                {"error": f"Expected integer for validity_days, got '{validity_days_raw}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if validity_days < 1 or validity_days > 36500:
            return Response(
                {"error": f"Expected validity_days between 1 and 36500, got {validity_days}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        key_size_raw: Any = request.data.get("key_size", 4096)
        try:
            key_size = int(key_size_raw)
        except TypeError, ValueError:
            return Response(
                {"error": f"Expected integer for key_size, got '{key_size_raw}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if key_size not in ALLOWED_KEY_SIZES:
            return Response(
                {"error": f"Expected key_size in {ALLOWED_KEY_SIZES}, got {key_size}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ca_key_pem = decrypt_private_key(bytes(active_ca.encrypted_private_key))

        cert_pem, client_key_pem = generate_client_certificate(
            ca_cert_pem=active_ca.certificate_pem.encode(),
            ca_key_pem=ca_key_pem,
            username=str(target_user.username),
            validity_days=validity_days,
            key_size=key_size,
        )

        encrypted_key = encrypt_private_key(client_key_pem)

        ClientCertificate.objects.filter(user=target_user, is_active=True).update(is_active=False)

        serial = get_certificate_serial_number(cert_pem)

        client_cert = ClientCertificate.objects.create(
            user=target_user,
            issuing_ca=active_ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name=get_certificate_subject(cert_pem),
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(serial),
            key_size=key_size,
            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=validity_days),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )

        logger.info(
            "Client certificate issued for user '%s' (serial %s, valid %d days) by admin '%s'",
            target_user.username,
            client_cert.serial_number,
            validity_days,
            request.user.username,
        )
        serializer = ClientCertificateSerializer(client_cert)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke(self, request: Request, pk: str | None = None) -> Response:
        """Revoke a client certificate."""
        try:
            cert = ClientCertificate.objects.get(pk=pk)
        except ClientCertificate.DoesNotExist:
            return Response(
                {"error": f"Expected valid client cert ID, got '{pk}'"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if cert.revoked:
            return Response(
                {"error": f"Certificate for '{cert.common_name}' (fingerprint={cert.fingerprint}) is already revoked"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cert.revoked = True
        cert.is_active = False
        cert.revoked_at = timezone.now()
        cert.save()
        return Response(
            {"detail": f"Certificate for '{cert.common_name}' (fingerprint={cert.fingerprint}) has been revoked."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["delete"], url_path="expunge")
    def expunge(self, request: Request, pk: str | None = None) -> Response:
        """Permanently delete a revoked or inactive client certificate."""
        try:
            cert = ClientCertificate.objects.get(pk=pk)
        except ClientCertificate.DoesNotExist:
            return Response(
                {"error": f"Expected valid client cert ID, got '{pk}'"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if cert.is_active and not cert.revoked:
            return Response(
                {"error": "Cannot expunge an active certificate. Revoke it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cert_name = cert.common_name
        cert_fingerprint = cert.fingerprint
        cert.delete()
        return Response(
            {"detail": f"Certificate for '{cert_name}' (fingerprint={cert_fingerprint}) permanently deleted."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="download")
    def download(self, request: Request, pk: str | None = None) -> DjangoHttpResponse | Response:
        """Download a client certificate as a PKCS#12 (.p12) bundle."""
        try:
            cert = ClientCertificate.objects.select_related("issuing_ca").get(pk=pk)
        except ClientCertificate.DoesNotExist:
            return Response(
                {"error": f"Expected valid client cert ID, got '{pk}'"},
                status=status.HTTP_404_NOT_FOUND,
            )

        password = request.data.get("password", "")
        if not password:
            return Response(
                {"error": "Expected 'password' field for .p12 encryption"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client_key_pem = decrypt_private_key(bytes(cert.encrypted_private_key))
        p12_bytes = generate_pkcs12(
            cert_pem=cert.certificate_pem.encode(),
            key_pem=client_key_pem,
            ca_cert_pem=cert.issuing_ca.certificate_pem.encode(),
            friendly_name=cert.common_name,
            password=str(password).encode(),
        )
        response = DjangoHttpResponse(
            p12_bytes,
            content_type="application/x-pkcs12",
        )
        response["Content-Disposition"] = f'attachment; filename="{cert.common_name}.p12"'
        return response


class CRLViewSet(viewsets.ViewSet):
    """Download the current Certificate Revocation List."""

    permission_classes = [AllowAny]

    def list(self, request: Request) -> DjangoHttpResponse | Response:
        """Generate and return the current CRL signed by the active CA."""
        active_ca = CertificateAuthority.objects.filter(is_active=True).first()
        if active_ca is None:
            return Response(
                {"error": "No active CA certificate"},
                status=status.HTTP_404_NOT_FOUND,
            )

        revoked_certs = ClientCertificate.objects.filter(issuing_ca=active_ca, revoked=True)
        revoked_entries: list[tuple[int, datetime]] = []
        for cert in revoked_certs:
            serial = int(cert.serial_number, 16)
            revoked_at = cert.revoked_at or cert.created_at
            revoked_entries.append((serial, revoked_at))

        ca_key_pem = decrypt_private_key(bytes(active_ca.encrypted_private_key))
        crl_pem = generate_crl(
            ca_cert_pem=active_ca.certificate_pem.encode(),
            ca_key_pem=ca_key_pem,
            revoked_entries=revoked_entries,
        )

        http_response = DjangoHttpResponse(
            crl_pem,
            content_type="application/x-pem-file",
        )
        http_response["Content-Disposition"] = 'attachment; filename="my-tracks.crl"'
        return http_response


class HealthViewSet(viewsets.ViewSet):
    """Lightweight health check for container orchestration and monitoring."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def list(self, request: Request) -> Response:
        """Return health status and version. No auth, no DB queries."""
        try:
            app_version = get_package_version("my-tracks")
        except PackageNotFoundError:
            app_version = "unknown"
        if is_mqtt_degraded():
            return Response(
                {"status": "degraded", "version": app_version, "mqtt": "down"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {"status": "ok", "version": app_version},
            status=status.HTTP_200_OK,
        )


class FriendRequestViewSet(viewsets.ViewSet):
    """
    ViewSet for managing friend requests.

    Provides endpoints for:
    - GET  /friends/requests/         List pending received and sent requests
    - POST /friends/requests/         Send a friend request
    - POST /friends/requests/{id}/accept/   Accept a request
    - POST /friends/requests/{id}/decline/  Decline a request
    - DELETE /friends/requests/{id}/  Cancel a sent request
    """

    permission_classes = [IsAuthenticated]

    def list(self, request: Request) -> Response:
        """List pending friend requests received by and sent by the current user."""
        received_qs = FriendRequest.objects.filter(to_user=request.user, status=FriendRequest.PENDING).select_related(
            "from_user"
        )
        sent_qs = FriendRequest.objects.filter(from_user=request.user, status=FriendRequest.PENDING).select_related(
            "to_user"
        )
        return Response(
            {
                "received": FriendRequestSerializer(received_qs, many=True).data,
                "sent": FriendRequestSerializer(sent_qs, many=True).data,
            }
        )

    def create(self, request: Request) -> Response:
        """Send a friend request to another user."""
        username = str(request.data.get("username") or "").strip()
        auto_accept_reciprocal = bool(request.data.get("auto_accept_reciprocal"))
        if not username:
            return Response({"error": "username is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        if target == request.user:
            return Response(
                {"error": "Cannot send a request to yourself"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Remove any previously declined request so they can re-request.
        FriendRequest.objects.filter(from_user=request.user, to_user=target, status=FriendRequest.DECLINED).delete()

        # Already friends?
        already_friends = (
            FriendRequest.objects.filter(from_user=request.user, to_user=target, status=FriendRequest.ACCEPTED).exists()
            or FriendRequest.objects.filter(
                from_user=target, to_user=request.user, status=FriendRequest.ACCEPTED
            ).exists()
        )
        if already_friends:
            return Response({"error": "Already friends"}, status=status.HTTP_409_CONFLICT)

        incoming_pending = FriendRequest.objects.filter(
            from_user=target, to_user=request.user, status=FriendRequest.PENDING
        ).first()
        if incoming_pending:
            if auto_accept_reciprocal or incoming_pending.auto_accept_reciprocal:
                incoming_pending.status = FriendRequest.ACCEPTED
                incoming_pending.save()
                return Response(FriendRequestSerializer(incoming_pending).data)
            return Response(
                {"error": "A pending request already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        outgoing_pending = FriendRequest.objects.filter(
            from_user=request.user, to_user=target, status=FriendRequest.PENDING
        ).first()
        if outgoing_pending:
            return Response(
                {"error": "A pending request already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        req = FriendRequest.objects.create(
            from_user=request.user,
            to_user=target,
            auto_accept_reciprocal=auto_accept_reciprocal,
        )
        try:
            from app.notifications import send_friend_request_email

            send_friend_request_email(req)
        except Exception:
            logger.exception(
                "Failed to send friend request email (from=%s, to=%s)",
                request.user.username,
                target.username,
            )
        return Response(FriendRequestSerializer(req).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def accept(self, request: Request, pk: str | None = None) -> Response:
        """Accept a received friend request."""
        try:
            req = FriendRequest.objects.get(pk=pk, to_user=request.user)
        except FriendRequest.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if req.status != FriendRequest.PENDING:
            return Response(
                {"error": "Request is not pending"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        req.status = FriendRequest.ACCEPTED
        req.save()

        auto_accept_reciprocal = bool(request.data.get("auto_accept_reciprocal"))
        if auto_accept_reciprocal:
            FriendRequest.objects.update_or_create(
                from_user=request.user,
                to_user=req.from_user,
                defaults={
                    "status": FriendRequest.ACCEPTED,
                    "auto_accept_reciprocal": True,
                },
            )

        return Response(FriendRequestSerializer(req).data)

    @action(detail=True, methods=["post"])
    def decline(self, request: Request, pk: str | None = None) -> Response:
        """Decline a received friend request."""
        try:
            req = FriendRequest.objects.get(pk=pk, to_user=request.user)
        except FriendRequest.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if req.status != FriendRequest.PENDING:
            return Response(
                {"error": "Request is not pending"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        req.status = FriendRequest.DECLINED
        req.save()
        return Response(FriendRequestSerializer(req).data)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Cancel a sent friend request (only the sender can cancel)."""
        try:
            req = FriendRequest.objects.get(pk=pk, from_user=request.user, status=FriendRequest.PENDING)
        except FriendRequest.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        req.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FriendViewSet(viewsets.ViewSet):
    """
    ViewSet for managing accepted friendships.

    Provides endpoints for:
    - GET    /friends/                List accepted friends
    - GET    /friends/user-search/    Search users for friend requests
    - DELETE /friends/{user_id}/      Remove a friend
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="user-search")
    def user_search(self, request: Request) -> Response:
        """Return usernames matching a prefix for the Friends tab autocomplete."""
        from django.db.models import Q

        query = str(request.query_params.get("q") or "").strip()
        if not query:
            return Response([])

        excluded_ids: set[int] = {request.user.id}
        for from_id, to_id in FriendRequest.objects.filter(
            Q(from_user=request.user) | Q(to_user=request.user),
            status__in=[FriendRequest.PENDING, FriendRequest.ACCEPTED],
        ).values_list("from_user_id", "to_user_id"):
            excluded_ids.add(from_id)
            excluded_ids.add(to_id)

        users = User.objects.filter(username__istartswith=query).exclude(pk__in=excluded_ids).order_by("username")[:10]
        payload = [
            {
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
            for user in users
        ]
        return Response(FriendUserSearchSerializer(payload, many=True).data)

    def list(self, request: Request) -> Response:
        """List all accepted friends of the current user."""
        from django.db.models import Q

        accepted = FriendRequest.objects.filter(
            Q(from_user=request.user, status=FriendRequest.ACCEPTED)
            | Q(to_user=request.user, status=FriendRequest.ACCEPTED)
        ).select_related("from_user", "to_user")

        friends = []
        seen_ids: set[int] = set()
        for req in accepted:
            other = req.to_user if req.from_user == request.user else req.from_user
            if other.id in seen_ids:
                continue
            seen_ids.add(other.id)
            friends.append(
                {
                    "user_id": other.id,
                    "username": other.username,
                    "first_name": other.first_name,
                    "last_name": other.last_name,
                }
            )
        return Response(FriendSerializer(friends, many=True).data)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Remove a friend and delete all DeviceShares in both directions."""
        from django.db.models import Q

        try:
            other = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        deleted, _ = FriendRequest.objects.filter(
            Q(from_user=request.user, to_user=other) | Q(from_user=other, to_user=request.user),
            status=FriendRequest.ACCEPTED,
        ).delete()
        if deleted == 0:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # Remove device shares in both directions.
        DeviceShare.objects.filter(device__owner=request.user, shared_with=other).delete()
        DeviceShare.objects.filter(device__owner=other, shared_with=request.user).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceShareViewSet(viewsets.ViewSet):
    """
    ViewSet for managing per-device shares with a specific friend.

    URL params: user_id (friend's pk), device_id (Device.device_id string).

    Provides endpoints for:
    - GET    /friends/{user_id}/shares/             List shares granted to this friend
    - POST   /friends/{user_id}/shares/             Share a device
    - DELETE /friends/{user_id}/shares/{device_id}/ Unshare a device
    """

    permission_classes = [IsAuthenticated]

    def _get_friend(self, request: Request, user_id: str) -> tuple[User | None, Response | None]:
        """Return the friend User or an error Response."""
        from django.db.models import Q

        try:
            friend = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None, Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        is_friend = FriendRequest.objects.filter(
            Q(from_user=request.user, to_user=friend) | Q(from_user=friend, to_user=request.user),
            status=FriendRequest.ACCEPTED,
        ).exists()
        if not is_friend:
            return None, Response(
                {"error": "No accepted friendship with this user"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return friend, None

    def list(self, request: Request, user_id: str = "") -> Response:
        """List devices you have shared with this friend."""
        friend, err = self._get_friend(request, user_id)
        if err:
            return err
        qs = DeviceShare.objects.filter(device__owner=request.user, shared_with=friend).select_related(
            "device", "shared_with"
        )
        return Response(DeviceShareSerializer(qs, many=True).data)

    def create(self, request: Request, user_id: str = "") -> Response:
        """Share one of your devices with this friend."""
        friend, err = self._get_friend(request, user_id)
        if err:
            return err
        device_id = str(request.data.get("device_id") or "").strip()
        if not device_id:
            return Response({"error": "device_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            device = Device.objects.get(device_id=device_id, owner=request.user)
        except Device.DoesNotExist:
            return Response(
                {"error": "Device not found or not owned by you"},
                status=status.HTTP_403_FORBIDDEN,
            )
        share, created = DeviceShare.objects.get_or_create(device=device, shared_with=friend)
        return Response(
            DeviceShareSerializer(share).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def destroy(self, request: Request, user_id: str = "", device_id: str = "") -> Response:
        """Unshare a device from this friend."""
        friend, err = self._get_friend(request, user_id)
        if err:
            return err
        deleted, _ = DeviceShare.objects.filter(
            device__device_id=device_id,
            device__owner=request.user,
            shared_with=friend,
        ).delete()
        if deleted == 0:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
