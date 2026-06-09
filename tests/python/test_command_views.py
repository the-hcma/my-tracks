"""Tests for the Command API views."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from hamcrest import assert_that, equal_to, has_entries
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Device
from app.views import CommandViewSet


class TestCommandViewSetReportLocation(TestCase):
    """Tests for CommandViewSet report_location endpoint."""

    def setUp(self) -> None:
        """Set up test user, device, and authenticated client."""
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice_rl", password="pw")
        self.device = Device.objects.create(device_id="phone", owner=self.user, mqtt_user="alice_mqtt")
        self.client.force_authenticate(user=self.user)

    def test_report_location_missing_device_id(self) -> None:
        """report_location without device_id returns 400."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_report_location_empty_device_id(self) -> None:
        """report_location with empty device_id returns 400."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={"device_id": ""},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_report_location_device_not_found(self) -> None:
        """Unknown device_id returns 400."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={"device_id": "nonexistent"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Device 'nonexistent' not found"))

    def test_report_location_device_not_found_slash_format(self) -> None:
        """Unknown device in user/device format returns 400."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={"device_id": "alice_rl/unknown"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Device 'alice_rl/unknown' not found"))

    def test_report_location_broker_unavailable(self) -> None:
        """Known device reaches MQTT stage and returns 503 when no broker."""
        response = self.client.post(
            "/api/commands/report-location/",
            data={"device_id": "phone"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))

    def test_report_location_uses_mqtt_user_for_topic(self) -> None:
        """report_location uses the device's stored mqtt_user, not the input prefix."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)

        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = self.client.post(
                "/api/commands/report-location/",
                data={"device_id": "wrongprefix/phone"},
                format="json",
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("alice_mqtt/phone"))

    def test_report_location_plain_device_id_resolves_via_db(self) -> None:
        """Plain device_id (no slash) resolves through DB lookup and uses stored mqtt_user."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)

        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = self.client.post(
                "/api/commands/report-location/",
                data={"device_id": "phone"},
                format="json",
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("alice_mqtt/phone"))


class TestCommandViewSetSessionAuth(TestCase):
    """Browser-style session + CSRF auth for command endpoints."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="browser_user", password="pw")
        self.device = Device.objects.create(device_id="phone", owner=self.user, mqtt_user="browser_mqtt")
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_authenticate(user=self.user)

    @patch("app.auth.get_command_api_key", return_value="command-secret")
    def test_report_location_requires_csrf_when_api_key_configured(self, _mock_key: Any) -> None:
        """Session-authenticated POST without CSRF is rejected (browser must send token)."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            "/api/commands/report-location/",
            data='{"device_id": "phone"}',
            content_type="application/json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    @patch("app.auth.get_command_api_key", return_value="command-secret")
    def test_report_location_accepts_session_with_csrf(self, _mock_key: Any) -> None:
        """Session-authenticated POST with CSRF succeeds when API key is configured."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)

        csrf_token = "test-csrf-token"
        with patch("django.middleware.csrf.get_token", return_value=csrf_token):
            with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
                response = self.client.post(
                    "/api/commands/report-location/",
                    data={"device_id": "phone"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf_token,
                )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("browser_mqtt/phone"))


