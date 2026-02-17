"""Tests for web_ui views."""

import pytest
from django.test import Client
from hamcrest import assert_that, contains_string, equal_to, has_key
from rest_framework import status


@pytest.mark.django_db
class TestWebUIViews:
    """Test the web UI view functions."""

    def test_home_view_returns_html(self) -> None:
        """Test that the home view returns HTML content."""
        client = Client()
        response = client.get('/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], contains_string('text/html'))

    def test_home_view_contains_expected_elements(self) -> None:
        """Test that the home view contains expected HTML elements."""
        client = Client()
        response = client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('<!DOCTYPE html>'))
        assert_that(content, contains_string('<title>My Tracks - OwnTracks Backend</title>'))
        assert_that(content, contains_string('leaflet'))  # Map library

    def test_home_view_no_cache_headers(self) -> None:
        """Test that the home view sets no-cache headers."""
        client = Client()
        response = client.get('/')

        assert_that(response['Cache-Control'], contains_string('no-cache'))
        assert_that(response['Pragma'], equal_to('no-cache'))
        assert_that(response['Expires'], equal_to('0'))

    def test_health_endpoint_returns_ok(self) -> None:
        """Test that the health endpoint returns status ok."""
        client = Client()
        response = client.get('/health/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = response.json()
        assert_that(data, has_key('status'))
        assert_that(data['status'], equal_to('ok'))

    def test_network_info_returns_expected_fields(self) -> None:
        """Test that network_info returns required fields."""
        client = Client()
        response = client.get('/network-info/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = response.json()
        assert_that(data, has_key('hostname'))
        assert_that(data, has_key('local_ip'))
        assert_that(data, has_key('port'))
        assert_that(data['port'], equal_to(8080))


@pytest.mark.django_db
class TestNetworkState:
    """Test the NetworkState helper class."""

    def test_get_current_ip_returns_string(self) -> None:
        """Test that get_current_ip returns an IP address string."""
        from web_ui.views import NetworkState

        ip = NetworkState.get_current_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_check_and_update_ip_returns_tuple(self) -> None:
        """Test that check_and_update_ip returns (ip, changed) tuple."""
        from web_ui.views import NetworkState

        # Reset state for clean test
        NetworkState.last_known_ip = None

        ip, changed = NetworkState.check_and_update_ip()
        assert isinstance(ip, str)
        assert isinstance(changed, bool)
        # First call should not show change
        assert_that(changed, equal_to(False))

    def test_check_and_update_ip_detects_change(self) -> None:
        """Test that check_and_update_ip detects IP changes."""
        from web_ui.views import NetworkState

        # Set a fake previous IP
        NetworkState.last_known_ip = "192.168.0.1"

        # Current IP should be different (unless by coincidence)
        current_ip = NetworkState.get_current_ip()
        if current_ip != "192.168.0.1":
            ip, changed = NetworkState.check_and_update_ip()
            assert_that(changed, equal_to(True))

    def test_check_and_update_ip_no_change_when_same(self) -> None:
        """Test that check_and_update_ip shows no change when IP is same."""
        from web_ui.views import NetworkState

        # Set current IP as last known
        current_ip = NetworkState.get_current_ip()
        NetworkState.last_known_ip = current_ip

        ip, changed = NetworkState.check_and_update_ip()
        assert_that(changed, equal_to(False))
        assert_that(ip, equal_to(current_ip))


@pytest.mark.django_db
class TestMQTTEndpointDisplay:
    """Test MQTT endpoint display in web UI."""

    def test_home_view_shows_http_enabled(self) -> None:
        """Test that home view shows HTTP server as enabled."""
        client = Client()
        response = client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('HTTP Server'))
        # HTTP is always enabled (you're viewing the page)
        assert_that(content, contains_string('● Enabled'))

    def test_home_view_shows_mqtt_disabled_by_default(self) -> None:
        """Test that home view shows MQTT disabled when port < 0."""
        from unittest.mock import patch

        client = Client()
        with patch('web_ui.views.get_mqtt_port', return_value=-1):
            response = client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('○ Disabled'))
        assert_that(content, contains_string('--mqtt-port 1883'))

    def test_home_view_shows_mqtt_enabled(self) -> None:
        """Test that home view shows MQTT info when enabled."""
        from unittest.mock import patch

        client = Client()
        with (
            patch('web_ui.views.get_mqtt_port', return_value=1883),
            patch('web_ui.views.get_actual_mqtt_port', return_value=None),
        ):
            response = client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('● Enabled'))
        assert_that(content, contains_string('1883'))
        assert_that(content, contains_string('MQTT Broker'))

    def test_home_view_shows_actual_mqtt_port(self) -> None:
        """Test that home view shows actual port when OS-allocated."""
        from unittest.mock import patch

        client = Client()
        with (
            patch('web_ui.views.get_mqtt_port', return_value=0),
            patch('web_ui.views.get_actual_mqtt_port', return_value=54321),
        ):
            response = client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('54321'))

    def test_home_view_shows_mqtt_config_instructions(self) -> None:
        """Test that home view shows MQTT configuration instructions when enabled."""
        from unittest.mock import patch

        client = Client()
        with (
            patch('web_ui.views.get_mqtt_port', return_value=1883),
            patch('web_ui.views.get_actual_mqtt_port', return_value=None),
        ):
            response = client.get('/')

        content = response.content.decode('utf-8')
        # Should show MQTT mode option
        assert_that(content, contains_string('MQTT (Recommended)'))
        assert_that(content, contains_string('For MQTT Mode'))
        # Should also show HTTP mode option
        assert_that(content, contains_string('For HTTP Mode'))
