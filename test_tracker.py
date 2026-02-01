"""
Test suite for OwnTracks location tracking API.

This module contains comprehensive tests for the tracker app,
including model validation, API endpoints, and OwnTracks protocol compatibility.
"""
import pytest
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from rest_framework import status
from rest_framework.test import APIClient
from tracker.models import Device, Location


@pytest.fixture
def api_client() -> APIClient:
    """Provide a DRF API client for testing."""
    return APIClient()


@pytest.fixture
def sample_device(db) -> Device:
    """Create a sample device for testing."""
    return Device.objects.create(
        device_id='TEST01',
        name='Test Device'
    )


@pytest.fixture
def sample_location(db, sample_device: Device) -> Location:
    """Create a sample location for testing."""
    return Location.objects.create(
        device=sample_device,
        latitude=Decimal('37.7749'),
        longitude=Decimal('-122.4194'),
        timestamp=timezone.now(),
        accuracy=10,
        altitude=50,
        velocity=5,
        battery_level=85,
        connection_type='w'
    )


@pytest.mark.django_db
class TestDeviceModel:
    """Tests for Device model."""
    
    def test_device_creation(self) -> None:
        """Test creating a device."""
        device = Device.objects.create(
            device_id='DEV001',
            name='My Phone'
        )
        assert device.device_id == 'DEV001'
        assert device.name == 'My Phone'
        assert device.created_at is not None
        assert device.last_seen is not None
    
    def test_device_str_representation(self) -> None:
        """Test string representation of device."""
        device = Device.objects.create(
            device_id='DEV002',
            name='Test Device'
        )
        assert str(device) == 'Test Device (DEV002)'
    
    def test_device_str_without_name(self) -> None:
        """Test string representation when name is empty."""
        device = Device.objects.create(device_id='DEV003')
        assert str(device) == 'DEV003'
    
    def test_device_unique_constraint(self) -> None:
        """Test that device_id must be unique."""
        Device.objects.create(device_id='UNIQUE01')
        with pytest.raises(Exception):  # IntegrityError
            Device.objects.create(device_id='UNIQUE01')


@pytest.mark.django_db
class TestLocationModel:
    """Tests for Location model."""
    
    def test_location_creation(self, sample_device: Device) -> None:
        """Test creating a location."""
        timestamp = timezone.now()
        location = Location.objects.create(
            device=sample_device,
            latitude=Decimal('40.7128'),
            longitude=Decimal('-74.0060'),
            timestamp=timestamp,
            accuracy=15,
            battery_level=90
        )
        assert location.device == sample_device
        assert location.latitude == Decimal('40.7128')
        assert location.longitude == Decimal('-74.0060')
        assert location.timestamp == timestamp
        assert location.accuracy == 15
        assert location.battery_level == 90
    
    def test_location_str_representation(self, sample_location: Location) -> None:
        """Test string representation of location."""
        result = str(sample_location)
        assert 'TEST01' in result
        assert '37.7749' in result
        assert '-122.4194' in result