class TestCommandViewSetSetWaypoints(TestCase):
    """Tests for CommandViewSet set_waypoints endpoint."""

    def setUp(self) -> None:
        """Set up test user, device, and authenticated client."""
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice_sw", password="pw")
        self.device = Device.objects.create(device_id="phone", owner=self.user, mqtt_user="alice_sw_mqtt")
        self.client.force_authenticate(user=self.user)

    def test_set_waypoints_missing_device_id(self) -> None:
        """set_waypoints without device_id returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1}]},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_set_waypoints_missing_waypoints(self) -> None:
        """set_waypoints without waypoints returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "phone"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "waypoints must be a non-empty list"}))

    def test_set_waypoints_empty_list(self) -> None:
        """set_waypoints with empty list returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "phone", "waypoints": []},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "waypoints must be a non-empty list"}))

    def test_set_waypoints_invalid_type(self) -> None:
        """set_waypoints with non-list waypoints returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "phone", "waypoints": "not a list"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "waypoints must be a non-empty list"}))

    def test_set_waypoints_device_not_found(self) -> None:
        """Unknown device_id returns 400."""
        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={
                "device_id": "nonexistent",
                "waypoints": [{"desc": "Home", "lat": 51.5, "lon": -0.1}],
            },
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Device 'nonexistent' not found"))

    def test_set_waypoints_broker_unavailable(self) -> None:
        """Known device reaches MQTT stage and returns 503 when no broker."""
        waypoints = [{"desc": "Home", "lat": 51.5074, "lon": -0.1278, "rad": 100}]

        response = self.client.post(
            "/api/commands/set-waypoints/",
            data={"device_id": "phone", "waypoints": waypoints},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))

    def test_set_waypoints_uses_mqtt_user_for_topic(self) -> None:
        """set_waypoints uses the device's stored mqtt_user for the MQTT topic."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)
        waypoints = [{"desc": "Home", "lat": 51.5074, "lon": -0.1278, "rad": 100}]

        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = self.client.post(
                "/api/commands/set-waypoints/",
                data={"device_id": "wrongprefix/phone", "waypoints": waypoints},
                format="json",
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("alice_sw_mqtt/phone"))


class TestCommandViewSetClearWaypoints(TestCase):
    """Tests for CommandViewSet clear_waypoints endpoint."""

    def setUp(self) -> None:
        """Set up test user, device, and authenticated client."""
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice_cw", password="pw")
        self.device = Device.objects.create(device_id="phone", owner=self.user, mqtt_user="alice_cw_mqtt")
        self.client.force_authenticate(user=self.user)

    def test_clear_waypoints_missing_device_id(self) -> None:
        """clear_waypoints without device_id returns 400."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_clear_waypoints_empty_device_id(self) -> None:
        """clear_waypoints with empty device_id returns 400."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={"device_id": ""},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_clear_waypoints_device_not_found(self) -> None:
        """Unknown device_id returns 400."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={"device_id": "nonexistent"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Device 'nonexistent' not found"))

    def test_clear_waypoints_broker_unavailable(self) -> None:
        """Known device reaches MQTT stage and returns 503 when no broker."""
        response = self.client.post(
            "/api/commands/clear-waypoints/",
            data={"device_id": "phone"},
            format="json",
        )

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))

    def test_clear_waypoints_uses_mqtt_user_for_topic(self) -> None:
        """clear_waypoints uses the device's stored mqtt_user for the MQTT topic."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)

        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = self.client.post(
                "/api/commands/clear-waypoints/",
                data={"device_id": "wrongprefix/phone"},
                format="json",
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("alice_cw_mqtt/phone"))


class TestCommandViewSetFetchWaypoints(TestCase):
    """Tests for CommandViewSet fetch_waypoints endpoint."""

    def setUp(self) -> None:
        """Set up test client and fixtures."""
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice_fw", password="pw")
        self.device = Device.objects.create(device_id="pixel7", owner=self.user, mqtt_user="alice_fw_mqtt")
        self.client.force_authenticate(user=self.user)

    def test_fetch_waypoints_missing_device_id(self) -> None:
        """fetch_waypoints without device_id returns 400."""
        response = self.client.post(
            "/api/commands/fetch-waypoints/",
            data={},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries({"error": "device_id is required"}))

    def test_fetch_waypoints_plain_device_id_not_found(self) -> None:
        """fetch_waypoints with unknown plain device_id returns 400."""
        response = self.client.post(
            "/api/commands/fetch-waypoints/",
            data={"device_id": "nonexistent"},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["error"], equal_to("Device 'nonexistent' not found"))

    def test_fetch_waypoints_broker_unavailable(self) -> None:
        """Known device (plain device_id) reaches MQTT stage and returns 503 when no broker."""
        response = self.client.post(
            "/api/commands/fetch-waypoints/",
            data={"device_id": "pixel7"},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))

    def test_fetch_waypoints_slash_format_broker_unavailable(self) -> None:
        """fetch_waypoints with user/device format resolves device and returns 503 when no broker."""
        response = self.client.post(
            "/api/commands/fetch-waypoints/",
            data={"device_id": "alice_fw/pixel7"},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["error"], equal_to("MQTT broker not available"))

    def test_fetch_waypoints_uses_mqtt_user_for_topic(self) -> None:
        """fetch_waypoints uses the device's stored mqtt_user for the MQTT topic."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)

        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = self.client.post(
                "/api/commands/fetch-waypoints/",
                data={"device_id": "wrongprefix/pixel7"},
                format="json",
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("alice_fw_mqtt/pixel7"))

    def test_fetch_waypoints_plain_device_id_uses_mqtt_user(self) -> None:
        """Plain device_id resolves through DB and uses stored mqtt_user in response."""
        mock_publisher = MagicMock()
        mock_publisher.send_command = AsyncMock(return_value=True)

        with patch.object(CommandViewSet, "_get_publisher", return_value=mock_publisher):
            response = self.client.post(
                "/api/commands/fetch-waypoints/",
                data={"device_id": "pixel7"},
                format="json",
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["device_id"], equal_to("alice_fw_mqtt/pixel7"))
