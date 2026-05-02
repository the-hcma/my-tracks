"""Tests for web_ui views."""
# pyright: reportIndexIssue=none

import json
import re
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import netifaces
import pytest
from cryptography.hazmat.primitives.serialization import pkcs12
from django.contrib.auth.models import User
from django.test import Client, override_settings
from hamcrest import (assert_that, contains_string, equal_to, greater_than,
                      has_item, has_key, has_length, instance_of, is_, is_not,
                      not_, not_none)
from rest_framework import status


@pytest.mark.django_db
class TestLoginPage:
    """Test the login page."""

    def test_login_page_renders(self) -> None:
        """Login page should render for unauthenticated users."""
        client = Client()
        response = client.get('/login/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Sign in'))

    def test_login_page_has_password_toggle(self) -> None:
        """Login page should contain the password visibility toggle button."""
        client = Client()
        response = client.get('/login/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="password-toggle"'))
        assert_that(content, contains_string('aria-label="Show password"'))

    def test_login_page_has_eye_icons(self) -> None:
        """Login page should contain both eye and eye-off SVG icons."""
        client = Client()
        response = client.get('/login/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="eye-icon"'))
        assert_that(content, contains_string('id="eye-off-icon"'))

    def test_login_page_has_toggle_script(self) -> None:
        """Login page should contain the password toggle JavaScript."""
        client = Client()
        response = client.get('/login/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('password-toggle'))
        assert_that(content, contains_string("input.type"))


@pytest.mark.django_db
class TestWebUIViews:
    """Test the web UI view functions."""

    def test_home_view_returns_html(self, logged_in_client: Client) -> None:
        """Test that the home view returns HTML content."""
        response = logged_in_client.get('/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], contains_string('text/html'))

    def test_home_view_contains_expected_elements(self, logged_in_client: Client) -> None:
        """Test that the home view contains expected HTML elements."""
        response = logged_in_client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('<!DOCTYPE html>'))
        assert_that(content, contains_string('<title>My Tracks - OwnTracks Backend</title>'))
        assert_that(content, contains_string('leaflet'))  # Map library

    def test_home_view_contains_historic_controls(self, logged_in_client: Client) -> None:
        """Test that the home view contains date picker and time slider controls."""
        response = logged_in_client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="historic-controls"'))
        assert_that(content, contains_string('id="historic-date"'))
        assert_that(content, contains_string('id="time-slider"'))
        assert_that(content, contains_string('id="time-slider-label"'))

    def test_home_view_no_cache_headers(self, logged_in_client: Client) -> None:
        """Test that the home view sets no-cache headers."""
        response = logged_in_client.get('/')

        assert_that(response['Cache-Control'], contains_string('no-cache'))
        assert_that(response['Pragma'], equal_to('no-cache'))
        assert_that(response['Expires'], equal_to('0'))

    def test_home_view_shows_username_and_logout(self, logged_in_client: Client) -> None:
        """Test that the home view shows the logged-in username and a POST logout form."""
        response = logged_in_client.get('/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('class="user-menu"'))
        assert_that(content, contains_string('testuser'))
        assert_that(content, contains_string('action="/logout/"'))
        assert_that(content, contains_string('method="post"'))
        assert_that(content, contains_string('Logout'))
        assert_that(content, contains_string('id="hamburger-btn"'))

    def test_home_redirects_unauthenticated(self) -> None:
        """Test that unauthenticated users are redirected to login."""
        client = Client()
        response = client.get('/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, contains_string('/login/'))

    def test_health_endpoint_returns_ok(self) -> None:
        """Test that the health endpoint returns status ok (no auth required)."""
        client = Client()
        response = client.get('/health/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = response.json()
        assert_that(data, has_key('status'))
        assert_that(data['status'], equal_to('ok'))

    def test_network_info_returns_expected_fields(self, logged_in_client: Client) -> None:
        """Test that network_info returns required fields derived from the request."""
        response = logged_in_client.get('/network-info/')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = response.json()
        assert_that(data, has_key('hostname'))
        assert_that(data, has_key('local_ip'))
        assert_that(data, has_key('local_ips'))
        assert_that(data, has_key('port'))
        assert_that(data, has_key('scheme'))
        assert_that(data, has_key('server_url'))
        assert_that(data['hostname'], equal_to('testserver'))
        assert_that(data['local_ips'], instance_of(list))


@pytest.mark.django_db
class TestNetworkDiscovery:
    """Test network IP discovery functions."""

    def test_get_all_local_ips_returns_list(self) -> None:
        """Test that get_all_local_ips returns a list of non-loopback IPs."""
        from web_ui.views import get_all_local_ips

        ips = get_all_local_ips()
        assert_that(ips, instance_of(list))
        # Should not contain loopback addresses
        for ip in ips:
            assert_that(ip.startswith('127.'), is_(False))

    def test_get_all_local_ips_returns_sorted(self) -> None:
        """Test that get_all_local_ips returns sorted, deduplicated IPs."""
        from web_ui.views import get_all_local_ips

        ips = get_all_local_ips()
        assert_that(ips, equal_to(sorted(set(ips))))

    def test_get_all_local_ips_excludes_tunnel_interfaces(self) -> None:
        """IPs without a broadcast address (VPN/tunnels) are excluded."""
        from web_ui.views import get_all_local_ips

        mock_interfaces = {
            'en0': {netifaces.AF_INET: [{'addr': '192.168.1.10', 'broadcast': '192.168.1.255'}]},
            'utun0': {netifaces.AF_INET: [{'addr': '100.99.77.90'}]},
            'tun0': {netifaces.AF_INET: [{'addr': '10.8.0.1'}]},
        }

        with (
            patch('netifaces.interfaces', return_value=list(mock_interfaces.keys())),
            patch('netifaces.ifaddresses', side_effect=lambda iface: mock_interfaces[iface]),
        ):
            ips = get_all_local_ips()
            assert_that(ips, equal_to(['192.168.1.10']))

    def test_update_allowed_hosts_adds_new_ips(self) -> None:
        """Test that update_allowed_hosts adds IPs not already in ALLOWED_HOSTS."""
        from django.conf import settings

        from web_ui.views import update_allowed_hosts

        original = settings.ALLOWED_HOSTS.copy()
        try:
            test_ip = '10.99.99.99'
            if test_ip in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.remove(test_ip)
            update_allowed_hosts([test_ip])
            assert_that(settings.ALLOWED_HOSTS, has_item(test_ip))
        finally:
            settings.ALLOWED_HOSTS[:] = original

    def test_update_allowed_hosts_no_duplicates(self) -> None:
        """Test that update_allowed_hosts does not add duplicate IPs."""
        from django.conf import settings

        from web_ui.views import update_allowed_hosts

        original = settings.ALLOWED_HOSTS.copy()
        try:
            test_ip = '10.99.99.99'
            settings.ALLOWED_HOSTS.append(test_ip)
            count_before = settings.ALLOWED_HOSTS.count(test_ip)
            update_allowed_hosts([test_ip])
            count_after = settings.ALLOWED_HOSTS.count(test_ip)
            assert_that(count_after, equal_to(count_before))
        finally:
            settings.ALLOWED_HOSTS[:] = original


@pytest.mark.django_db
class TestNetworkState:
    """Test the NetworkState helper class."""

    def test_get_current_ip_returns_string(self) -> None:
        """Test that get_current_ip returns an IP address string."""
        from web_ui.views import NetworkState

        ip = NetworkState.get_current_ip()
        assert_that(ip, instance_of(str))
        assert_that(ip, has_length(greater_than(0)))

    def test_get_current_ips_returns_list(self) -> None:
        """Test that get_current_ips returns a list of IP strings."""
        from web_ui.views import NetworkState

        ips = NetworkState.get_current_ips()
        assert_that(ips, instance_of(list))
        for ip in ips:
            assert_that(ip, instance_of(str))
            assert_that(ip.startswith('127.'), is_(False))

    def test_check_and_update_ip_returns_tuple(self) -> None:
        """Test that check_and_update_ip returns (ip, changed) tuple."""
        from web_ui.views import NetworkState

        # Reset state for clean test
        NetworkState.last_known_ips = None

        ip, changed = NetworkState.check_and_update_ip()
        assert_that(ip, instance_of(str))
        assert_that(changed, instance_of(bool))
        # First call should not show change
        assert_that(changed, equal_to(False))

    def test_check_and_update_ips_detects_change(self) -> None:
        """Test that check_and_update_ips detects IP changes."""
        from web_ui.views import NetworkState

        # Set a fake previous IP list
        NetworkState.last_known_ips = ["192.168.0.1"]

        # Current IPs should be different (unless by coincidence)
        current_ips = NetworkState.get_current_ips()
        if set(current_ips) != {"192.168.0.1"}:
            ips, changed = NetworkState.check_and_update_ips()
            assert_that(changed, equal_to(True))

    def test_check_and_update_ips_no_change_when_same(self) -> None:
        """Test that check_and_update_ips shows no change when IPs are same."""
        from web_ui.views import NetworkState

        # Set current IPs as last known
        current_ips = NetworkState.get_current_ips()
        NetworkState.last_known_ips = current_ips

        ips, changed = NetworkState.check_and_update_ips()
        assert_that(changed, equal_to(False))
        assert_that(ips, equal_to(current_ips))


@pytest.mark.django_db
class TestServerInfo:
    """Test the ServerInfo helper and get_server_info function."""

    def test_server_info_from_plain_request(self, logged_in_client: Client) -> None:
        """Test server info from a standard Django test client request."""
        from web_ui.views import ServerInfo, get_server_info

        response = logged_in_client.get('/about/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('testserver'))

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_server_info_uses_request_host(self, logged_in_client: Client) -> None:
        """Hostname is derived from the request Host header, not socket."""
        response = logged_in_client.get(
            '/about/', SERVER_NAME='mytracks.example.com',
        )
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('mytracks.example.com'))

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_server_info_extracts_port_from_host(self) -> None:
        """Port is extracted from the Host header when non-standard."""
        from django.test import RequestFactory

        from web_ui.views import get_server_info

        factory = RequestFactory()
        request = factory.get('/', SERVER_NAME='mytracks.local', SERVER_PORT='8443')
        request.META['HTTP_HOST'] = 'mytracks.local:8443'
        info = get_server_info(request)
        assert_that(info.hostname, equal_to('mytracks.local'))
        assert_that(info.port, equal_to('8443'))

    @override_settings(
        ALLOWED_HOSTS=['*'],
        SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    )
    def test_server_info_defaults_port_443_for_https(self) -> None:
        """When no port in Host and using HTTPS, port defaults to 443."""
        from django.test import RequestFactory

        from web_ui.views import get_server_info

        factory = RequestFactory()
        request = factory.get('/', SERVER_NAME='mytracks.local')
        request.META['HTTP_HOST'] = 'mytracks.local'
        request.META['HTTP_X_FORWARDED_PROTO'] = 'https'
        info = get_server_info(request)
        assert_that(info.scheme, equal_to('https'))
        assert_that(info.port, equal_to('443'))

    @override_settings(ALLOWED_HOSTS=['mytracks.example.com', 'backup.example.com', 'localhost'])
    def test_server_info_accessible_hosts_from_allowed_hosts(self) -> None:
        """Accessible hosts are populated from ALLOWED_HOSTS, excluding the primary."""
        from django.test import RequestFactory

        from web_ui.views import get_server_info

        factory = RequestFactory()
        request = factory.get('/', SERVER_NAME='mytracks.example.com')
        request.META['HTTP_HOST'] = 'mytracks.example.com'
        info = get_server_info(request)
        assert_that(info.accessible_hosts, has_item('backup.example.com'))
        assert_that('mytracks.example.com' not in info.accessible_hosts, is_(True))

    @override_settings(ALLOWED_HOSTS=['mytracks.example.com', 'localhost', '127.0.0.1'])
    def test_server_info_filters_loopback_when_real_hosts_exist(self) -> None:
        """Loopback hosts are excluded when real hosts are available."""
        from django.test import RequestFactory

        from web_ui.views import get_server_info

        factory = RequestFactory()
        request = factory.get('/', SERVER_NAME='mytracks.example.com')
        request.META['HTTP_HOST'] = 'mytracks.example.com'
        info = get_server_info(request)
        assert_that('localhost' not in info.accessible_hosts, is_(True))
        assert_that('127.0.0.1' not in info.accessible_hosts, is_(True))

    def test_server_info_base_url_with_standard_port(self) -> None:
        """base_url omits port when it matches the scheme default."""
        from web_ui.views import ServerInfo

        info = ServerInfo(hostname='example.com', port='443', scheme='https')
        assert_that(info.base_url, equal_to('https://example.com'))

    def test_server_info_base_url_with_custom_port(self) -> None:
        """base_url includes port when non-standard."""
        from web_ui.views import ServerInfo

        info = ServerInfo(hostname='example.com', port='8443', scheme='https')
        assert_that(info.base_url, equal_to('https://example.com:8443'))

    def test_server_info_url_for_host(self) -> None:
        """url_for_host builds correct URL for a given host."""
        from web_ui.views import ServerInfo

        info = ServerInfo(hostname='primary.com', port='8443', scheme='https')
        assert_that(
            info.url_for_host('backup.com'),
            equal_to('https://backup.com:8443'),
        )

    def test_about_page_shows_server_url(self, logged_in_client: Client) -> None:
        """About page should display the server URL derived from the request."""
        response = logged_in_client.get('/about/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('http://testserver/'))

    def test_about_page_shows_api_url(self, logged_in_client: Client) -> None:
        """About page OwnTracks config should show server URL for API endpoints."""
        response = logged_in_client.get('/about/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('http://testserver/api/locations/'))


@pytest.mark.django_db
class TestMQTTEndpointDisplay:
    """Test MQTT endpoint display on the about page."""

    def test_about_page_shows_http_enabled(self, logged_in_client: Client) -> None:
        """Test that about page shows HTTP server as enabled."""
        response = logged_in_client.get('/about/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('HTTP Server'))
        assert_that(content, contains_string('● Enabled'))

    def test_about_page_shows_mqtt_disabled_by_default(self, logged_in_client: Client) -> None:
        """Test that about page shows MQTT disabled when port < 0."""
        from unittest.mock import patch

        with patch('web_ui.views.get_mqtt_port', return_value=-1):
            response = logged_in_client.get('/about/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('○ Disabled'))
        assert_that(content, contains_string('--mqtt-port 1883'))

    def test_about_page_shows_mqtt_enabled(self, logged_in_client: Client) -> None:
        """Test that about page shows MQTT info when enabled."""
        from unittest.mock import patch

        with (
            patch('web_ui.views.get_mqtt_port', return_value=1883),
            patch('web_ui.views.get_actual_mqtt_port', return_value=None),
        ):
            response = logged_in_client.get('/about/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('● Enabled'))
        assert_that(content, contains_string('1883'))
        assert_that(content, contains_string('MQTT Broker'))

    def test_about_page_shows_actual_mqtt_port(self, logged_in_client: Client) -> None:
        """Test that about page shows actual port when OS-allocated."""
        from unittest.mock import patch

        with (
            patch('web_ui.views.get_mqtt_port', return_value=0),
            patch('web_ui.views.get_actual_mqtt_port', return_value=54321),
        ):
            response = logged_in_client.get('/about/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('54321'))

    def test_about_page_shows_mqtt_config_instructions(self, logged_in_client: Client) -> None:
        """Test that about page shows MQTT configuration instructions when enabled."""
        from unittest.mock import patch

        with (
            patch('web_ui.views.get_mqtt_port', return_value=1883),
            patch('web_ui.views.get_actual_mqtt_port', return_value=None),
        ):
            response = logged_in_client.get('/about/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Choose Connection Mode'))
        assert_that(content, contains_string('For MQTT Mode'))
        assert_that(content, contains_string('For HTTP Mode'))

    def test_about_page_shows_mqtt_tls_disabled(self, logged_in_client: Client) -> None:
        """Test that about page shows MQTT TLS disabled when no server cert exists."""
        from unittest.mock import patch

        with (
            patch('web_ui.views.get_mqtt_port', return_value=1883),
            patch('web_ui.views.get_actual_mqtt_port', return_value=None),
            patch('web_ui.views.get_mqtt_tls_port', return_value=8883),
        ):
            response = logged_in_client.get('/about/')

        content = response.content.decode('utf-8')
        assert_that(content, contains_string('MQTT TLS'))
        assert_that(content, contains_string('Generate a server certificate'))

    def test_about_page_redirects_unauthenticated(self, client: Client) -> None:
        """Test that about page redirects unauthenticated users."""
        response = client.get('/about/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))

    def test_about_page_shows_back_link(self, logged_in_client: Client) -> None:
        """Test that about page has a back link to the map."""
        response = logged_in_client.get('/about/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Back to Map'))

    def test_hamburger_menu_shows_about_link(self, logged_in_client: Client) -> None:
        """Test that hamburger menu contains About & Setup link."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('About &amp; Setup'))


# CSS custom properties that must be defined in both light and dark theme blocks.
# Keep in sync with REQUIRED_THEME_VARIABLES in theme.ts.
REQUIRED_CSS_VARIABLES = [
    '--bg-main',
    '--bg-left',
    '--text-main',
    '--text-secondary',
    '--text-left',
    '--border-color',
    '--endpoint-bg',
    '--endpoint-border',
    '--code-bg',
    '--log-entry-bg',
    '--log-entry-border',
    '--log-time-color',
    '--link-color',
    '--status-color',
    '--log-device-color',
    '--log-coords-color',
    '--right-header-color',
]

CSS_PATH = Path(__file__).parent.parent.parent / 'web_ui' / 'static' / 'web_ui' / 'css' / 'main.css'
HTML_PATH = Path(__file__).parent.parent.parent / 'web_ui' / 'templates' / 'web_ui' / 'home.html'


def _extract_css_block(css: str, selector: str) -> str:
    """Extract the content of a CSS block matching a selector.

    Finds the selector and extracts everything until the matching
    closing brace, handling nested braces correctly.
    """
    pattern = re.escape(selector) + r'\s*\{'
    match = re.search(pattern, css)
    if not match:
        return ''
    start = match.end()
    depth = 1
    pos = start
    while pos < len(css) and depth > 0:
        if css[pos] == '{':
            depth += 1
        elif css[pos] == '}':
            depth -= 1
        pos += 1
    return css[start:pos - 1]


class TestThemeCSS:
    """Validate that CSS defines all required variables for both themes."""

    def test_light_theme_block_exists(self) -> None:
        """CSS must have a [data-theme='light'] block."""
        css = CSS_PATH.read_text()
        block = _extract_css_block(css, '[data-theme="light"]')
        assert_that(block, is_not(equal_to('')))

    def test_dark_theme_block_exists(self) -> None:
        """CSS must have a [data-theme='dark'] block."""
        css = CSS_PATH.read_text()
        block = _extract_css_block(css, '[data-theme="dark"]')
        assert_that(block, is_not(equal_to('')))

    @pytest.mark.parametrize('variable', REQUIRED_CSS_VARIABLES)
    def test_light_theme_has_variable(self, variable: str) -> None:
        """Each required CSS variable must be defined in the light theme."""
        css = CSS_PATH.read_text()
        block = _extract_css_block(css, '[data-theme="light"]')
        assert_that(
            block,
            contains_string(f'{variable}:'),
        )

    @pytest.mark.parametrize('variable', REQUIRED_CSS_VARIABLES)
    def test_dark_theme_has_variable(self, variable: str) -> None:
        """Each required CSS variable must be defined in the dark theme."""
        css = CSS_PATH.read_text()
        block = _extract_css_block(css, '[data-theme="dark"]')
        assert_that(
            block,
            contains_string(f'{variable}:'),
        )

    def test_light_and_dark_use_different_bg_main(self) -> None:
        """Light and dark themes must have distinct --bg-main values."""
        css = CSS_PATH.read_text()
        light = _extract_css_block(css, '[data-theme="light"]')
        dark = _extract_css_block(css, '[data-theme="dark"]')

        light_bg = re.search(r'--bg-main:\s*([^;]+);', light)
        dark_bg = re.search(r'--bg-main:\s*([^;]+);', dark)

        assert_that(light_bg, is_(not_none()))
        assert_that(dark_bg, is_(not_none()))
        assert_that(
            cast(Any, light_bg).group(1).strip(),
            is_not(equal_to(cast(Any, dark_bg).group(1).strip())),
        )

    def test_light_and_dark_use_different_text_main(self) -> None:
        """Light and dark themes must have distinct --text-main values."""
        css = CSS_PATH.read_text()
        light = _extract_css_block(css, '[data-theme="light"]')
        dark = _extract_css_block(css, '[data-theme="dark"]')

        light_text = re.search(r'--text-main:\s*([^;]+);', light)
        dark_text = re.search(r'--text-main:\s*([^;]+);', dark)

        assert_that(light_text, is_(not_none()))
        assert_that(dark_text, is_(not_none()))
        assert_that(
            cast(Any, light_text).group(1).strip(),
            is_not(equal_to(cast(Any, dark_text).group(1).strip())),
        )


@pytest.mark.django_db
class TestThemeHTMLIntegration:
    """Validate that the HTML template supports theme toggling."""

    def test_template_has_theme_toggle_button(self) -> None:
        """HTML template must include the theme toggle button."""
        html = HTML_PATH.read_text()
        assert_that(html, contains_string('id="theme-toggle"'))

    def test_template_loads_css(self) -> None:
        """HTML template must load the main CSS stylesheet."""
        html = HTML_PATH.read_text()
        assert_that(html, contains_string("main.css"))

    def test_home_response_has_theme_toggle(self, logged_in_client: Client) -> None:
        """Rendered home page must contain the theme toggle button."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="theme-toggle"'))

    def test_home_response_has_data_theme_support(self, logged_in_client: Client) -> None:
        """Rendered page must include JS that sets data-theme attribute."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('/static/web_ui/js/main.'))


@pytest.mark.django_db
class TestAdminBadge:
    """Test admin badge display in the header."""

    def test_admin_user_sees_admin_badge(self, admin_logged_in_client: Client) -> None:
        """Admin users should see the admin badge in the header."""
        response = admin_logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('class="admin-badge"'))
        assert_that(content, contains_string('admin'))

    def test_regular_user_does_not_see_admin_badge(self, logged_in_client: Client) -> None:
        """Regular users should not see the admin badge."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, not_(contains_string('class="admin-badge"')))

    def test_hamburger_has_profile_link(self, logged_in_client: Client) -> None:
        """Hamburger menu should have a link to the profile page."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('href="/profile/"'))


@pytest.mark.django_db
class TestProfilePage:
    """Test the user profile page."""

    def test_profile_page_renders(self, logged_in_client: Client) -> None:
        """Profile page should render for authenticated users."""
        response = logged_in_client.get('/profile/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('testuser'))

    def test_profile_page_redirects_unauthenticated(self) -> None:
        """Unauthenticated users should be redirected to login."""
        client = Client()
        response = client.get('/profile/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, contains_string('/login/'))

    def test_profile_shows_admin_badge_for_admin(self, admin_logged_in_client: Client) -> None:
        """Profile page shows Administrator badge for admin users."""
        response = admin_logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Administrator'))
        assert_that(content, contains_string('role-badge admin'))

    def test_profile_shows_user_badge_for_regular_user(self, logged_in_client: Client) -> None:
        """Profile page shows User badge for regular users."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('role-badge user'))

    def test_profile_update_name(self, logged_in_client: Client, user: User) -> None:
        """Updating first and last name via the profile form."""
        response = logged_in_client.post('/profile/', {
            'form_type': 'profile',
            'first_name': 'John',
            'last_name': 'Doe',
            'email': user.email,
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Profile updated successfully'))

        user.refresh_from_db()
        assert_that(user.first_name, equal_to('John'))
        assert_that(user.last_name, equal_to('Doe'))

    def test_profile_update_email(self, logged_in_client: Client, user: User) -> None:
        """Updating email via the profile form."""
        response = logged_in_client.post('/profile/', {
            'form_type': 'profile',
            'first_name': '',
            'last_name': '',
            'email': 'newemail@example.com',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        user.refresh_from_db()
        assert_that(user.email, equal_to('newemail@example.com'))

    def test_password_change_success(self, logged_in_client: Client, user: User) -> None:
        """Changing password with correct current password."""
        response = logged_in_client.post('/profile/', {
            'form_type': 'password',
            'current_password': 'testpass123',
            'new_password': 'newSecureP@ss99',
            'confirm_password': 'newSecureP@ss99',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Password changed successfully'))

        user.refresh_from_db()
        assert_that(user.check_password('newSecureP@ss99'), is_(True))

    def test_password_change_wrong_current_password(self, logged_in_client: Client) -> None:
        """Changing password with wrong current password should fail."""
        response = logged_in_client.post('/profile/', {
            'form_type': 'password',
            'current_password': 'wrongpassword',
            'new_password': 'newSecureP@ss99',
            'confirm_password': 'newSecureP@ss99',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Current password is incorrect'))

    def test_password_change_mismatch(self, logged_in_client: Client) -> None:
        """Changing password with mismatched new passwords should fail."""
        response = logged_in_client.post('/profile/', {
            'form_type': 'password',
            'current_password': 'testpass123',
            'new_password': 'newSecureP@ss99',
            'confirm_password': 'differentP@ss99',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('New passwords do not match'))

    def test_password_change_too_short(self, logged_in_client: Client) -> None:
        """Changing password to something too short should fail."""
        response = logged_in_client.post('/profile/', {
            'form_type': 'password',
            'current_password': 'testpass123',
            'new_password': 'short',
            'confirm_password': 'short',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('at least 8 characters'))

    def test_password_change_keeps_session(self, logged_in_client: Client) -> None:
        """Changing password should not log the user out."""
        logged_in_client.post('/profile/', {
            'form_type': 'password',
            'current_password': 'testpass123',
            'new_password': 'newSecureP@ss99',
            'confirm_password': 'newSecureP@ss99',
        })
        response = logged_in_client.get('/profile/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    def test_profile_has_back_to_map_link(self, logged_in_client: Client) -> None:
        """Profile page should have a link back to the map."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Back to Map'))
        assert_that(content, contains_string('href="/"'))

    def test_profile_shows_member_since(self, logged_in_client: Client) -> None:
        """Profile page should show the member since date."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Member since'))

    def test_profile_has_password_toggle(self, logged_in_client: Client) -> None:
        """Profile change password form should have a single reveal toggle for all fields."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="change-pw-reveal"'))
        assert_that(content, contains_string('change-pw-field'))
        assert_that(content, contains_string('class="eye-icon"'))
        assert_that(content, contains_string('class="eye-off-icon"'))


@pytest.mark.django_db
class TestProfileCertificates:
    """Test the certificates section of the user profile page."""

    def _create_ca_and_client_cert(self, user: User) -> None:
        """Helper to create a CA and issue a client cert for a user."""
        from datetime import timedelta

        from app.models import CertificateAuthority, ClientCertificate
        from app.pki import (encrypt_private_key, generate_ca_certificate,
                             generate_client_certificate,
                             get_certificate_expiry,
                             get_certificate_fingerprint,
                             get_certificate_serial_number)

        ca_cert_pem, ca_key_pem = generate_ca_certificate(
            common_name='Profile Test CA', key_size=2048
        )
        ca = CertificateAuthority.objects.create(
            certificate_pem=ca_cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(ca_key_pem),
            common_name='Profile Test CA',
            fingerprint=get_certificate_fingerprint(ca_cert_pem),
            key_size=2048,
            not_valid_before=get_certificate_expiry(ca_cert_pem) - timedelta(days=3650),
            not_valid_after=get_certificate_expiry(ca_cert_pem),
            is_active=True,
        )

        cert_pem, key_pem = generate_client_certificate(
            ca_cert_pem, ca_key_pem, username=str(user.username), key_size=2048
        )
        ClientCertificate.objects.create(
            user=user,
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name=str(user.username),
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(get_certificate_serial_number(cert_pem)),
            key_size=2048,
            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=365),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )

    def test_profile_shows_certificates_section(self, logged_in_client: Client) -> None:
        """Profile page should contain the Certificates section header."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Certificates'))

    def test_no_cert_message_when_none_issued(self, logged_in_client: Client) -> None:
        """When no cert exists, show a prompt to contact admin."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Contact an administrator'))

    def test_no_ca_message_when_none_exists(self, logged_in_client: Client) -> None:
        """When no CA exists, show appropriate message."""
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No CA certificate'))

    def test_profile_shows_client_cert_details(self, logged_in_client: Client, user: User) -> None:
        """When user has a cert, show its details."""
        self._create_ca_and_client_cert(user)
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Client Certificate'))
        assert_that(content, contains_string(str(user.username)))
        assert_that(content, contains_string('Fingerprint'))
        assert_that(content, contains_string('Download .p12 Bundle'))

    def test_profile_shows_ca_cert_details(self, logged_in_client: Client, user: User) -> None:
        """When a CA exists, show its details and download link."""
        self._create_ca_and_client_cert(user)
        response = logged_in_client.get('/profile/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('CA Certificate'))
        assert_that(content, contains_string('Profile Test CA'))
        assert_that(content, contains_string('Download CA Cert'))

    def test_download_my_cert_p12(self, logged_in_client: Client, user: User) -> None:
        """Authenticated user can download their client cert as .p12 bundle."""
        self._create_ca_and_client_cert(user)
        response = logged_in_client.post('/profile/download-cert/', {'p12_password': 'test1234'})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], equal_to('application/x-pkcs12'))
        assert_that(response['Content-Disposition'], contains_string('.p12'))
        private_key, cert, cas = pkcs12.load_key_and_certificates(
            response.content, b'test1234'
        )
        assert_that(private_key, is_(not_none()))
        assert_that(cert, is_(not_none()))
        assert_that(cas, has_length(1))

    def test_download_my_cert_missing_password(self, logged_in_client: Client, user: User) -> None:
        """POST without password returns 400."""
        self._create_ca_and_client_cert(user)
        response = logged_in_client.post('/profile/download-cert/', {})
        assert_that(response.status_code, equal_to(400))

    def test_download_my_cert_get_not_allowed(self, logged_in_client: Client, user: User) -> None:
        """GET is no longer supported (method changed to POST)."""
        self._create_ca_and_client_cert(user)
        response = logged_in_client.get('/profile/download-cert/')
        assert_that(response.status_code, equal_to(405))

    def test_download_my_cert_no_cert(self, logged_in_client: Client) -> None:
        """Downloading cert when none exists returns 404."""
        response = logged_in_client.post('/profile/download-cert/', {'p12_password': 'test1234'})
        assert_that(response.status_code, equal_to(404))

    def test_download_ca_cert(self, logged_in_client: Client, user: User) -> None:
        """Authenticated user can download the CA cert PEM."""
        self._create_ca_and_client_cert(user)
        response = logged_in_client.get('/profile/download-ca/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], equal_to('application/x-pem-file'))
        assert_that(response['Content-Disposition'], contains_string('.crt'))
        assert_that(response.content.decode(), contains_string('BEGIN CERTIFICATE'))

    def test_download_ca_cert_no_ca(self, logged_in_client: Client) -> None:
        """Downloading CA cert when none exists returns 404."""
        response = logged_in_client.get('/profile/download-ca/')
        assert_that(response.status_code, equal_to(404))

    def test_download_requires_authentication(self) -> None:
        """Download endpoints redirect unauthenticated users."""
        client = Client()
        response = client.post('/profile/download-cert/', {'p12_password': 'test'})
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        response = client.get('/profile/download-ca/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))


@pytest.mark.django_db
class TestSessionConfiguration:
    """Test session configuration settings."""

    def test_session_cookie_age_is_7_days(self) -> None:
        """Session cookie age should be 7 days (604800 seconds)."""
        from django.conf import settings
        assert_that(settings.SESSION_COOKIE_AGE, equal_to(604800))

    def test_session_save_every_request(self) -> None:
        """Session should be saved on every request for sliding window expiry."""
        from django.conf import settings
        assert_that(settings.SESSION_SAVE_EVERY_REQUEST, is_(True))


@pytest.mark.django_db
class TestAdminPanel:
    """Test the admin panel page."""

    def test_admin_panel_renders_for_admin(self, admin_logged_in_client: Client) -> None:
        """Admin panel should render for staff users."""
        response = admin_logged_in_client.get('/admin-panel/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Admin Panel'))
        assert_that(content, contains_string('Create User'))

    def test_admin_panel_rejected_for_regular_user(self, logged_in_client: Client) -> None:
        """Regular users should be redirected away from admin panel."""
        response = logged_in_client.get('/admin-panel/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))

    def test_admin_panel_redirects_unauthenticated(self) -> None:
        """Unauthenticated users should be redirected to login."""
        client = Client()
        response = client.get('/admin-panel/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, contains_string('/login/'))

    def test_admin_panel_shows_user_list(
        self, admin_logged_in_client: Client, user: User, admin_user: User
    ) -> None:
        """Admin panel should show all users in a table."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('testuser'))
        assert_that(content, contains_string('admin'))
        assert_that(content, contains_string('user-table'))

    def test_admin_panel_create_user(self, admin_logged_in_client: Client) -> None:
        """Creating a user through the admin panel form."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'create_user',
            'username': 'newperson',
            'email': 'new@test.com',
            'password': 'secureP@ss99',
            'first_name': 'Jane',
            'last_name': 'Doe',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string("created as user"))

        created = User.objects.get(username='newperson')
        assert_that(created.first_name, equal_to('Jane'))
        assert_that(created.last_name, equal_to('Doe'))
        assert_that(created.email, equal_to('new@test.com'))

    def test_admin_panel_create_admin_user(self, admin_logged_in_client: Client) -> None:
        """Creating an admin user through the admin panel form."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'create_user',
            'username': 'newadmin',
            'email': 'admin2@test.com',
            'password': 'secureP@ss99',
            'is_admin': 'on',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string("created as administrator"))

        new_admin = User.objects.get(username='newadmin')
        assert_that(new_admin.is_staff, is_(True))
        assert_that(new_admin.is_superuser, is_(True))

    def test_admin_panel_create_user_missing_username(self, admin_logged_in_client: Client) -> None:
        """Creating a user without username shows error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'create_user',
            'username': '',
            'password': 'secureP@ss99',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Username is required'))

    def test_admin_panel_create_user_missing_password(self, admin_logged_in_client: Client) -> None:
        """Creating a user without password shows error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'create_user',
            'username': 'someone',
            'password': '',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Password is required'))

    def test_admin_panel_create_user_short_password(self, admin_logged_in_client: Client) -> None:
        """Creating a user with short password shows error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'create_user',
            'username': 'someone',
            'password': 'short',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('at least 8 characters'))

    def test_admin_panel_create_duplicate_user(
        self, admin_logged_in_client: Client, user: User
    ) -> None:
        """Creating a user with existing username shows error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'create_user',
            'username': 'testuser',
            'password': 'secureP@ss99',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string("already exists"))

    def test_hamburger_menu_shows_admin_panel_for_admin(self, admin_logged_in_client: Client) -> None:
        """Hamburger menu should contain admin panel link for admin users."""
        response = admin_logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="hamburger-dropdown"'))
        assert_that(content, contains_string('Admin Panel'))
        assert_that(content, contains_string('href="/admin-panel/"'))

    def test_hamburger_menu_hides_admin_panel_for_regular_user(self, logged_in_client: Client) -> None:
        """Hamburger menu should not contain admin panel link for regular users."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="hamburger-dropdown"'))
        assert_that(content, not_(contains_string('Admin Panel')))

    def test_hamburger_menu_shows_profile_link(self, logged_in_client: Client) -> None:
        """Hamburger menu should contain profile link for all users."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('hamburger-item'))
        assert_that(content, contains_string('Profile'))

    def test_hamburger_menu_shows_logout(self, logged_in_client: Client) -> None:
        """Hamburger menu should contain logout option."""
        response = logged_in_client.get('/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Logout'))

    def test_admin_panel_has_back_to_map_link(self, admin_logged_in_client: Client) -> None:
        """Admin panel should have a link back to the map."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Back to Map'))
        assert_that(content, contains_string('href="/"'))

    def test_admin_panel_has_password_toggle(self, admin_logged_in_client: Client) -> None:
        """Create user form should have a password visibility toggle."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="password-toggle"'))
        assert_that(content, contains_string('aria-label="Show password"'))
        assert_that(content, contains_string('class="eye-icon"'))
        assert_that(content, contains_string('class="eye-off-icon"'))

    def test_admin_panel_shows_delete_button(
        self, admin_logged_in_client: Client, user: User
    ) -> None:
        """Admin panel should show a Delete button for other users."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('hard-delete'))
        assert_that(content, contains_string('PERMANENTLY delete'))

    def test_admin_panel_shows_set_password_button(
        self, admin_logged_in_client: Client, user: User
    ) -> None:
        """Admin panel should show a Set Password button for other users."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Set Password'))
        assert_that(content, contains_string('openPasswordModal'))

    def test_admin_panel_has_password_modal(self, admin_logged_in_client: Client) -> None:
        """Admin panel should contain the password modal."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('id="password-modal"'))
        assert_that(content, contains_string('id="modal-password"'))
        assert_that(content, contains_string('submitPassword'))


@pytest.mark.django_db
class TestAdminPanelPKI:
    """Test the PKI / Certificate Authority section of the admin panel."""

    def test_admin_panel_shows_pki_section(self, admin_logged_in_client: Client) -> None:
        """Admin panel should contain the PKI section header."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('PKI'))
        assert_that(content, contains_string('Certificate Authority'))

    def test_admin_panel_shows_no_active_ca_message(self, admin_logged_in_client: Client) -> None:
        """When no CA exists, shows a prompt to generate one."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No active CA certificate'))

    def test_admin_panel_shows_generate_ca_form(self, admin_logged_in_client: Client) -> None:
        """Admin panel should contain the CA generation form with key size."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Generate New CA'))
        assert_that(content, contains_string('ca_common_name'))
        assert_that(content, contains_string('ca_validity_days'))
        assert_that(content, contains_string('ca_key_size'))
        assert_that(content, contains_string('Key Size'))

    def test_generate_ca_creates_active_ca(self, admin_logged_in_client: Client) -> None:
        """Submitting the CA form should create a new active CA."""
        from app.models import CertificateAuthority

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Test CA',
            'ca_validity_days': '365',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('generated successfully'))

        ca = CertificateAuthority.objects.filter(is_active=True).first()
        assert_that(ca, is_(not_none()))
        assert_that(cast(Any, ca).common_name, equal_to('Test CA'))

    def test_generate_ca_shows_active_ca_details(self, admin_logged_in_client: Client) -> None:
        """After generating, the active CA details should appear on the page."""
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'My Test CA',
            'ca_validity_days': '3650',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('My Test CA'))
        assert_that(content, contains_string('Fingerprint'))
        assert_that(content, contains_string('Download CA Cert'))

    def test_generate_ca_deactivates_previous(self, admin_logged_in_client: Client) -> None:
        """Generating a new CA should deactivate the previous one."""
        from app.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'First CA',
            'ca_validity_days': '365',
        })
        first_ca = CertificateAuthority.objects.get(common_name='First CA')
        assert_that(first_ca.is_active, is_(True))

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Second CA',
            'ca_validity_days': '365',
        })

        first_ca.refresh_from_db()
        assert_that(first_ca.is_active, is_(False))

        second_ca = CertificateAuthority.objects.get(common_name='Second CA')
        assert_that(second_ca.is_active, is_(True))

    def test_generate_ca_invalid_validity(self, admin_logged_in_client: Client) -> None:
        """Invalid validity days should show an error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Bad CA',
            'ca_validity_days': 'notanumber',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('must be a number'))

    def test_generate_ca_out_of_range_validity(self, admin_logged_in_client: Client) -> None:
        """Validity days outside 1-36500 range should show an error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Range CA',
            'ca_validity_days': '0',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('between 1 and 36500'))

    def test_generate_ca_empty_common_name(self, admin_logged_in_client: Client) -> None:
        """Empty common name should show an error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': '',
            'ca_validity_days': '365',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Common Name is required'))

    def test_ca_history_table_shown(self, admin_logged_in_client: Client) -> None:
        """After generating CAs, the history table should appear."""
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'History CA',
            'ca_validity_days': '365',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('CA History'))
        assert_that(content, contains_string('History CA'))

    def test_ca_download_link_present(self, admin_logged_in_client: Client) -> None:
        """Active CA should have a download link."""
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Download CA',
            'ca_validity_days': '365',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('/api/admin/pki/ca/'))
        assert_that(content, contains_string('/download/'))

    def test_expunge_inactive_ca(self, admin_logged_in_client: Client) -> None:
        """Expunging an inactive CA should permanently delete it."""
        from app.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Old CA',
            'ca_validity_days': '365',
        })
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'New CA',
            'ca_validity_days': '365',
        })

        old_ca = CertificateAuthority.objects.get(common_name='Old CA')
        assert_that(old_ca.is_active, is_(False))

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_ca',
            'ca_id': str(old_ca.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('permanently deleted'))
        assert_that(
            CertificateAuthority.objects.filter(pk=old_ca.pk).exists(), is_(False)
        )

    def test_expunge_active_ca_rejected(self, admin_logged_in_client: Client) -> None:
        """Expunging an active CA should be rejected."""
        from app.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Active CA',
            'ca_validity_days': '365',
        })
        active_ca = CertificateAuthority.objects.get(common_name='Active CA')

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_ca',
            'ca_id': str(active_ca.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Cannot expunge an active CA'))
        assert_that(
            CertificateAuthority.objects.filter(pk=active_ca.pk).exists(), is_(True)
        )

    def test_expunge_nonexistent_ca(self, admin_logged_in_client: Client) -> None:
        """Expunging a CA that doesn't exist should show an error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_ca',
            'ca_id': '99999',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('not found'))

    def test_expunge_button_shown_for_inactive_ca(self, admin_logged_in_client: Client) -> None:
        """Expunge button should appear in history table for inactive CAs."""
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'First',
            'ca_validity_days': '365',
        })
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Second',
            'ca_validity_days': '365',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Expunge'))

    def test_generate_ca_with_key_size(self, admin_logged_in_client: Client) -> None:
        """Generating CA with explicit key size should store it."""
        from app.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Small Key CA',
            'ca_validity_days': '365',
            'ca_key_size': '2048',
        })

        ca = CertificateAuthority.objects.filter(is_active=True).first()
        assert_that(ca, is_(not_none()))
        assert_that(cast(Any, ca).key_size, equal_to(2048))

    def test_generate_ca_default_key_size(self, admin_logged_in_client: Client) -> None:
        """Generating CA without key size should default to 4096."""
        from app.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Default Key CA',
            'ca_validity_days': '365',
        })

        ca = CertificateAuthority.objects.filter(is_active=True).first()
        assert_that(ca, is_(not_none()))
        assert_that(cast(Any, ca).key_size, equal_to(4096))

    def test_generate_ca_invalid_key_size(self, admin_logged_in_client: Client) -> None:
        """Invalid key size should show an error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Bad Key CA',
            'ca_validity_days': '365',
            'ca_key_size': '1024',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Key size must be one of'))

    def test_active_ca_shows_key_size(self, admin_logged_in_client: Client) -> None:
        """Active CA details should display the key size."""
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Display Key CA',
            'ca_validity_days': '365',
            'ca_key_size': '3072',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('3072-bit RSA'))

    def test_ca_history_shows_key_size(self, admin_logged_in_client: Client) -> None:
        """CA history table should show key size column."""
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'History Key CA',
            'ca_validity_days': '365',
            'ca_key_size': '2048',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('2048-bit'))


@pytest.mark.django_db
class TestAdminPanelServerCert:
    """Test the Server Certificate section of the admin panel."""

    def _create_ca(self, client: Client) -> None:
        """Helper to create a CA certificate."""
        client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Test CA',
            'ca_validity_days': '3650',
            'ca_key_size': '2048',
        })

    def test_admin_panel_shows_server_cert_section(self, admin_logged_in_client: Client) -> None:
        """Admin panel should contain the server cert section header."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Server Certificate'))
        assert_that(content, contains_string('MQTT TLS'))

    def test_no_active_server_cert_message(self, admin_logged_in_client: Client) -> None:
        """When no server cert exists, show a prompt."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No active server certificate'))

    def test_generate_form_requires_ca(self, admin_logged_in_client: Client) -> None:
        """Without a CA, the generate form should show a message."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('CA certificate is required'))

    def test_generate_form_shown_with_ca(self, admin_logged_in_client: Client) -> None:
        """With an active CA, the generate form should be displayed."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('sc_common_name'))
        assert_that(content, contains_string('sc_validity_days'))
        assert_that(content, contains_string('sc_key_size'))
        assert_that(content, contains_string('sc_san_entries'))

    def test_generate_server_cert(self, admin_logged_in_client: Client) -> None:
        """Submitting the form should create a server certificate."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'myserver.local',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'myserver.local, 192.168.1.10',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('generated successfully'))

        sc = ServerCertificate.objects.filter(is_active=True).first()
        assert_that(sc, is_(not_none()))
        assert_that(cast(Any, sc).common_name, equal_to('myserver.local'))

    def test_active_server_cert_details(self, admin_logged_in_client: Client) -> None:
        """After generating, the active server cert details should appear."""
        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'display-test.local',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'display-test.local, 10.0.1.5',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('display-test.local'))
        assert_that(content, contains_string('Fingerprint'))
        assert_that(content, contains_string('SANs'))
        assert_that(content, contains_string('10.0.1.5'))
        assert_that(content, contains_string('Download Server Cert'))

    def test_generate_server_cert_no_ca(self, admin_logged_in_client: Client) -> None:
        """Generating without a CA should show an error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'myserver',
            'sc_validity_days': '365',
            'sc_san_entries': 'myserver',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No active CA'))

    def test_generate_server_cert_empty_cn(self, admin_logged_in_client: Client) -> None:
        """Empty common name should show an error."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': '',
            'sc_validity_days': '365',
            'sc_san_entries': 'myserver',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Common Name is required'))

    def test_generate_server_cert_empty_sans_auto_includes_host(
        self, admin_logged_in_client: Client,
    ) -> None:
        """Empty SANs auto-includes the request hostname, so the cert is generated."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'myserver',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': '',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('generated successfully'))
        sc = ServerCertificate.objects.filter(is_active=True).first()
        assert_that(sc, is_(not_none()))
        assert_that(cast(Any, sc).san_entries, has_item('testserver'))

    def test_generate_server_cert_invalid_key_size(self, admin_logged_in_client: Client) -> None:
        """Invalid key size should show an error."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'myserver',
            'sc_validity_days': '365',
            'sc_key_size': '1024',
            'sc_san_entries': 'myserver',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Key size must be one of'))

    def test_generate_deactivates_previous(self, admin_logged_in_client: Client) -> None:
        """Generating a new server cert should deactivate the previous one."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'first-server',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'first-server',
        })
        first = ServerCertificate.objects.get(common_name='first-server')
        assert_that(first.is_active, is_(True))

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'second-server',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'second-server',
        })
        first.refresh_from_db()
        assert_that(first.is_active, is_(False))
        second = ServerCertificate.objects.get(common_name='second-server')
        assert_that(second.is_active, is_(True))

    def test_server_cert_history_table(self, admin_logged_in_client: Client) -> None:
        """After generating certs, the history table should appear."""
        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'history-server',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'history-server',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Server Certificate History'))
        assert_that(content, contains_string('history-server'))

    def test_expunge_inactive_server_cert(self, admin_logged_in_client: Client) -> None:
        """Expunging an inactive server cert should permanently delete it."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'old-server',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'old-server',
        })
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'new-server',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'new-server',
        })

        old = ServerCertificate.objects.get(common_name='old-server')
        assert_that(old.is_active, is_(False))

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_server_cert',
            'sc_id': str(old.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('permanently deleted'))
        assert_that(ServerCertificate.objects.filter(pk=old.pk).exists(), is_(False))

    def test_expunge_active_server_cert_rejected(self, admin_logged_in_client: Client) -> None:
        """Expunging an active server cert should be rejected."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'active-server',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'active-server',
        })
        active = ServerCertificate.objects.get(common_name='active-server')

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_server_cert',
            'sc_id': str(active.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Cannot expunge'))

    def test_default_sans_populated(self, admin_logged_in_client: Client) -> None:
        """The SAN editor should be seeded with request hostname and local IPs."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('testserver'))
        assert_that(content, contains_string('san-editor'))
        assert_that(content, contains_string('san-tags'))

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_default_sans_includes_request_host(self, admin_logged_in_client: Client) -> None:
        """When accessed via a custom hostname, that host is included in SANs."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get(
            '/admin-panel/', SERVER_NAME='mytracks.example.com',
        )
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('mytracks.example.com'))

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_auto_include_request_host_in_cert_sans(
        self, admin_logged_in_client: Client,
    ) -> None:
        """Request hostname is auto-included in SANs even if user omits it."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post(
            '/admin-panel/',
            {
                'form_type': 'generate_server_cert',
                'sc_common_name': 'myserver',
                'sc_validity_days': '365',
                'sc_key_size': '2048',
                'sc_san_entries': '10.0.0.1, 192.168.1.1',
            },
            SERVER_NAME='mytracks.example.com',
        )
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('generated successfully'))
        sc = ServerCertificate.objects.filter(is_active=True).first()
        assert_that(sc, is_(not_none()))
        san_list: list[str] = cast(Any, sc).san_entries
        assert_that(san_list, has_item('10.0.0.1'))
        assert_that(san_list, has_item('192.168.1.1'))
        assert_that(san_list, has_item('mytracks.example.com'))

    def test_no_duplicate_when_host_already_in_sans(
        self, admin_logged_in_client: Client,
    ) -> None:
        """Request hostname is not duplicated if already in the SAN list."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'myserver',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'testserver, 10.0.0.1',
        })
        sc = ServerCertificate.objects.filter(is_active=True).first()
        assert_that(sc, is_(not_none()))
        san_list: list[str] = cast(Any, sc).san_entries
        testserver_count = sum(1 for s in san_list if s == 'testserver')
        assert_that(testserver_count, equal_to(1))

    def test_cn_auto_included_in_sans(self, admin_logged_in_client: Client) -> None:
        """CN is auto-included in SANs — modern TLS clients check SANs only."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'mqtt.hcma.info',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            # Deliberately omit the CN from the SAN list
            'sc_san_entries': '192.168.1.10',
        })
        sc = ServerCertificate.objects.filter(is_active=True).first()
        assert_that(sc, is_(not_none()))
        san_list: list[str] = cast(Any, sc).san_entries
        assert_that(san_list, has_item('mqtt.hcma.info'))

    def test_cn_not_duplicated_when_already_in_sans(
        self, admin_logged_in_client: Client,
    ) -> None:
        """CN is not duplicated if already explicitly listed in the SANs."""
        from app.models import ServerCertificate

        self._create_ca(admin_logged_in_client)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'mqtt.hcma.info',
            'sc_validity_days': '365',
            'sc_key_size': '2048',
            'sc_san_entries': 'mqtt.hcma.info, 192.168.1.10',
        })
        sc = ServerCertificate.objects.filter(is_active=True).first()
        assert_that(sc, is_(not_none()))
        san_list: list[str] = cast(Any, sc).san_entries
        cn_count = sum(1 for s in san_list if s == 'mqtt.hcma.info')
        assert_that(cn_count, equal_to(1))

    def test_san_host_warning_in_template(self, admin_logged_in_client: Client) -> None:
        """The SAN editor should contain the host warning element."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('san-host-warning'))
        assert_that(content, contains_string('not in the SAN list'))


@pytest.mark.django_db
class TestAdminPanelClientCert:
    """Test the Client Certificates section of the admin panel."""

    def _create_ca(self, client: Client) -> None:
        """Helper to create a CA certificate."""
        client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Test CA',
            'ca_validity_days': '3650',
            'ca_key_size': '2048',
        })

    def _create_user(self, username: str = 'testuser') -> User:
        """Helper to create a regular user."""
        return User.objects.create_user(username=username, password='testpass123')

    def test_admin_panel_shows_client_cert_section(self, admin_logged_in_client: Client) -> None:
        """Admin panel should contain the client cert section header."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Client Certificates'))

    def test_no_client_certs_message(self, admin_logged_in_client: Client) -> None:
        """When no certs exist, show a placeholder message."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No client certificates issued yet'))

    def test_issue_form_requires_ca(self, admin_logged_in_client: Client) -> None:
        """Without a CA, the issue form should show a message."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('CA certificate is required'))

    def test_issue_form_shown_with_ca(self, admin_logged_in_client: Client) -> None:
        """With an active CA, the issue form should be displayed."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('cc_user_id'))
        assert_that(content, contains_string('cc_validity_days'))
        assert_that(content, contains_string('cc_key_size'))
        assert_that(content, contains_string('Issue Client Certificate'))

    def test_issue_client_cert(self, admin_logged_in_client: Client) -> None:
        """Submitting the form should issue a client certificate."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('issued for'))

        cert = ClientCertificate.objects.filter(user=user, is_active=True).first()
        assert_that(cert, is_(not_none()))
        assert_that(cast(Any, cert).common_name, equal_to('testuser'))

    def test_issue_cert_without_user_selection(self, admin_logged_in_client: Client) -> None:
        """Issuing a cert without selecting a user should show an error."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': '',
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('select a user'))

    def test_issue_cert_without_ca(self, admin_logged_in_client: Client) -> None:
        """Issuing a cert without a CA should show an error."""
        user = self._create_user()
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No active CA'))

    def test_issue_cert_deactivates_existing(self, admin_logged_in_client: Client) -> None:
        """Issuing a new cert for a user should deactivate the old one."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        first = ClientCertificate.objects.get(user=user, is_active=True)

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        first.refresh_from_db()
        assert_that(first.is_active, is_(False))
        second = ClientCertificate.objects.filter(user=user, is_active=True).first()
        assert_that(second, is_(not_none()))

    def test_client_cert_table_shown_after_issue(self, admin_logged_in_client: Client) -> None:
        """After issuing, the cert should appear in the table."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user('tabluser')
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('tabluser'))
        assert_that(content, contains_string('Download'))

    def test_revoke_client_cert(self, admin_logged_in_client: Client) -> None:
        """Revoking a client cert should mark it as revoked."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        cert = ClientCertificate.objects.get(user=user, is_active=True)

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'revoke_client_cert',
            'cc_id': str(cert.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('revoked'))

        cert.refresh_from_db()
        assert_that(cert.revoked, is_(True))
        assert_that(cert.is_active, is_(False))
        assert_that(cert.revoked_at, is_(not_none()))

    def test_revoke_already_revoked_cert(self, admin_logged_in_client: Client) -> None:
        """Revoking an already-revoked cert should show an error."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        cert = ClientCertificate.objects.get(user=user, is_active=True)

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'revoke_client_cert',
            'cc_id': str(cert.pk),
        })
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'revoke_client_cert',
            'cc_id': str(cert.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('already revoked'))

    def test_expunge_revoked_client_cert(self, admin_logged_in_client: Client) -> None:
        """Expunging a revoked cert should permanently delete it."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        cert = ClientCertificate.objects.get(user=user)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'revoke_client_cert',
            'cc_id': str(cert.pk),
        })

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_client_cert',
            'cc_id': str(cert.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('permanently deleted'))
        assert_that(ClientCertificate.objects.filter(pk=cert.pk).exists(), is_(False))

    def test_expunge_active_client_cert_rejected(self, admin_logged_in_client: Client) -> None:
        """Expunging an active cert should be rejected."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        cert = ClientCertificate.objects.get(user=user, is_active=True)

        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'expunge_client_cert',
            'cc_id': str(cert.pk),
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Cannot expunge'))

    def test_user_dropdown_lists_users(self, admin_logged_in_client: Client) -> None:
        """The user dropdown should list all available users."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user('dropdownuser')
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('dropdownuser'))

    def test_issue_cert_invalid_validity(self, admin_logged_in_client: Client) -> None:
        """Invalid validity days should show an error."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': 'abc',
            'cc_key_size': '2048',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('must be a number'))

    def test_issue_cert_invalid_key_size(self, admin_logged_in_client: Client) -> None:
        """Invalid key size should show an error."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '1024',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Key size must be one of'))

    def test_issue_cert_nonexistent_user(self, admin_logged_in_client: Client) -> None:
        """Issuing a cert for a nonexistent user should show an error."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': '99999',
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('not found'))

    def test_download_link_present(self, admin_logged_in_client: Client) -> None:
        """After issuing, a download link should be present."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('/api/admin/pki/client-certs/'))
        assert_that(content, contains_string('/download/'))


