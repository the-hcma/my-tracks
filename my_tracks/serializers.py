"""
Serializers for OwnTracks location tracking API.

This module provides DRF serializers for converting between
OwnTracks JSON payloads and Django model instances.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from rest_framework import serializers

from .models import Device, Location

logger = logging.getLogger(__name__)


class DeviceSerializer(serializers.ModelSerializer):
    """Serializer for Device model."""

    location_count = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = ['id', 'device_id', 'name', 'created_at', 'last_seen', 'location_count']
        read_only_fields = ['id', 'created_at', 'last_seen']

    def get_location_count(self, obj: Device) -> int:
        """Get the total number of locations for this device."""
        return obj.locations.count()


class LocationSerializer(serializers.ModelSerializer):
    """
    Serializer for Location model.

    Handles both OwnTracks format (for incoming data) and
    standard format (for API responses).
    """

    device_id = serializers.CharField(write_only=True, required=False)
    tid = serializers.CharField(write_only=True, required=False, help_text="OwnTracks tracker ID")
    topic = serializers.CharField(write_only=True, required=False, help_text="OwnTracks topic path")
    lat = serializers.DecimalField(
        max_digits=15,
        decimal_places=10,
        write_only=True,
        required=False,
        help_text="OwnTracks latitude field"
    )
    lon = serializers.DecimalField(
        max_digits=15,
        decimal_places=10,
        write_only=True,
        required=False,
        help_text="OwnTracks longitude field"
    )
    long = serializers.DecimalField(
        max_digits=15,
        decimal_places=10,
        write_only=True,
        required=False,
        help_text="OwnTracks longitude field (alternative name)"
    )
    tst = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="OwnTracks Unix timestamp"
    )
    acc = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="OwnTracks accuracy"
    )
    alt = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="OwnTracks altitude"
    )
    vel = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="OwnTracks velocity"
    )
    batt = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="OwnTracks battery level"
    )
    conn = serializers.CharField(
        write_only=True,
        required=False,
        max_length=1,
        help_text="OwnTracks connection type"
    )
    _type = serializers.CharField(
        write_only=True,
        required=False,
        help_text="OwnTracks message type"
    )

    # Custom read-only fields for UI display
    device_name = serializers.SerializerMethodField()
    device_id_display = serializers.SerializerMethodField()
    tid_display = serializers.SerializerMethodField()
    timestamp_unix = serializers.SerializerMethodField()

    def get_device_name(self, obj: Location) -> str:
        """Return the device name for display."""
        # Return custom name if set, otherwise just the device_id
        if obj.device.name and not obj.device.name.startswith('Device '):
            return obj.device.name
        return obj.device.device_id

    def get_device_id_display(self, obj: Location) -> str:
        """Return the device ID for display."""
        return obj.device.device_id

    def get_tid_display(self, obj: Location) -> str:
        """Return the tracker ID (tid) from the original message if available."""
        return str(obj.tracker_id) if obj.tracker_id else ""

    def get_timestamp_unix(self, obj: Location) -> int:
        """Return timestamp as Unix timestamp for JavaScript."""
        return int(obj.timestamp.timestamp())

    class Meta:
        model = Location
        fields = [
            'id', 'device', 'device_id', 'tid', 'topic', 'device_name', 'device_id_display', 'tid_display', 'timestamp_unix',
            'latitude', 'longitude', 'timestamp',
            'lat', 'lon', 'long', 'tst',
            'accuracy', 'altitude', 'velocity', 'battery_level', 'connection_type',
            'acc', 'alt', 'vel', 'batt', 'conn', '_type',
            'ip_address', 'received_at'
        ]
        read_only_fields = [
            'id', 'device', 'received_at', 'ip_address',
            'latitude', 'longitude', 'timestamp',
            'accuracy', 'altitude', 'velocity', 'battery_level', 'connection_type'
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Validate and transform OwnTracks format to internal format.

        Converts OwnTracks field names (lat, lon, tst, etc.) to
        Django model field names (latitude, longitude, timestamp, etc.).

        Args:
            attrs: Input attributes from request

        Returns:
            Validated and transformed attributes

        Raises:
            serializers.ValidationError: If required fields are missing or invalid
        """
        logger.debug("Received OwnTracks data: %s (keys: %s)", attrs, list(attrs.keys()))

        # Device identification - prioritize topic over tid
        device_id = attrs.get('device_id')

        # Extract device ID from topic if present (format: owntracks/user/deviceid)
        if not device_id and 'topic' in attrs:
            topic = attrs.get('topic', '')
            parts = topic.split('/')
            if len(parts) >= 3:
                device_id = parts[-1]  # Get last part of topic path
                logger.info(f"Extracted device_id '{device_id}' from topic '{topic}'")

        # Fallback to tid if no topic available
        if not device_id:
            device_id = attrs.get('tid')

        if not device_id:
            logger.error("Missing device_id, topic, or tid field")
            raise serializers.ValidationError(
                "Expected 'device_id', 'topic', or 'tid' field for device identification, got neither"
            )

        # Get or create device
        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={'name': f'Device {device_id}'}
        )

        # Always log device connections (special case - always appears)
        client_ip = self.context.get('client_ip', 'unknown')
        if created:
            logger.info("New device connected: %s from %s", device_id, client_ip)
        else:
            logger.debug("Device reconnected: %s from %s", device_id, client_ip)

        # Map OwnTracks fields to model fields
        # Use explicit None check for longitude to handle 0 values correctly
        lon_value = attrs.get('lon')
        if lon_value is None:
            lon_value = attrs.get('long')

        tst_value = attrs.get('tst')
        if tst_value is None:
            raise serializers.ValidationError("Expected timestamp field ('tst'), got None")

        transformed = {
            'device': device,
            'latitude': attrs.get('lat'),
            'longitude': lon_value,  # Support both 'lon' and 'long'
            'timestamp': datetime.fromtimestamp(float(tst_value), tz=UTC),
            'accuracy': attrs.get('acc'),
            'altitude': attrs.get('alt'),
            'velocity': attrs.get('vel'),
            'battery_level': attrs.get('batt'),
            'connection_type': attrs.get('conn', ''),
            'tracker_id': attrs.get('tid', ''),
        }

        logger.debug("Transformed data: %s", transformed)

        # Validate required fields
        if transformed['latitude'] is None:
            raise serializers.ValidationError(
                "Expected latitude field ('lat'), got None"
            )
        if transformed['longitude'] is None:
            raise serializers.ValidationError(
                "Expected longitude field ('lon' or 'long'), got None"
            )

        # Validate latitude range
        if not -90 <= transformed['latitude'] <= 90:
            logger.error(f"Invalid latitude: {transformed['latitude']}")
            raise serializers.ValidationError(
                f"Expected latitude between -90 and +90 degrees, got {transformed['latitude']}"
            )

        # Validate longitude range
        if not -180 <= transformed['longitude'] <= 180:
            raise serializers.ValidationError(
                f"Expected longitude between -180 and +180 degrees, got {transformed['longitude']}"
            )

        # Validate battery level if provided
        if transformed['battery_level'] is not None:
            if not 0 <= transformed['battery_level'] <= 100:
                raise serializers.ValidationError(
                    f"Expected battery level between 0 and 100, got {transformed['battery_level']}"
                )

        return transformed

    def create(self, validated_data: dict[str, Any]) -> Location:
        """Create location instance with IP address from context."""
        # Get IP address from context if available
        client_ip = self.context.get('client_ip')
        if client_ip:
            validated_data['ip_address'] = client_ip

        return super().create(validated_data)