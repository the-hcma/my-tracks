"""Tests for web_ui views."""

import re
from pathlib import Path
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
        """Test that network_info returns required fields."""
        response = logged_in_client.get('/network-info/', SERVER_PORT='8080')

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        data = response.json()
        assert_that(data, has_key('hostname'))
        assert_that(data, has_key('local_ip'))
        assert_that(data, has_key('local_ips'))
        assert_that(data, has_key('port'))
        assert_that(data['port'], equal_to(8080))
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
            patch('web_ui.views.netifaces.interfaces', return_value=list(mock_interfaces.keys())),
            patch('web_ui.views.netifaces.ifaddresses', side_effect=lambda iface: mock_interfaces[iface]),
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
        assert_that(content, contains_string('MQTT (Recommended)'))
        assert_that(content, contains_string('For MQTT Mode'))
        assert_that(content, contains_string('For HTTP Mode'))

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

CSS_PATH = Path(__file__).parent / 'web_ui' / 'static' / 'web_ui' / 'css' / 'main.css'
HTML_PATH = Path(__file__).parent / 'web_ui' / 'templates' / 'web_ui' / 'home.html'


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
            light_bg.group(1).strip(),  # type: ignore[union-attr]
            is_not(equal_to(dark_bg.group(1).strip())),  # type: ignore[union-attr]
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
            light_text.group(1).strip(),  # type: ignore[union-attr]
            is_not(equal_to(dark_text.group(1).strip())),  # type: ignore[union-attr]
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

        from my_tracks.models import CertificateAuthority, ClientCertificate
        from my_tracks.pki import (encrypt_private_key,
                                   generate_ca_certificate,
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
        from my_tracks.models import CertificateAuthority

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
        assert_that(ca.common_name, equal_to('Test CA'))  # type: ignore[union-attr]

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
        from my_tracks.models import CertificateAuthority

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
        from my_tracks.models import CertificateAuthority

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
        from my_tracks.models import CertificateAuthority

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
        from my_tracks.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Small Key CA',
            'ca_validity_days': '365',
            'ca_key_size': '2048',
        })

        ca = CertificateAuthority.objects.filter(is_active=True).first()
        assert_that(ca, is_(not_none()))
        assert_that(ca.key_size, equal_to(2048))  # type: ignore[union-attr]

    def test_generate_ca_default_key_size(self, admin_logged_in_client: Client) -> None:
        """Generating CA without key size should default to 4096."""
        from my_tracks.models import CertificateAuthority

        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_ca',
            'ca_common_name': 'Default Key CA',
            'ca_validity_days': '365',
        })

        ca = CertificateAuthority.objects.filter(is_active=True).first()
        assert_that(ca, is_(not_none()))
        assert_that(ca.key_size, equal_to(4096))  # type: ignore[union-attr]

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
        from my_tracks.models import ServerCertificate

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
        assert_that(sc.common_name, equal_to('myserver.local'))  # type: ignore[union-attr]

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

    def test_generate_server_cert_no_sans(self, admin_logged_in_client: Client) -> None:
        """Empty SANs should show an error."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'generate_server_cert',
            'sc_common_name': 'myserver',
            'sc_validity_days': '365',
            'sc_san_entries': '',
        })
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('SAN entry is required'))

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
        from my_tracks.models import ServerCertificate

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
        from my_tracks.models import ServerCertificate

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
        from my_tracks.models import ServerCertificate

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
        """The SAN editor should be seeded with local IPs, hostname, and request host."""
        self._create_ca(admin_logged_in_client)
        response = admin_logged_in_client.get('/admin-panel/')
        content = response.content.decode('utf-8')
        import socket
        hostname = socket.gethostname()
        assert_that(content, contains_string(hostname))
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
        from my_tracks.models import ClientCertificate
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
        assert_that(cert.common_name, equal_to('testuser'))  # type: ignore[union-attr]

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
        from my_tracks.models import ClientCertificate
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
        from my_tracks.models import ClientCertificate
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
        from my_tracks.models import ClientCertificate
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
        from my_tracks.models import ClientCertificate
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
        from my_tracks.models import ClientCertificate
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
        from my_tracks.models import ClientCertificate
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
        from my_tracks.models import ClientCertificate
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
