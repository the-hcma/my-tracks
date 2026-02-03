"""
Test suite for OwnTracks location tracking API.

This module contains comprehensive tests for the tracker app,
including model validation, API endpoints, and OwnTracks protocol compatibility.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from hamcrest import (all_of, assert_that, contains_string, equal_to,
                      greater_than_or_equal_to, has_key, has_length, is_not,
                      none)
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient

from tracker.models import Device, Location


@pytest.fixture
def api_client() -> APIClient:
    """Provide a DRF API client for testing."""
    return APIClient()


@pytest.fixture
def sample_device(db: Any) -> Device:
    """Create a sample device for testing."""
    return Device.objects.create(
        device_id='TEST01',
        name='Test Device'
    )


@pytest.fixture
def sample_location(db: Any, sample_device: Device) -> Location:
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
        assert_that(device.device_id, equal_to('DEV001'))
        assert_that(device.name, equal_to('My Phone'))
        assert_that(device.created_at, is_not(none()))
        assert_that(device.last_seen, is_not(none()))

    def test_device_str_representation(self) -> None:
        """Test string representation of device."""
        device = Device.objects.create(
            device_id='DEV002',
            name='Test Device'
        )
        assert_that(str(device), equal_to('Test Device (DEV002)'))

    def test_device_str_without_name(self) -> None:
        """Test string representation when name is empty."""
        device = Device.objects.create(device_id='DEV003')
        assert_that(str(device), equal_to('DEV003'))

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
        assert_that(location.device, equal_to(sample_device))
        assert_that(location.latitude, equal_to(Decimal('40.7128')))
        assert_that(location.longitude, equal_to(Decimal('-74.0060')))
        assert_that(location.timestamp, equal_to(timestamp))
        assert_that(location.accuracy, equal_to(15))
        assert_that(location.battery_level, equal_to(90))

    def test_location_str_representation(self, sample_location: Location) -> None:
        """Test string representation of location."""
        result = str(sample_location)
        assert_that(result, contains_string('TEST01'))
        assert_that(result, contains_string('37.7749'))
        assert_that(result, contains_string('-122.4194'))

    def test_coordinate_precision_from_schema(self) -> None:
        """Test that coordinate precision can be extracted from model schema.

        This tests the mechanism used by the frontend to derive collapse precision
        from the database schema, ensuring it doesn't rely on hardcoded values.
        """
        lat_field = Location._meta.get_field('latitude')
        lon_field = Location._meta.get_field('longitude')

        # Verify both fields have the same precision
        assert_that(lat_field.decimal_places, equal_to(lon_field.decimal_places))

        # Verify precision is defined (not None)
        assert_that(lat_field.decimal_places, is_not(none()))

        # Verify precision is reasonable (at least 5 for ~1m accuracy)
        assert_that(lat_field.decimal_places, greater_than_or_equal_to(5))

        # Test the collapse precision calculation (same logic as in urls.py)
        db_decimal_places = lat_field.decimal_places or 10
        collapse_precision = min(db_decimal_places, 5)
        assert_that(collapse_precision, equal_to(5))


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

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, equal_to([]))

        # Verify device was created
        device = Device.objects.get(device_id='AB')
        assert_that(device, is_not(none()))

        # Verify location was created
        location = Location.objects.get(device=device)
        assert_that(location.latitude, equal_to(Decimal('37.7749')))
        assert_that(location.longitude, equal_to(Decimal('-122.4194')))
        assert_that(location.accuracy, equal_to(10))
        assert_that(location.battery_level, equal_to(85))

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

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, equal_to([]))

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

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(str(response.data).lower(), contains_string('latitude'))

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

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(str(response.data).lower(), contains_string('longitude'))

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

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(str(response.data).lower(), contains_string('battery'))

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

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, equal_to([]))

        # Verify message was stored
        message = OwnTracksMessage.objects.get(message_type='status')
        assert_that(message.payload['_type'], equal_to('status'))
        assert_that(message.device, is_not(none()))
        if message.device:  # Type guard for Pylance
            assert_that(message.device.device_id, equal_to('XY'))

    def test_create_location_with_topic(self, api_client: APIClient) -> None:
        """Test that device ID is extracted from topic field."""
        payload = {
            "lat": 37.7749,
            "lon": -122.4194,
            "tst": int(datetime.now().timestamp()),
            "tid": "xy",  # Should be ignored in favor of topic
            "topic": "owntracks/user/hcma"
        }

        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )

        # OwnTracks expects 200, not 201
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        # Verify device was created with ID from topic, not tid
        device = Device.objects.get(device_id='hcma')
        assert_that(device.device_id, equal_to('hcma'))

        # Verify location was created for correct device
        location = Location.objects.latest('id')
        assert_that(location.device.device_id, equal_to('hcma'))

    def test_non_location_message_with_topic(self, api_client: APIClient) -> None:
        """Test that non-location messages extract device ID from topic."""
        from tracker.models import OwnTracksMessage

        payload = {
            "_type": "status",
            "topic": "owntracks/user/testdevice",
            "status": {"battery": 75}
        }

        response = api_client.post(
            '/api/locations/',
            payload,
            format='json'
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, equal_to([]))

        # Verify message was stored with device from topic
        message = OwnTracksMessage.objects.get(message_type='status')
        assert_that(message.device, is_not(none()))
        if message.device:  # Type guard for Pylance
            assert_that(message.device.device_id, equal_to('testdevice'))

    def test_list_locations(self, api_client: APIClient, sample_location: Location) -> None:
        """Test listing locations."""
        response = api_client.get('/api/locations/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_key('results'))
        assert_that(response.data['results'], has_length(greater_than_or_equal_to(1)))

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

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.data['results']
        for loc in results:
            assert_that(loc['device'], equal_to(sample_device.id))

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

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['results'], has_length(2))

    def test_filter_locations_by_unix_timestamp(
        self,
        api_client: APIClient,
        sample_device: Device
    ) -> None:
        """Test filtering locations by Unix timestamp (start_time)."""
        now = timezone.now()

        # Create locations at different times
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('1.0'),
            longitude=Decimal('1.0'),
            timestamp=now - timedelta(hours=3)
        )
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('2.0'),
            longitude=Decimal('2.0'),
            timestamp=now - timedelta(hours=1)
        )
        Location.objects.create(
            device=sample_device,
            latitude=Decimal('3.0'),
            longitude=Decimal('3.0'),
            timestamp=now
        )

        # Test filtering by start_time (Unix timestamp)
        start_time = int((now - timedelta(hours=2)).timestamp())
        response = api_client.get(
            '/api/locations/',
            {'start_time': start_time, 'device': sample_device.device_id}
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.data['results']
        assert_that(results, has_length(2))  # Should get last 2 locations within 2 hours


@pytest.mark.django_db
class TestDeviceAPI:
    """Tests for Device API endpoints."""

    def test_list_devices(self, api_client: APIClient, sample_device: Device) -> None:
        """Test listing devices."""
        response = api_client.get('/api/devices/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_key('results'))
        assert_that(response.data['results'], has_length(greater_than_or_equal_to(1)))

    def test_get_device_detail(self, api_client: APIClient, sample_device: Device) -> None:
        """Test retrieving device details."""
        response = api_client.get(f'/api/devices/{sample_device.device_id}/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['device_id'], equal_to('TEST01'))
        assert_that(response.data['name'], equal_to('Test Device'))

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

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_key('results'))
        assert_that(response.data['results'], has_length(greater_than_or_equal_to(1)))


@pytest.mark.django_db
class TestResolutionThinning:
    """Test cases for the resolution-based waypoint thinning feature."""

    def test_resolution_always_includes_first_and_last_points(
        self, api_client: APIClient, sample_device: Device
    ) -> None:
        """Test that coarse resolution always includes first and last waypoints."""
        base_time = timezone.now() - timedelta(hours=1)

        # Create 10 locations, one every 2 minutes
        locations = []
        for i in range(10):
            loc = Location.objects.create(
                device=sample_device,
                latitude=Decimal('37.7749') + Decimal(str(i * 0.001)),
                longitude=Decimal('-122.4194'),
                timestamp=base_time + timedelta(minutes=i * 2),
                accuracy=10
            )
            locations.append(loc)

        # Request with 6-minute resolution (should get ~3-4 points: first, middle, last)
        start_time = int((base_time - timedelta(minutes=1)).timestamp())
        response = api_client.get(
            f'/api/locations/?device={sample_device.device_id}'
            f'&start_time={start_time}&resolution=360'
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.data['results']

        # Must have at least 2 points (first and last)
        assert_that(len(results), greater_than_or_equal_to(2))

        # Results are returned newest first (descending order)
        # First result should be the newest (last location)
        # Last result should be the oldest (first location)
        first_result_ts = results[0]['timestamp_unix']
        last_result_ts = results[-1]['timestamp_unix']

        first_location_ts = int(locations[0].timestamp.timestamp())
        last_location_ts = int(locations[-1].timestamp.timestamp())

        assert_that(first_result_ts, equal_to(last_location_ts))  # newest first
        assert_that(last_result_ts, equal_to(first_location_ts))  # oldest last

    def test_resolution_thins_to_expected_interval(
        self, api_client: APIClient, sample_device: Device
    ) -> None:
        """Test that resolution parameter thins waypoints to expected intervals."""
        base_time = timezone.now() - timedelta(hours=1)

        # Create 60 locations, one every minute (simulating 1 hour of data)
        for i in range(60):
            Location.objects.create(
                device=sample_device,
                latitude=Decimal('37.7749') + Decimal(str(i * 0.0001)),
                longitude=Decimal('-122.4194'),
                timestamp=base_time + timedelta(minutes=i),
                accuracy=10
            )

        # Request with 6-minute resolution (360 seconds)
        # Should get ~10 points per hour plus first/last
        start_time = int((base_time - timedelta(minutes=1)).timestamp())
        response = api_client.get(
            f'/api/locations/?device={sample_device.device_id}'
            f'&start_time={start_time}&resolution=360'
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.data['results']

        # Should have roughly 10-12 points (60 min / 6 min = 10, plus first/last)
        assert_that(len(results), greater_than_or_equal_to(10))
        # But much less than the original 60
        assert_that(len(results), is_not(greater_than_or_equal_to(30)))

    def test_medium_resolution_thins_to_three_minute_interval(
        self, api_client: APIClient, sample_device: Device
    ) -> None:
        """Test that medium resolution (180s) provides ~20 points per hour."""
        base_time = timezone.now() - timedelta(hours=1)

        # Create 60 locations, one every minute (simulating 1 hour of data)
        for i in range(60):
            Location.objects.create(
                device=sample_device,
                latitude=Decimal('37.7749') + Decimal(str(i * 0.0001)),
                longitude=Decimal('-122.4194'),
                timestamp=base_time + timedelta(minutes=i),
                accuracy=10
            )

        # Request with 3-minute resolution (180 seconds)
        # Should get ~20 points per hour plus first/last
        start_time = int((base_time - timedelta(minutes=1)).timestamp())
        response = api_client.get(
            f'/api/locations/?device={sample_device.device_id}'
            f'&start_time={start_time}&resolution=180'
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        results = response.data['results']

        # Should have roughly 20-22 points (60 min / 3 min = 20, plus first/last)
        assert_that(len(results), greater_than_or_equal_to(18))
        # But less than 40 (proving it's thinning)
        assert_that(len(results), is_not(greater_than_or_equal_to(40)))
        # And more than coarse (which gives ~10)
        assert_that(len(results), greater_than_or_equal_to(15))

    def test_resolution_zero_returns_all_points(
        self, api_client: APIClient, sample_device: Device
    ) -> None:
        """Test that resolution=0 does not thin waypoints."""
        base_time = timezone.now() - timedelta(hours=1)

        # Create 5 locations
        for i in range(5):
            Location.objects.create(
                device=sample_device,
                latitude=Decimal('37.7749'),
                longitude=Decimal('-122.4194'),
                timestamp=base_time + timedelta(minutes=i),
                accuracy=10
            )

        start_time = int((base_time - timedelta(minutes=1)).timestamp())

        # Request with resolution=0 should return all points via normal pagination
        response = api_client.get(
            f'/api/locations/?device={sample_device.device_id}'
            f'&start_time={start_time}&resolution=0'
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        # resolution=0 should not apply thinning (uses normal response)
        results = response.data['results']
        assert_that(len(results), equal_to(5))


@pytest.mark.django_db
class TestHomeView:
    """Tests for the home page view."""

    def test_home_page_includes_collapse_precision(self, api_client: APIClient) -> None:
        """Test that the home page includes the collapse precision derived from DB."""
        response = api_client.get('/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        # The response content should contain the precision configuration
        content = response.content.decode('utf-8')

        # Verify the PRECISION constant is set to 5 (derived from DB schema)
        assert_that(content, contains_string('const PRECISION = 5'))

        # Verify the comment explaining the precision source
        assert_that(content, contains_string('Precision from DB schema'))