@pytest.mark.django_db
class TestLocationAPI:
    """Tests for Location API endpoints."""
    
    def test_create_location_owntracks_format(self, api_client: APIClient) -> None:
        """Test creating location with OwnTracks JSON format."""
        payload = {
            "_type": "location",
            "lat": 37.7749,
            "lon": -122.4194,
            "tst": int(datetime.now().timestamp()),
            "acc": 10,
            "alt": 50,
            "vel": 5,
            "batt": 85,
            "tid": "AB",
            "conn": "w"
        }
        
        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
        
        # Verify device was created
        device = Device.objects.get(device_id='AB')
        assert device is not None
        
        # Verify location was created
        location = Location.objects.get(device=device)
        assert location.latitude == Decimal('37.7749')
        assert location.longitude == Decimal('-122.4194')
        assert location.accuracy == 10
        assert location.battery_level == 85
    
    def test_create_location_minimal_payload(self, api_client: APIClient) -> None:
        """Test creating location with minimal required fields."""
        payload = {
            "lat": 40.7128,
            "lon": -74.0060,
            "tst": int(datetime.now().timestamp()),
            "tid": "CD"
        }
        
        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
    
    def test_create_location_invalid_latitude(self, api_client: APIClient) -> None:
        """Test that invalid latitude is rejected."""
        payload = {
            "lat": 91.0,  # Invalid: > 90
            "lon": 0.0,
            "tst": int(datetime.now().timestamp()),
            "tid": "EF"
        }
        
        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'latitude' in str(response.data).lower()
    
    def test_create_location_invalid_longitude(self, api_client: APIClient) -> None:
        """Test that invalid longitude is rejected."""
        payload = {
            "lat": 0.0,
            "lon": 181.0,  # Invalid: > 180
            "tst": int(datetime.now().timestamp()),
            "tid": "GH"
        }
        
        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'longitude' in str(response.data).lower()
    
    def test_create_location_invalid_battery(self, api_client: APIClient) -> None:
        """Test that invalid battery level is rejected."""
        payload = {
            "lat": 0.0,
            "lon": 0.0,
            "tst": int(datetime.now().timestamp()),
            "tid": "IJ",
            "batt": 150  # Invalid: > 100
        }
        
        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'battery' in str(response.data).lower()
    
    def test_non_location_message(self, api_client: APIClient) -> None:
        """Test handling of non-location OwnTracks messages (status, waypoint, etc)."""
        from tracker.models import OwnTracksMessage
        
        payload = {
            "_type": "status",
            "tid": "XY",
            "status": {"battery": 75}
        }
        
        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
        
        # Verify message was stored
        message = OwnTracksMessage.objects.get(message_type='status')
        assert message.payload['_type'] == 'status'
        assert message.device is not None
        assert message.device.device_id == 'XY'
    
    def test_list_locations(self, api_client: APIClient, sample_location: Location) -> None:
        """Test listing locations."""
        response = api_client.get('/api/locations/')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert len(response.data['results']) >= 1
    
    def test_filter_locations_by_device(
        self,
        api_client: APIClient,
        sample_device: Device
    ) -> None:
        """Test filtering locations by device."""
        # Create locations for different devices
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('1.0'),
            longitude=Decimal('1.0'),
            timestamp=timezone.now()
        )
        
        other_device = Device.objects.create(device_id='OTHER')
        Location.objects.create(
            device=other_device,
            latitude=Decimal('2.0'),
            longitude=Decimal('2.0'),
            timestamp=timezone.now()
        )
        
        response = api_client.get(
            '/api/locations/',
            {'device': 'TEST01'}
        )
        
        assert response.status_code == status.HTTP_200_OK
        results = response.data['results']
        assert all(loc['device'] == sample_device.id for loc in results)
    
    def test_filter_locations_by_date_range(
        self,
        api_client: APIClient,
        sample_device: Device
    ) -> None:
        """Test filtering locations by date range."""
        now = timezone.now()
        
        # Create locations at different times
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('1.0'),
            longitude=Decimal('1.0'),
            timestamp=now - timedelta(days=2)
        )
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('2.0'),
            longitude=Decimal('2.0'),
            timestamp=now - timedelta(days=1)
        )
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('3.0'),
            longitude=Decimal('3.0'),
            timestamp=now
        )
        
        # Filter for last day
        start_date = (now - timedelta(days=1, hours=1)).isoformat()
        response = api_client.get(
            '/api/locations/',
            {'start_date': start_date}
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) == 2


@pytest.mark.django_db
class TestDeviceAPI:
    """Tests for Device API endpoints."""
    
    def test_list_devices(self, api_client: APIClient, sample_device: Device) -> None:
        """Test listing devices."""
        response = api_client.get('/api/devices/')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert len(response.data['results']) >= 1
    
    def test_get_device_detail(self, api_client: APIClient, sample_device: Device) -> None:
        """Test retrieving device details."""
        response = api_client.get(f'/api/devices/{sample_device.device_id}/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['device_id'] == 'TEST01'
        assert response.data['name'] == 'Test Device'
    
    def test_get_device_locations(
        self,
        api_client: APIClient,
        sample_device: Device,
        sample_location: Location
    ) -> None:
        """Test getting locations for a specific device."""
        response = api_client.get(
            f'/api/devices/{sample_device.device_id}/locations/'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert len(response.data['results']) >= 1