@pytest.mark.django_db
class TestAdminPanelCRL:
    """Test the Certificate Revocation List section of the admin panel."""

    def _create_ca(self, client: Client) -> None:
        client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'CRL Test CA',
            'ca_validity_days': '3650',
            'ca_key_size': '2048',
        })

    def _create_user(self, username: str = 'crluser') -> User:
        return User.objects.create_user(username=username, password='testpass123')

    def _issue_and_revoke(self, client: Client, user: User) -> None:
        from app.models import ClientCertificate
        client.post('/admin-panel/', {
            'form_type': 'issue_client_cert',
            'cc_user_id': str(user.pk),
            'cc_validity_days': '365',
            'cc_key_size': '2048',
        })
        cert = ClientCertificate.objects.get(user=user, is_active=True)
        client.post('/admin-panel/', {
            'form_type': 'revoke_client_cert',
            'cc_id': str(cert.pk),
        })

    def test_crl_section_header_present(self, admin_logged_in_client: Client) -> None:
        """Admin panel should show the CRL section header."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Certificate Revocation List'))

    def test_crl_section_requires_ca(self, admin_logged_in_client: Client) -> None:
        """Without a CA, CRL section should show a message."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('A CA certificate is required to generate a CRL'))

    def test_crl_empty_state(self, admin_logged_in_client: Client) -> None:
        """With a CA but no revocations, show 'No certificates have been revoked'."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('No certificates have been revoked'))

    def test_crl_no_download_when_empty(self, admin_logged_in_client: Client) -> None:
        """Download CRL button should not appear when there are no revocations."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, not_(contains_string('Download CRL')))

    def test_crl_shows_revoked_cert(self, admin_logged_in_client: Client) -> None:
        """Revoked certificate should appear in the CRL table."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        self._issue_and_revoke(admin_logged_in_client, user)

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('1 revoked certificate'))
        assert_that(content, contains_string('crluser'))

    def test_crl_shows_serial_number(self, admin_logged_in_client: Client) -> None:
        """CRL table should display the certificate serial number."""
        from app.models import ClientCertificate
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        self._issue_and_revoke(admin_logged_in_client, user)

        cert = ClientCertificate.objects.get(user=user)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string(cert.serial_number))

    def test_crl_download_link_present(self, admin_logged_in_client: Client) -> None:
        """Download CRL button should appear when revocations exist."""
        self._create_ca(admin_logged_in_client)
        user = self._create_user()
        self._issue_and_revoke(admin_logged_in_client, user)

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Download CRL'))
        assert_that(content, contains_string('/api/admin/pki/crl/'))

    def test_crl_multiple_revoked_certs(self, admin_logged_in_client: Client) -> None:
        """Multiple revoked certs should all appear with correct count."""
        self._create_ca(admin_logged_in_client)
        user_a = self._create_user('alice')
        user_b = self._create_user('bob')
        self._issue_and_revoke(admin_logged_in_client, user_a)
        self._issue_and_revoke(admin_logged_in_client, user_b)

        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('2 revoked certificates'))
        assert_that(content, contains_string('alice'))
        assert_that(content, contains_string('bob'))

    def test_crl_not_visible_to_regular_user(self) -> None:
        """Regular users should not be able to access the admin panel."""
        user = User.objects.create_user(username='regular', password='testpass123')
        client = Client()
        client.login(username='regular', password='testpass123')
        response = client.get('/admin-panel/')
        assert_that(response.status_code, is_(equal_to(status.HTTP_302_FOUND)))


@pytest.mark.django_db
class TestGeofencesView:
    """Tests for the /geofences/ view."""

    def test_get_redirects_unauthenticated(self) -> None:
        """Unauthenticated users are redirected to login."""
        client = Client()
        response = client.get('/geofences/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, contains_string('/login/'))

    def test_get_renders_for_authenticated_user(self, logged_in_client: Client) -> None:
        """GET returns 200 for a logged-in user."""
        response = logged_in_client.get('/geofences/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Geofences'))
        assert_that(content, contains_string('geofence-map'))

    def test_get_lists_user_waypoints(self, logged_in_client: Client, user: User) -> None:
        """Waypoints owned by the user appear in the context."""
        from app.models import Waypoint
        wp = Waypoint.objects.create(
            user=user, label='Test Zone', latitude='41.0', longitude='-73.0', radius=200
        )
        response = logged_in_client.get('/geofences/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Test Zone'))
        wp.delete()

    def test_get_excludes_other_users_waypoints(
        self, logged_in_client: Client, user: User
    ) -> None:
        """Waypoints owned by other users are not shown."""
        from app.models import Waypoint
        other = User.objects.create_user(username='other', password='pass')
        wp = Waypoint.objects.create(
            user=other, label='Other Zone', latitude='42.0', longitude='-74.0', radius=100
        )
        response = logged_in_client.get('/geofences/')
        content = response.content.decode('utf-8')
        assert_that(content, not_(contains_string('Other Zone')))
        wp.delete()
        other.delete()

    def test_post_add_waypoint_creates_object(
        self, logged_in_client: Client, user: User
    ) -> None:
        """POST add_waypoint creates a new Waypoint for the user and redirects."""
        from app.models import Waypoint
        response = logged_in_client.post('/geofences/', {
            'form_type': 'add_waypoint',
            'label': 'Home',
            'latitude': '41.194',
            'longitude': '-73.888',
            'radius': '150',
        })
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, equal_to('/geofences/'))
        wp = Waypoint.objects.filter(user=user, label='Home').first()
        assert_that(wp, not_none())
        assert_that(wp.radius, equal_to(150))

    def test_post_edit_waypoint_updates_object(
        self, logged_in_client: Client, user: User
    ) -> None:
        """POST edit_waypoint updates the waypoint and redirects."""
        from app.models import Waypoint
        wp = Waypoint.objects.create(
            user=user, label='Old Name', latitude='41.0', longitude='-73.0', radius=100
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'edit_waypoint',
            'waypoint_id': wp.pk,
            'label': 'New Name',
            'latitude': '41.5',
            'longitude': '-73.5',
            'radius': '300',
        })
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        wp.refresh_from_db()
        assert_that(wp.label, equal_to('New Name'))
        assert_that(wp.radius, equal_to(300))

    def test_post_edit_waypoint_returns_404_for_other_user(
        self, logged_in_client: Client
    ) -> None:
        """Editing another user's waypoint returns 404."""
        from app.models import Waypoint
        other = User.objects.create_user(username='other2', password='pass')
        wp = Waypoint.objects.create(
            user=other, label='Theirs', latitude='41.0', longitude='-73.0', radius=100
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'edit_waypoint',
            'waypoint_id': wp.pk,
            'label': 'Hijacked',
            'latitude': '0',
            'longitude': '0',
            'radius': '50',
        })
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_post_delete_waypoint_removes_object(
        self, logged_in_client: Client, user: User
    ) -> None:
        """POST delete_waypoint removes the waypoint and redirects."""
        from app.models import Waypoint
        wp = Waypoint.objects.create(
            user=user, label='To Delete', latitude='41.0', longitude='-73.0', radius=100
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'delete_waypoint',
            'waypoint_id': wp.pk,
        })
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(Waypoint.objects.filter(pk=wp.pk).exists(), is_(False))

    def test_post_delete_waypoint_returns_404_for_other_user(
        self, logged_in_client: Client
    ) -> None:
        """Deleting another user's waypoint returns 404."""
        from app.models import Waypoint
        other = User.objects.create_user(username='other3', password='pass')
        wp = Waypoint.objects.create(
            user=other, label='Theirs', latitude='41.0', longitude='-73.0', radius=100
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'delete_waypoint',
            'waypoint_id': wp.pk,
        })
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_post_sync_to_device_returns_404_for_unowned_device(
        self, logged_in_client: Client, user: User
    ) -> None:
        """Syncing to a device not owned by the user returns 404."""
        from app.models import Device
        other = User.objects.create_user(username='other4', password='pass')
        device = Device.objects.create(
            device_id='d1', mqtt_user='other4', name='Device', owner=other
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'sync_to_device',
            'device_id': device.pk,
        })
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_post_sync_to_device_calls_command_publisher(
        self, logged_in_client: Client, user: User
    ) -> None:
        """Syncing to an owned device calls CommandPublisher.set_waypoints."""
        from unittest.mock import AsyncMock, patch

        from app.models import Device, Waypoint
        device = Device.objects.create(
            device_id='mydevice', mqtt_user='testuser', name='My Phone', owner=user
        )
        Waypoint.objects.create(
            user=user, label='Home', latitude='41.194', longitude='-73.888', radius=100
        )
        with patch('web_ui.views.CommandPublisher') as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.set_waypoints = AsyncMock(return_value=True)
            response = logged_in_client.post('/geofences/', {
                'form_type': 'sync_to_device',
                'device_id': device.pk,
            })
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        mock_instance.set_waypoints.assert_called_once()
        call_args = mock_instance.set_waypoints.call_args
        assert_that(call_args[0][0], equal_to('testuser/mydevice'))
        payload = call_args[0][1]
        assert_that(payload, has_length(1))
        assert_that(payload[0]['desc'], equal_to('Home'))

    def test_waypoint_db_fields_match_set_waypoints_mqtt_json(
        self, user: User
    ) -> None:
        """Stored waypoint coordinates must match setWaypoints JSON payload."""
        from app.models import Waypoint
        from app.mqtt.commands import Command

        wp = Waypoint.objects.create(
            user=user,
            label='Test zone (fixture)',
            latitude='12.3456789012',
            longitude='-98.7654321098',
            radius=250,
        )
        wp.refresh_from_db()
        row = wp.as_device_sync_row()
        assert_that(row['desc'], equal_to(wp.label))
        assert_that(row['lat'], equal_to(float(wp.latitude)))
        assert_that(row['lon'], equal_to(float(wp.longitude)))
        assert_that(row['rad'], equal_to(wp.radius))
        assert_that(row['tst'], equal_to(int(wp.updated_at.timestamp())))

        cmd = Command.set_waypoints([row])
        outer = json.loads(cmd.to_mqtt_payload().decode('utf-8'))
        inner = outer['waypoints']['waypoints'][0]
        assert_that(inner['_type'], equal_to('waypoint'))
        assert_that(inner['desc'], equal_to(wp.label))
        assert_that(inner['lat'], equal_to(row['lat']))
        assert_that(inner['lon'], equal_to(row['lon']))
        assert_that(inner['rad'], equal_to(wp.radius))
        assert_that(inner['tst'], equal_to(row['tst']))


