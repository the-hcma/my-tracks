"""Tests for the Command API views."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import TestCase
from hamcrest import (assert_that, contains_string, equal_to, has_entries,
                      has_key)
from rest_framework import status
from rest_framework.test import APIClient


class TestCommandViewSetReportLocation(TestCase):
    """Tests for CommandViewSet report_location endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        self.client = APIClient()

    def test_report_location_missing_device_id(self) -> None:
        """Test report_location without device_id returns 400."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_report_location_empty_device_id(self) -> None:
        """Test report_location with empty device_id returns 400."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={"device_id": ""},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_report_location_broker_unavailable(self) -> None:
        """Test report_location when broker is unavailable returns 503."""
        # CommandPublisher without a client will raise RuntimeError
        response = self.client.post(
            "/api/commands/report-location/",
            data={"device_id": "alice/phone"},
            format="json",
        )

        # Since there's no broker running, should get 503
        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json(), has_key("error"))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))


class TestCommandViewSetSetWaypoints(TestCase):
    """Tests for CommandViewSet set_waypoints endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        self.client = APIClient()

    def test_set_waypoints_missing_device_id(self) -> None:
        """Test set_waypoints without device_id returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1}]},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_set_waypoints_missing_waypoints(self) -> None:
        """Test set_waypoints without waypoints returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "alice/phone"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(
            response.json(), has_entries({"error": "waypoints must be a non-empty list"})
        )

    def test_set_waypoints_empty_list(self) -> None:
        """Test set_waypoints with empty list returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "alice/phone", "waypoints": []},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(
            response.json(), has_entries({"error": "waypoints must be a non-empty list"})
        )

    def test_set_waypoints_invalid_type(self) -> None:
        """Test set_waypoints with non-list waypoints returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "alice/phone", "waypoints": "not a list"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(
            response.json(), has_entries({"error": "waypoints must be a non-empty list"})
        )

    def test_set_waypoints_broker_unavailable(self) -> None:
        """Test set_waypoints when broker is unavailable returns 503."""
        waypoints = [
            {"desc": "Home", "lat": 51.5074, "lon": -0.1278, "rad": 100},
        ]

        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "alice/phone", "waypoints": waypoints},
            format="json",
        )

        # Since there's no broker running, should get 503
        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json(), has_key("error"))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))


class TestCommandViewSetClearWaypoints(TestCase):
    """Tests for CommandViewSet clear_waypoints endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        self.client = APIClient()

    def test_clear_waypoints_missing_device_id(self) -> None:
        """Test clear_waypoints without device_id returns 400."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_clear_waypoints_empty_device_id(self) -> None:
        """Test clear_waypoints with empty device_id returns 400."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={"device_id": ""},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_clear_waypoints_broker_unavailable(self) -> None:
        """Test clear_waypoints when broker is unavailable returns 503."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={"device_id": "alice/phone"},
            format="json",
        )

        # Since there's no broker running, should get 503
        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json(), has_key("error"))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))
