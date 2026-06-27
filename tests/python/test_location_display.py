"""Tests for location display formatting."""

from hamcrest import assert_that, equal_to

from app.location_display import (
    format_connection_type_display,
    location_network_vac_log_fragment,
    location_network_vac_log_fragment_from_mapping,
)


def test_format_connection_type_wifi_with_ssid() -> None:
    assert_that(
        format_connection_type_display("w", wifi_ssid="familia"),
        equal_to("WiFi (familia)"),
    )


def test_format_connection_type_wifi_without_ssid() -> None:
    assert_that(format_connection_type_display("w"), equal_to("WiFi"))


def test_format_connection_type_mobile() -> None:
    assert_that(format_connection_type_display("m"), equal_to("Mobile"))


def test_format_connection_type_missing() -> None:
    assert_that(format_connection_type_display(None), equal_to("N/A"))


def test_location_network_vac_log_fragment_full() -> None:
    assert_that(
        location_network_vac_log_fragment(
            vertical_accuracy=100,
            fix_source="network",
            connection_type="w",
            wifi_ssid="familia",
        ),
        equal_to(", vac=100m, conn=WiFi (familia), src=network"),
    )


def test_location_network_vac_log_fragment_empty() -> None:
    assert_that(location_network_vac_log_fragment(), equal_to(""))


def test_location_network_vac_log_fragment_from_mapping() -> None:
    fragment = location_network_vac_log_fragment_from_mapping(
        {
            "vertical_accuracy": 8,
            "fix_source": "gps",
            "connection_type": "m",
            "wifi_ssid": "",
        }
    )
    assert_that(fragment, equal_to(", vac=8m, conn=Mobile, src=gps"))


def test_location_network_vac_log_fragment_escapes_unsafe_values() -> None:
    assert_that(
        location_network_vac_log_fragment(
            fix_source="net,work",
            connection_type="w",
            wifi_ssid="evil\r\nssid",
        ),
        equal_to(r", conn=WiFi (evil\r\nssid), src=net\,work"),
    )