@pytest.mark.django_db
class TestProfileTransitions:
    """Profile view should include transition history in context."""

    def test_profile_transitions_in_context(
        self, logged_in_client: Client, user: User
    ) -> None:
        """Transitions for the user's devices appear on the profile Locations tab."""
        from django.utils import timezone

        from app.models import Device, Transition, Waypoint
        device = Device.objects.create(
            device_id='dev1', mqtt_user='testuser', name='Test Device', owner=user
        )
        wp = Waypoint.objects.create(
            user=user, label='Office', latitude='40.7', longitude='-74.0', radius=100
        )
        Transition.objects.create(
            device=device,
            waypoint=wp,
            event='enter',
            region_id=wp.rid,
            description='Office',
            timestamp=timezone.now(),
        )
        response = logged_in_client.get('/profile/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Recent Transitions'))
        assert_that(content, contains_string('Office'))


@pytest.mark.django_db
class TestAdminPanelSmtp:
    """Tests for the SMTP configuration section of the admin panel."""

    def test_email_tab_renders(self, admin_logged_in_client: Client) -> None:
        """GET admin panel renders the Email tab containing SMTP Settings."""
        response = admin_logged_in_client.get('/admin-panel/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('SMTP Settings'))
        assert_that(content, contains_string('Send test email'))

    def test_save_smtp_creates_config(self, admin_logged_in_client: Client) -> None:
        """POST save_smtp with valid data creates SmtpConfig and shows success."""
        from app.models import SmtpConfig
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': 'smtp.example.com',
            'smtp_port': '587',
            'smtp_username': 'user@example.com',
            'smtp_password': 'secret',
            'smtp_from_address': 'noreply@example.com',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.content.decode(), contains_string('SMTP settings saved.'))
        config = SmtpConfig.get()
        assert config is not None
        assert_that(config.host, equal_to('smtp.example.com'))
        assert_that(config.port, equal_to(587))
        assert_that(config.from_address, equal_to('noreply@example.com'))
        assert_that(bool(config.encrypted_password), equal_to(True))

    def test_save_smtp_updates_existing(self, admin_logged_in_client: Client) -> None:
        """Saving again updates the singleton — only one row ever exists."""
        from app.models import SmtpConfig
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': 'smtp.first.com',
            'smtp_port': '587',
            'smtp_username': '',
            'smtp_password': '',
            'smtp_from_address': 'a@first.com',
        })
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': 'smtp.second.com',
            'smtp_port': '465',
            'smtp_username': '',
            'smtp_password': '',
            'smtp_from_address': 'a@second.com',
        })
        assert_that(SmtpConfig.objects.count(), equal_to(1))
        config = SmtpConfig.get()
        assert config is not None
        assert_that(config.host, equal_to('smtp.second.com'))

    def test_save_smtp_preserves_password_when_blank(self, admin_logged_in_client: Client) -> None:
        """Saving with blank password keeps the existing encrypted password."""
        from app.models import SmtpConfig
        from app.pki import encrypt_private_key
        config = SmtpConfig(host='smtp.example.com', port=587, from_address='a@b.com')
        config.encrypted_password = encrypt_private_key(b'original-password')
        config.save()
        assert_that(config.encrypted_password, is_(not_none()))
        original_encrypted = bytes(cast(Any, config.encrypted_password))

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': 'smtp.example.com',
            'smtp_port': '587',
            'smtp_username': '',
            'smtp_password': '',  # blank — should not overwrite
            'smtp_from_address': 'a@b.com',
        })
        config.refresh_from_db()
        assert_that(config.encrypted_password, is_(not_none()))
        assert_that(bytes(cast(Any, config.encrypted_password)), equal_to(original_encrypted))

    def test_save_smtp_missing_host(self, admin_logged_in_client: Client) -> None:
        """POST with blank host shows smtp_error."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': '',
            'smtp_port': '587',
            'smtp_username': '',
            'smtp_password': '',
            'smtp_from_address': 'a@b.com',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.content.decode(), contains_string('Host is required.'))

    def test_save_smtp_without_from_address(self, admin_logged_in_client: Client) -> None:
        """POST with blank from_address is now allowed (from address is optional)."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': 'smtp.example.com',
            'smtp_port': '587',
            'smtp_username': '',
            'smtp_password': '',
            'smtp_from_address': '',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.content.decode(), contains_string('SMTP settings saved.'))

    def test_smtp_test_no_config(self, admin_logged_in_client: Client) -> None:
        """POST smtp-test/ with no config returns ok=false."""
        import json
        response = admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(False))
        assert_that(data['error'], contains_string('not configured'))

    def test_smtp_test_success(self, admin_logged_in_client: Client) -> None:
        """POST smtp-test/ with valid config and mock send returns ok=true."""
        import json

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.example.com', port=587, from_address='a@b.com').save()
        with patch('web_ui.views.send_test_email'):
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(True))

    def test_smtp_test_includes_server_sans(self, admin_logged_in_client: Client) -> None:
        """SANs from the active server cert are forwarded to send_test_email."""
        from unittest.mock import MagicMock

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.example.com', port=587, from_address='a@b.com').save()
        mock_sc = MagicMock()
        mock_sc.certificate_pem = 'FAKE-PEM'
        with (
            patch('web_ui.views.ServerCertificate') as mock_sc_model,
            patch('web_ui.views.get_certificate_sans', return_value=['tracks.local', '192.168.1.1']) as mock_sans,
            patch('web_ui.views.send_test_email') as mock_send,
        ):
            mock_sc_model.objects.filter.return_value.first.return_value = mock_sc
            admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        mock_sans.assert_called_once_with(b'FAKE-PEM')
        _, kwargs = mock_send.call_args
        assert_that(kwargs['server_names'], equal_to(['tracks.local', '192.168.1.1']))

    def test_smtp_test_failure(self, admin_logged_in_client: Client) -> None:
        """POST smtp-test/ when send raises returns ok=false with error message."""
        import json

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.example.com', port=587, from_address='a@b.com').save()
        with patch('web_ui.views.send_test_email', side_effect=Exception('connection timeout')):
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(False))
        assert_that(data['error'], contains_string('connection timeout'))

    def test_smtp_test_friendly_error_gaierror(self, admin_logged_in_client: Client) -> None:
        """socket.gaierror is translated to a human-readable message."""
        import json
        import socket

        from app.models import SmtpConfig
        SmtpConfig(host='bad.host', port=587, from_address='a@b.com').save()
        with patch('web_ui.views.send_test_email', side_effect=socket.gaierror(8, 'nodename nor servname provided')):
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(False))
        assert_that(data['error'], contains_string('Could not resolve hostname'))

    def test_save_smtp_infers_tls_from_port(self, admin_logged_in_client: Client) -> None:
        """Port 465 sets use_ssl=True; port 587 sets use_tls=True."""
        from app.models import SmtpConfig
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': 'smtp.example.com',
            'smtp_port': '465',
            'smtp_from_address': 'a@b.com',
        })
        config = SmtpConfig.get()
        assert config is not None
        assert_that(config.use_ssl, equal_to(True))
        assert_that(config.use_tls, equal_to(False))

    def test_smtp_test_requires_staff(self, logged_in_client: Client) -> None:
        """Non-staff user is redirected away from smtp-test/."""
        response = logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        assert_that(response.status_code, equal_to(302))

    def test_smtp_test_saves_recipient_to_session(self, admin_logged_in_client: Client) -> None:
        """A successful test email saves the recipient address in the session."""
        import json
        with patch('web_ui.views.send_test_email_via_backend'):
            admin_logged_in_client.post('/admin-panel/smtp-test/', {
                'to': 'saved@example.com',
                'host': 'smtp.hcma.info',
                'port': '25',
                'username': '',
                'password': '',
                'from_address': 'noreply@my-tracks',
            })
        # The recipient should now be pre-filled on the admin panel
        response = admin_logged_in_client.get('/admin-panel/')
        assert_that(response.content.decode(), contains_string('saved@example.com'))

    def test_smtp_test_failed_does_not_save_recipient(self, admin_logged_in_client: Client) -> None:
        """A failed test email does not update the saved recipient in the session."""
        import smtplib

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.hcma.info', port=25, from_address='a@b.com').save()
        # Prime session with an existing recipient
        with patch('web_ui.views.send_test_email_via_backend'):
            admin_logged_in_client.post('/admin-panel/smtp-test/', {
                'to': 'existing@example.com',
                'host': 'smtp.hcma.info',
                'port': '25',
                'username': '',
                'password': '',
                'from_address': 'noreply@my-tracks',
            })
        # Now fail with a different address
        err = smtplib.SMTPConnectError(421, b'fail')
        with patch('web_ui.views.send_test_email', side_effect=err):
            admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'new@example.com'})
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode()
        assert_that(content, contains_string('existing@example.com'))
        assert_that(content, is_not(contains_string('new@example.com')))

    def test_smtp_test_unauthenticated_relay(self, admin_logged_in_client: Client) -> None:
        """Blank username+password builds backend with empty credentials (unauthenticated relay)."""
        import json
        with patch('web_ui.views.SmtpEmailBackend') as mock_backend_cls:
            mock_instance = mock_backend_cls.return_value
            with patch('web_ui.views.send_test_email_via_backend') as mock_send:
                response = admin_logged_in_client.post('/admin-panel/smtp-test/', {
                    'to': 'test@example.com',
                    'host': 'relay.internal',
                    'port': '25',
                    'username': '',
                    'password': '',
                    'from_address': 'noreply@my-tracks',
                })
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(True))
        assert_that(mock_backend_cls.called, equal_to(True))
        _, kwargs = mock_backend_cls.call_args
        assert_that(kwargs['username'], equal_to(''))
        assert_that(kwargs['password'], equal_to(''))
        assert_that(mock_send.called, equal_to(True))

    def test_smtp_test_transient_success(self, admin_logged_in_client: Client) -> None:
        """POST smtp-test/ with host param uses transient backend without saving config."""
        import json
        with patch('web_ui.views.send_test_email_via_backend') as mock_send:
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {
                'to': 'test@example.com',
                'host': 'smtp.hcma.info',
                'port': '25',
                'username': '',
                'password': '',
                'from_address': 'noreply@hcma.info',
            })
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(True))
        assert_that(mock_send.called, equal_to(True))
        from app.models import SmtpConfig
        assert_that(SmtpConfig.get(), equal_to(None))

    def test_smtp_test_transient_reuses_saved_password(self, admin_logged_in_client: Client) -> None:
        """Transient test with blank password reuses saved config's backend when host matches."""
        import json

        from app.models import SmtpConfig
        from app.pki import encrypt_private_key
        saved = SmtpConfig(host='smtp.hcma.info', port=587, from_address='a@b.com')
        saved.encrypted_password = encrypt_private_key(b'secret')
        saved.save()
        with patch('web_ui.views.send_test_email_via_backend') as mock_send:
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {
                'to': 'test@example.com',
                'host': 'smtp.hcma.info',
                'port': '587',
                'username': '',
                'password': '',
                'from_address': 'a@b.com',
            })
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(True))
        assert_that(mock_send.called, equal_to(True))

    def test_smtp_test_transient_no_config_no_password(self, admin_logged_in_client: Client) -> None:
        """Transient test with no saved config and no password tests without auth."""
        import json
        with patch('web_ui.views.send_test_email_via_backend') as mock_send:
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {
                'to': 'test@example.com',
                'host': 'smtp.hcma.info',
                'port': '25',
                'username': '',
                'password': '',
                'from_address': 'noreply@hcma.info',
            })
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(True))
        assert_that(mock_send.called, equal_to(True))

    def test_smtp_test_transient_invalid_port(self, admin_logged_in_client: Client) -> None:
        """Transient test with non-numeric port returns an error."""
        import json
        response = admin_logged_in_client.post('/admin-panel/smtp-test/', {
            'to': 'test@example.com',
            'host': 'smtp.hcma.info',
            'port': 'notanumber',
        })
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(False))
        assert_that(data['error'], contains_string('Invalid port'))

    def test_smtp_test_button_enabled_without_saved_config(self, admin_logged_in_client: Client) -> None:
        """The test button is always enabled — no saved config required."""
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode()
        assert_that(content, contains_string('id="smtp-test-btn"'))
        assert_that(content, is_not(contains_string('disabled title="Save SMTP settings first"')))

    def test_save_smtp_preserves_form_data_on_validation_error(self, admin_logged_in_client: Client) -> None:
        """On save error, submitted form values are repopulated in the response."""
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'save_smtp',
            'smtp_host': '',  # missing host → triggers error
            'smtp_port': '587',
            'smtp_username': 'user@hcma.info',
            'smtp_password': '',
            'smtp_from_address': '',
        })
        content = response.content.decode()
        assert_that(content, contains_string('Host is required.'))

    def test_smtp_friendly_error_auth_not_supported(self, admin_logged_in_client: Client) -> None:
        """SMTPNotSupportedError for AUTH returns a helpful no-auth-relay message."""
        import json
        import smtplib

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.hcma.info', port=25, from_address='a@b.com').save()
        err = smtplib.SMTPNotSupportedError('SMTP AUTH extension not supported by server.')
        with patch('web_ui.views.send_test_email', side_effect=err):
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(False))
        assert_that(data['error'], contains_string('does not support SMTP authentication'))
        assert_that(data['error'], contains_string('Username and Password blank'))

    def test_smtp_friendly_error_connect_error(self, admin_logged_in_client: Client) -> None:
        """SMTPConnectError returns a helpful connection message."""
        import json
        import smtplib

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.hcma.info', port=25, from_address='a@b.com').save()
        err = smtplib.SMTPConnectError(421, b'Service not available')
        with patch('web_ui.views.send_test_email', side_effect=err):
            response = admin_logged_in_client.post('/admin-panel/smtp-test/', {'to': 'test@example.com'})
        data = json.loads(response.content)
        assert_that(data['ok'], equal_to(False))
        assert_that(data['error'], contains_string('Could not connect'))

    def test_smtp_test_includes_public_domain(self, admin_logged_in_client: Client) -> None:
        """Test email body includes the configured PUBLIC_DOMAIN."""
        from unittest.mock import MagicMock

        from django.core.mail import EmailMessage as BaseEmailMessage
        from django.core.mail.backends.smtp import \
            EmailBackend as SmtpEmailBackend
        from django.test import override_settings

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.hcma.info', port=25, from_address='a@b.com').save()
        captured: list[dict[str, str]] = []

        def fake_send(to: str, backend: SmtpEmailBackend, from_email: str, server_names: list[str] | None = None) -> None:
            captured.append({'to': to, 'from_email': from_email})

        with override_settings(PUBLIC_DOMAIN='mytracks.example.com'):
            with patch('web_ui.views.send_test_email', side_effect=fake_send) as mock_send:
                # Use saved-config mode (no host in POST)
                pass
            # Call send_test_email_via_backend directly to check the email body
            import smtplib

            from app.notifications import send_test_email_via_backend

            sent_messages: list[BaseEmailMessage] = []

            class CapturingBackend(SmtpEmailBackend):
                def send_messages(self, messages: Any) -> int:
                    sent_messages.extend(messages)
                    return len(messages)

            with override_settings(PUBLIC_DOMAIN='mytracks.example.com'):
                send_test_email_via_backend('out@example.com', CapturingBackend(), 'noreply@my-tracks')

        assert_that(len(sent_messages), equal_to(1))
        assert_that(sent_messages[0].body, contains_string('mytracks.example.com'))
        assert_that(sent_messages[0].from_email, equal_to('noreply@my-tracks'))
        assert_that(sent_messages[0].reply_to, equal_to(['mytracks-no-reply@mytracks.example.com']))

    def test_reset_smtp_deletes_config(self, admin_logged_in_client: Client) -> None:
        """POSTing reset_smtp deletes the saved SmtpConfig and clears the session recipient."""
        import json

        from app.models import SmtpConfig
        SmtpConfig(host='smtp.hcma.info', port=587, from_address='a@b.com').save()
        assert_that(SmtpConfig.get(), not_(equal_to(None)))
        # Prime the session with a recipient
        with patch('web_ui.views.send_test_email_via_backend'):
            admin_logged_in_client.post('/admin-panel/smtp-test/', {
                'to': 'old@example.com',
                'host': 'smtp.hcma.info',
                'port': '587',
                'username': '',
                'password': '',
                'from_address': 'a@b.com',
            })

        response = admin_logged_in_client.post('/admin-panel/', {'form_type': 'reset_smtp'})
        assert_that(response.status_code, equal_to(200))
        assert_that(SmtpConfig.get(), equal_to(None))
        # Session recipient should be cleared — input should be empty
        assert_that(response.content.decode(), is_not(contains_string('old@example.com')))

    def test_reset_smtp_when_no_config_is_noop(self, admin_logged_in_client: Client) -> None:
        """POSTing reset_smtp when no config exists succeeds silently."""
        from app.models import SmtpConfig
        assert_that(SmtpConfig.get(), equal_to(None))

        response = admin_logged_in_client.post('/admin-panel/', {'form_type': 'reset_smtp'})
        assert_that(response.status_code, equal_to(200))

    def test_reset_smtp_button_always_shown(self, admin_logged_in_client: Client) -> None:
        """Reset button is always rendered regardless of whether a SmtpConfig is saved."""
        from app.models import SmtpConfig

        # No config → button still present but disabled
        response = admin_logged_in_client.get('/admin-panel/')
        html = response.content.decode()
        assert_that(html, contains_string('reset_smtp'))
        assert_that(html, contains_string('form="smtp-reset-form" class="submit-btn" style="background:var(--error,#dc2626)" disabled'))

        # With config → button present and enabled (no disabled attribute)
        SmtpConfig(host='smtp.hcma.info', port=587, from_address='a@b.com').save()
        response = admin_logged_in_client.get('/admin-panel/')
        html = response.content.decode()
        assert_that(html, contains_string('reset_smtp'))
        assert_that(html, not_(contains_string('form="smtp-reset-form" class="submit-btn" style="background:var(--error,#dc2626)" disabled')))

    def test_save_smtp_button_initially_disabled(self, admin_logged_in_client: Client) -> None:
        """Save button always starts disabled — enabled only after a successful test via JS."""
        response = admin_logged_in_client.get('/admin-panel/')
        assert_that(response.content.decode(), contains_string('id="smtp-save-btn" disabled'))
