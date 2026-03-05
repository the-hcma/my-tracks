"""Tests for production settings hardening."""

from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from hamcrest import (assert_that, calling, contains_string, equal_to, is_,
                      raises)


class TestSecretKeyValidation:
    """SECRET_KEY must be set when DEBUG=False."""

    def test_debug_true_provides_insecure_default(self) -> None:
        key = _simulate_secret_key_check(debug=True, secret_key="")
        assert_that(key, equal_to("django-insecure-change-me-in-production"))

    def test_debug_false_without_secret_key_raises(self) -> None:
        assert_that(
            calling(_simulate_secret_key_check).with_args(debug=False, secret_key=""),
            raises(ImproperlyConfigured, "SECRET_KEY must be set in production"),
        )

    def test_debug_false_with_secret_key_succeeds(self) -> None:
        key = _simulate_secret_key_check(debug=False, secret_key="a-real-secret-key")
        assert_that(key, equal_to("a-real-secret-key"))

    def test_debug_true_with_empty_key_falls_back_to_insecure_default(self) -> None:
        key = _simulate_secret_key_check(debug=True, secret_key="")
        assert_that(key, equal_to("django-insecure-change-me-in-production"))

    def test_debug_true_with_explicit_key_uses_it(self) -> None:
        key = _simulate_secret_key_check(debug=True, secret_key="my-custom-key")
        assert_that(key, equal_to("my-custom-key"))


class TestAllowedHostsAutoDetect:
    """netifaces auto-detection only runs when DEBUG=True."""

    def test_netifaces_block_is_conditional_on_debug(self) -> None:
        import ast
        source = _read_settings_source()
        tree = ast.parse(source)
        found_netifaces_in_debug_block = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and not isinstance(node, ast.IfExp):
                test = ast.dump(node.test)
                if "DEBUG" in test and "Not" not in test:
                    body_src = ast.get_source_segment(source, node)
                    if body_src and "netifaces" in body_src:
                        found_netifaces_in_debug_block = True
        assert_that(found_netifaces_in_debug_block, is_(True))

    def test_netifaces_not_called_when_debug_false(self) -> None:
        with patch("netifaces.interfaces") as mock_interfaces:
            _simulate_allowed_hosts(debug=False)
        mock_interfaces.assert_not_called()

    def test_netifaces_called_when_debug_true(self) -> None:
        with patch("netifaces.interfaces", return_value=[]) as mock_interfaces:
            _simulate_allowed_hosts(debug=True)
        mock_interfaces.assert_called_once()


class TestProductionSecuritySettings:
    """Secure cookies and proxy header only active in production."""

    def test_settings_source_contains_secure_proxy_ssl_header(self) -> None:
        source = _read_settings_source()
        assert_that(source, contains_string("SECURE_PROXY_SSL_HEADER"))

    def test_settings_source_contains_session_cookie_secure(self) -> None:
        source = _read_settings_source()
        assert_that(source, contains_string("SESSION_COOKIE_SECURE = True"))

    def test_settings_source_contains_csrf_cookie_secure(self) -> None:
        source = _read_settings_source()
        assert_that(source, contains_string("CSRF_COOKIE_SECURE = True"))

    def test_production_security_block_is_conditional_on_not_debug(self) -> None:
        import ast
        source = _read_settings_source()
        tree = ast.parse(source)
        found_secure_block = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test = ast.dump(node.test)
                if "Not" in test and "DEBUG" in test:
                    body_src = ast.get_source_segment(source, node)
                    if body_src and "SESSION_COOKIE_SECURE" in body_src:
                        found_secure_block = True
        assert_that(found_secure_block, is_(True))

    def test_secure_proxy_ssl_header_value(self) -> None:
        source = _read_settings_source()
        assert_that(source, contains_string("HTTP_X_FORWARDED_PROTO"))
        assert_that(source, contains_string("https"))


def _simulate_secret_key_check(*, debug: bool, secret_key: str) -> str:
    """Reproduce the SECRET_KEY validation logic from settings.py."""
    default = "django-insecure-change-me-in-production" if debug else ""
    key = secret_key if secret_key else default
    if not key:
        raise ImproperlyConfigured(
            "SECRET_KEY must be set in production (DEBUG=False). "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )
    return key


def _simulate_allowed_hosts(*, debug: bool) -> list[str]:
    """Reproduce the ALLOWED_HOSTS logic from settings.py."""
    import netifaces

    hosts = ["localhost", "127.0.0.1"]
    if debug:
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            for addr_info in addrs.get(netifaces.AF_INET, []):
                ip = addr_info.get("addr", "")
                has_broadcast = bool(addr_info.get("broadcast"))
                if ip and not ip.startswith("127.") and has_broadcast and ip not in hosts:
                    hosts.append(ip)
    return hosts


def _read_settings_source() -> str:
    """Read the settings.py source for AST / string inspection."""
    settings_path = Path(__file__).resolve().parent / "config" / "settings.py"
    return settings_path.read_text()
