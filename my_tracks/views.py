"""
API views for OwnTracks location tracking.

This module provides REST API endpoints for receiving location data
from OwnTracks clients and querying stored location history.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from .models import Device, Location, OwnTracksMessage
from .serializers import DeviceSerializer, LocationSerializer

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class LocationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing location data.

    Provides endpoints for:
    - POST: Receive location data from OwnTracks clients
    - GET: Query location history
    - Filter by device, date range, etc.
    """

    queryset = Location.objects.all()
    serializer_class = LocationSerializer
    permission_classes = [AllowAny]

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
        # Get client IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(',')[0]
        else:
            client_ip = request.META.get('REMOTE_ADDR')

        logger.info("Incoming location request from: %s", client_ip)
        logger.debug("Request data: %s, Content-Type: %s", request.data, request.content_type)

        # Check message type
        msg_type = request.data.get('_type', 'location')

        if msg_type != 'location':
            logger.info("Received non-location message type: %s, storing", msg_type)

            # Try to identify the device - prioritize topic over tid
            device = None
            device_id = None

            # Convert request.data to dict for type-safe access
            raw_data = request.data
            field_name_to_value: dict[str, Any] = {
                str(k): v for k, v in (raw_data.items() if hasattr(raw_data, 'items') else [])
            }

            # Extract from topic first (format: owntracks/user/deviceid)
            if 'topic' in field_name_to_value:
                topic = str(field_name_to_value['topic'])
                parts = topic.split('/')
                if len(parts) >= 3:
                    device_id = parts[-1]

            # Fallback to tid
            if not device_id:
                device_id = field_name_to_value.get('tid')

            if device_id:
                device, created = Device.objects.get_or_create(
                    device_id=device_id,
                    defaults={'name': f'Device {device_id}'}
                )
                # Always log device connections (special case - always appears)
                if created:
                    logger.info("New device connected: %s from %s", device_id, client_ip)
                else:
                    logger.debug("Device reconnected: %s from %s", device_id, client_ip)

            # Store the message
            OwnTracksMessage.objects.create(
                device=device,
                message_type=msg_type,
                payload=field_name_to_value,
                ip_address=client_ip
            )

            # OwnTracks expects an empty JSON array response
            return Response([], status=status.HTTP_200_OK)

        # Extract device_id from topic if present (format: owntracks/user/deviceid)
        raw_data = request.data
        field_name_to_value: dict[str, Any] = {
            str(k): v for k, v in (raw_data.items() if hasattr(raw_data, 'items') else [])
        }
        if 'topic' in field_name_to_value and 'device_id' not in field_name_to_value:
            topic = str(field_name_to_value['topic'])
            parts = topic.split('/')
            if len(parts) >= 3:
                field_name_to_value['device_id'] = parts[-1]  # Get last part of topic path
                logger.info(f"Extracted device_id '{parts[-1]}' from topic '{topic}'")

        serializer = self.get_serializer(data=field_name_to_value, context={'client_ip': client_ip})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # Broadcast new location via WebSocket
        location_data = serializer.data
        channel_layer = get_channel_layer()
        if channel_layer:
            try:
                logger.info(
                    f"📡 Broadcasting location to WebSocket (id={location_data.get('id')}, device={location_data.get('device_id_display')})"
                )
                async_to_sync(channel_layer.group_send)(
                    "locations",
                    {
                        "type": "location_update",
                        "data": location_data
                    }
                )
                logger.info(
                    f"✅ WebSocket broadcast completed for location {location_data.get('id')}"
                )
            except Exception as e:
                logger.error(
                    "WebSocket broadcast failed",
                    extra={"location_id": location_data.get("id"), "error": str(e)},
                    exc_info=True
                )
        else:
            logger.warning("WebSocket broadcast skipped: no channel layer configured")

        # OwnTracks expects an empty JSON array response
        return Response([], status=status.HTTP_200_OK)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        List location history with optional filtering.

        Query parameters:
        - device: Filter by device ID
        - start_date: ISO 8601 datetime (e.g., 2024-01-01T00:00:00Z)
        - end_date: ISO 8601 datetime
        - limit: Maximum number of results

        Args:
            request: HTTP request with query parameters

        Returns:
            Paginated list of location records
        """
        queryset = self.get_queryset()

        # Filter by device
        device_id = request.query_params.get('device')
        if device_id:
            try:
                device = Device.objects.get(device_id=device_id)
                queryset = queryset.filter(device=device)
            except Device.DoesNotExist:
                return Response(
                    {
                        'error': f"Expected valid device ID, got '{device_id}' which does not exist"
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

        # Filter by date range
        start_date = request.query_params.get('start_date')
        start_time = request.query_params.get('start_time')  # Unix timestamp

        if start_time:
            try:
                start_timestamp = int(start_time)
                start_dt = datetime.fromtimestamp(start_timestamp, tz=UTC)
                queryset = queryset.filter(timestamp__gte=start_dt)
            except (ValueError, OSError) as e:
                return Response(
                    {
                        'error': f"Expected Unix timestamp for start_time, got invalid value: {e}"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                queryset = queryset.filter(timestamp__gte=start_dt)
            except ValueError as e:
                return Response(
                    {
                        'error': f"Expected ISO 8601 datetime for start_date, got invalid format: {e}"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        end_date = request.query_params.get('end_date')
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                queryset = queryset.filter(timestamp__lte=end_dt)
            except ValueError as e:
                return Response(
                    {
                        'error': f"Expected ISO 8601 datetime for end_date, got invalid format: {e}"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Apply resolution-based thinning (for coarse mode)
        # resolution parameter specifies minimum seconds between waypoints
        # resolution=0 means return all points (no thinning) but bypass pagination
        resolution = request.query_params.get('resolution')
        if resolution is not None:
            try:
                resolution_seconds = int(resolution)
                # Get all matching locations ordered by timestamp (ascending for thinning)
                all_locations = list(queryset.order_by('timestamp'))
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
                    return Response({
                        'results': serializer.data,
                        'count': len(result_locations),
                        'resolution_applied': resolution_seconds
                    })
            except ValueError:
                return Response(
                    {
                        'error': f"Expected integer for resolution, got '{resolution}'"
                    },
                    status=status.HTTP_400_BAD_REQUEST
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
    - GET /devices/: List all devices
    - GET /devices/{id}/: Get device details
    - GET /devices/{id}/locations/: Get locations for specific device
    """

    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    lookup_field = 'device_id'

    @action(detail=True, methods=['get'])
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

    permission_classes = [AllowAny]  # TODO: Add proper authentication

    def _get_publisher(self) -> Any:
        """Get the command publisher from the global broker instance."""
        # Import here to avoid circular imports
        from my_tracks.mqtt.commands import CommandPublisher

        # For now, return a publisher without a client
        # In production, this would be connected to the running broker
        return CommandPublisher()

    @action(detail=False, methods=['post'], url_path='report-location')
    def report_location(self, request: Request) -> Response:
        """
        Request a device to report its current location.

        Request body:
            {
                "device_id": "user/device"
            }

        Returns:
            200: Command sent successfully
            400: Missing device_id or invalid format
            503: MQTT broker not available
        """
        device_id = request.data.get('device_id')
        if not device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        publisher = self._get_publisher()

        # Import async utilities
        from asgiref.sync import async_to_sync as a2s

        from my_tracks.mqtt.commands import Command

        try:
            success = a2s(publisher.send_command)(
                device_id,
                Command.report_location(),
            )
        except RuntimeError as e:
            logger.warning("MQTT broker not available: %s", e)
            return Response(
                {"error": "MQTT broker not available", "detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if success:
            return Response(
                {"status": "command_sent", "device_id": device_id, "command": "reportLocation"},
                status=status.HTTP_200_OK,
            )
        return Response(
            {"error": "Failed to send command", "device_id": device_id},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=['post'], url_path='set-waypoints')
    def set_waypoints(self, request: Request) -> Response:
        """
        Set waypoints/regions on a device.

        Request body:
            {
                "device_id": "user/device",
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
            400: Missing required fields or invalid format
            503: MQTT broker not available
        """
        device_id = request.data.get('device_id')
        waypoints = request.data.get('waypoints')

        if not device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not waypoints or not isinstance(waypoints, list):
            return Response(
                {"error": "waypoints must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        publisher = self._get_publisher()

        from asgiref.sync import async_to_sync as a2s

        from my_tracks.mqtt.commands import Command

        try:
            success = a2s(publisher.send_command)(
                device_id,
                Command.set_waypoints(waypoints),
            )
        except RuntimeError as e:
            logger.warning("MQTT broker not available: %s", e)
            return Response(
                {"error": "MQTT broker not available", "detail": str(e)},
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

    @action(detail=False, methods=['post'], url_path='clear-waypoints')
    def clear_waypoints(self, request: Request) -> Response:
        """
        Clear all waypoints from a device.

        Request body:
            {
                "device_id": "user/device"
            }

        Returns:
            200: Command sent successfully
            400: Missing device_id or invalid format
            503: MQTT broker not available
        """
        device_id = request.data.get('device_id')
        if not device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        publisher = self._get_publisher()

        from asgiref.sync import async_to_sync as a2s

        from my_tracks.mqtt.commands import Command

        try:
            success = a2s(publisher.send_command)(
                device_id,
                Command.clear_waypoints(),
            )
        except RuntimeError as e:
            logger.warning("MQTT broker not available: %s", e)
            return Response(
                {"error": "MQTT broker not available", "detail": str(e)},
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

