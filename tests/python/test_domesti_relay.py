"""Tests for live domesti-bot location relay."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from hamcrest import assert_that, contains_string, equal_to, is_
from rest_framework import status
from rest_framework.test import APIClient

from app.domesti_bot import pair_domesti_bot
from app.domesti_relay import relay_location_to_domesti_bot
from app.models import Device, DomestiBotConfig, Location


@pytest.fixture
def owner(db: Any) -> User:
    return User.objects.create_user(username="kristen", password="secret")


@pytest.fixture
def device(owner: User) -> Device:
    return Device.objects.create(
        owner=owner,
        device_id="pixel7pro",
        name="Pixel",
        mqtt_user=owner.username,
    )


@pytest.fixture
def location(device: Device) -> Location:
    return Location.objects.create(
        device=device,
        latitude=Decimal("41.194085"),
        longitude=Decimal("-73.888365"),
        timestamp=timezone.now(),
        accuracy=12,
        received_via="mqtt",
    )


def _pair_config() -> DomestiBotConfig:
    config = DomestiBotConfig.get_solo()
    pair_domesti_bot(
        config,
        api_key="domesti-secret-key",
        participant_location_update_url="http://192.168.1.10:8003/v1/webhooks/presence",
        participant_location_test_url="http://192.168.1.10:8003/v1/webhooks/presence/test",
        domesti_base_url="http://192.168.1.10:8003",
    )
    return DomestiBotConfig.get_solo()


def test_relay_skips_when_not_paired(location: Location) -> None:
    with patch("app.domesti_relay.send_location_webhook") as mock_send:
        relay_location_to_domesti_bot(location)
    mock_send.assert_not_called()


def test_relay_skips_when_disabled(location: Location) -> None:
    config = _pair_config()
    config.location_updates_enabled = False
    config.save(update_fields=["location_updates_enabled"])

    with patch("app.domesti_relay.send_location_webhook") as mock_send:
        relay_location_to_domesti_bot(location)
    mock_send.assert_not_called()


def test_relay_posts_live_payload(location: Location) -> None:
    _pair_config()
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response):
        relay_location_to_domesti_bot(location)

    recent_log = cast(list[dict[str, Any]], DomestiBotConfig.get_solo().recent_webhook_log)
    assert_that(recent_log[0]["source"], equal_to("live"))
    assert_that(
        recent_log[0]["post_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence"),
    )


def test_relay_logs_network_delivery_failure(location: Location) -> None:
    _pair_config()
    with patch(
        "app.domesti_bot.urllib.request.urlopen",
        side_effect=__import__("urllib").error.URLError("connection refused"),
    ):
        relay_location_to_domesti_bot(location)

    recent_log = cast(list[dict[str, Any]], DomestiBotConfig.get_solo().recent_webhook_log)
    assert_that(recent_log[0]["source"], equal_to("live"))
    assert_that(recent_log[0]["success"], is_(False))
    assert_that(
        recent_log[0]["post_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence"),
    )
    assert_that(recent_log[0]["response_preview"], contains_string("connection refused"))


def test_relay_logs_unexpected_delivery_error(location: Location) -> None:
    _pair_config()
    with patch("app.domesti_bot.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        relay_location_to_domesti_bot(location)

    recent_log = cast(list[dict[str, Any]], DomestiBotConfig.get_solo().recent_webhook_log)
    assert_that(recent_log[0]["source"], equal_to("live"))
    assert_that(recent_log[0]["success"], is_(False))
    assert_that(recent_log[0]["response_preview"], contains_string("boom"))


def test_relay_logs_pre_send_errors_in_activity_log(location: Location) -> None:
    _pair_config()
    with patch("app.domesti_relay.send_location_webhook", side_effect=ValueError("api_key is not configured")):
        relay_location_to_domesti_bot(location)

    recent_log = cast(list[dict[str, Any]], DomestiBotConfig.get_solo().recent_webhook_log)
    assert_that(recent_log[0]["source"], equal_to("live"))
    assert_that(recent_log[0]["success"], is_(False))
    assert_that(recent_log[0]["response_preview"], contains_string("api_key is not configured"))


def test_mqtt_save_location_triggers_relay(owner: User) -> None:
    from app.mqtt.plugin import save_location_to_db

    _pair_config()
    with patch("app.domesti_relay.relay_location_to_domesti_bot") as mock_relay:
        save_location_to_db(
            {
                "device": "pixel7pro",
                "latitude": 41.194085,
                "longitude": -73.888365,
                "timestamp": timezone.now(),
                "mqtt_user": owner.username,
                "tls_cn": owner.username,
                "accuracy": 12,
            }
        )
    mock_relay.assert_called_once()


def test_http_location_create_triggers_relay(owner: User) -> None:
    _pair_config()
    Device.objects.create(owner=owner, device_id="pixel7pro", mqtt_user=owner.username)
    client = APIClient()
    with patch("app.domesti_relay.relay_location_to_domesti_bot") as mock_relay:
        response = client.post(
            "/api/locations/",
            {
                "_type": "location",
                "tid": "pixel7pro",
                "lat": 41.194085,
                "lon": -73.888365,
                "tst": int(timezone.now().timestamp()),
                "acc": 12,
            },
            format="json",
        )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    mock_relay.assert_called_once()
