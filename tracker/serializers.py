"""
Serializers for OwnTracks location tracking API.

This module provides DRF serializers for converting between
OwnTracks JSON payloads and Django model instances.
"""
from rest_framework import serializers
from typing import Dict, Any
from datetime import datetime
from django.utils import timezone
import logging
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
    lat = serializers.DecimalField(
        max_digits=10,
        decimal_places=7,
        write_only=True,
        required=False,
        help_text="OwnTracks latitude field"
    )
    lon = serializers.DecimalField(
        max_digits=10,
        decimal_places=7,
        write_only=True,
        required=False,
        help_text="OwnTracks longitude field"
    )
    long = serializers.DecimalField(
        max_digits=10,
        decimal_places=7,
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
    timestamp_unix = serializers.SerializerMethodField()
    
    def get_device_name(self, obj: Location) -> str:
        """Return the device ID for display."""
        return obj.device.device_id
    
    def get_timestamp_unix(self, obj: Location) -> int:
        """Return timestamp as Unix timestamp for JavaScript."""
        return int(obj.timestamp.timestamp())
    
    class Meta:
        model = Location
        fields = [
            'id', 'device', 'device_id', 'tid', 'device_name', 'timestamp_unix',
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
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
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
        # Debug logging
        print("="*80)
        print("🔍 Received OwnTracks data:")
        print(f"📦 Raw attrs: {attrs}")
        print(f"🔑 Available keys: {list(attrs.keys())}")
        print("="*80)
        
        logger.info("="*80)
        logger.info("Received OwnTracks data:")
        logger.info(f"Raw attrs: {attrs}")
        logger.info(f"Available keys: {list(attrs.keys())}")
        logger.info("="*80)
        
        # Device identification
        device_id = attrs.get('device_id') or attrs.get('tid')
        if not device_id:
            logger.error("Missing device_id or tid field")
            raise serializers.ValidationError(
                "Expected 'device_id' or 'tid' field for device identification, got neither"
            )
        
        # Get or create device
        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={'name': f'Device {device_id}'}
        )
        
        # Always log device connections (special case - always appears)
        client_ip = self.context.get('client_ip', 'unknown')
        if created:
            # Use print to bypass log level filtering for device connections
            print(f"🔌 New device connected: {device_id} from {client_ip}")
            logger.info(f"New device connected: {device_id} from {client_ip}")
        else:
            # Use print for reconnections too
            print(f"🔌 Device reconnected: {device_id} from {client_ip}")
            logger.debug(f"Device reconnected: {device_id} from {client_ip}")
        
        # Map OwnTracks fields to model fields
        # Use explicit None check for longitude to handle 0 values correctly
        lon_value = attrs.get('lon')
        if lon_value is None:
            lon_value = attrs.get('long')
        
        transformed = {
            'device': device,
            'latitude': attrs.get('lat'),
            'longitude': lon_value,  # Support both 'lon' and 'long'
            'timestamp': timezone.make_aware(datetime.fromtimestamp(attrs.get('tst'))),
            'accuracy': attrs.get('acc'),
            'altitude': attrs.get('alt'),
            'velocity': attrs.get('vel'),
            'battery_level': attrs.get('batt'),
            'connection_type': attrs.get('conn', ''),
        }
        
        print(f"✅ Transformed data: {transformed}")
        logger.info(f"Transformed data: {transformed}")
        
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
    def create(self, validated_data):
        """Create location instance with IP address from context."""
        # Get IP address from context if available
        client_ip = self.context.get('client_ip')
        if client_ip:
            validated_data['ip_address'] = client_ip
        
        return super().create(validated_data)