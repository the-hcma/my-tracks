"""Tests for live domesti-bot location relay."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from hamcrest import assert_that, contains_string, equal_to, is_, none, not_
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
        user_location_test_url="http://192.168.1.10:8003/v1/webhooks/presence/test",
        user_location_update_url="http://192.168.1.10:8003/v1/webhooks/presence",
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

    config = DomestiBotConfig.get_solo()
    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    assert_that(recent_log[0]["source"], equal_to("live"))
    assert_that(recent_log[0]["user_id"], equal_to("kristen"))
    assert_that(recent_log[0]["payload"]["user_id"], equal_to("kristen"))
    assert_that(
        recent_log[0]["post_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence"),
    )
    last_relayed = cast(dict[str, str], config.last_relayed_location_by_user)
    assert_that(last_relayed.get("kristen"), is_(not_(none())))


def test_relay_includes_connection_type_in_payload(
    location: Location,
) -> None:
    _pair_config()
    location.connection_type = "w"
    location.save(update_fields=["connection_type"])
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response):
        relay_location_to_domesti_bot(location)

    config = DomestiBotConfig.get_solo()
    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    assert_that(recent_log[0]["payload"]["connection_type"], equal_to("w"))


def test_relay_includes_optional_location_metadata_in_payload(
    location: Location,
) -> None:
    _pair_config()
    created_at = timezone.now()
    location.connection_type = "w"
    location.owntracks_message_id = "msg-42"
    location.owntracks_created_at = created_at
    location.trigger = "p"
    location.fix_source = "network"
    location.wifi_ssid = "home"
    location.wifi_bssid = "aa:bb:cc:dd:ee:ff"
    location.in_regions = ["home"]
    location.vertical_accuracy = 8
    location.save(
        update_fields=[
            "connection_type",
            "owntracks_message_id",
            "owntracks_created_at",
            "trigger",
            "fix_source",
            "wifi_ssid",
            "wifi_bssid",
            "in_regions",
            "vertical_accuracy",
        ]
    )
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response):
        relay_location_to_domesti_bot(location)

    config = DomestiBotConfig.get_solo()
    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    payload = cast(dict[str, Any], recent_log[0]["payload"])
    assert_that(payload["source"], equal_to("my-tracks"))
    assert_that(payload["fix_source"], equal_to("network"))
    assert_that(payload["trigger"], equal_to("p"))
    assert_that(payload["wifi_ssid"], equal_to("home"))
    assert_that(payload["in_regions"], equal_to(["home"]))
    assert_that(payload["vertical_accuracy_m"], equal_to(8))
    assert_that(payload["owntracks_message_id"], equal_to("msg-42"))
    assert_that(payload["reported_at"], is_(not_(none())))
    assert_that(payload["timestamp"], is_(not_(none())))


def test_relay_delivers_ping_with_same_fix_and_new_message_id(
    location: Location,
    device: Device,
) -> None:
    _pair_config()
    location.owntracks_message_id = "msg-first"
    location.save(update_fields=["owntracks_message_id"])
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    ping = Location.objects.create(
        device=device,
        latitude=location.latitude,
        longitude=location.longitude,
        timestamp=location.timestamp,
        accuracy=location.accuracy,
        received_via="mqtt",
        trigger="p",
        owntracks_message_id="msg-ping",
        owntracks_created_at=timezone.now(),
    )

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        relay_location_to_domesti_bot(location)
        relay_location_to_domesti_bot(ping)

    assert_that(mock_urlopen.call_count, equal_to(2))


def test_relay_skips_duplicate_location_fix(location: Location) -> None:
    _pair_config()
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    duplicate = Location.objects.create(
        device=location.device,
        latitude=location.latitude,
        longitude=location.longitude,
        timestamp=location.timestamp,
        accuracy=location.accuracy,
        received_via="mqtt",
        owntracks_message_id="same-msg-id",
    )
    location.owntracks_message_id = "same-msg-id"
    location.save(update_fields=["owntracks_message_id"])

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        relay_location_to_domesti_bot(location)
        relay_location_to_domesti_bot(duplicate)

    assert_that(mock_urlopen.call_count, equal_to(1))


def test_relay_retries_after_failed_delivery(location: Location) -> None:
    _pair_config()
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    with patch(
        "app.domesti_bot.urllib.request.urlopen",
        side_effect=[
            __import__("urllib").error.URLError("connection refused"),
            mock_response,
        ],
    ) as mock_urlopen:
        relay_location_to_domesti_bot(location)
        relay_location_to_domesti_bot(location)

    assert_that(mock_urlopen.call_count, equal_to(2))
    config = DomestiBotConfig.get_solo()
    last_relayed = cast(dict[str, str], config.last_relayed_location_by_user)
    assert_that(last_relayed.get("kristen"), is_(not_(none())))


def test_relay_delivers_newer_location_after_prior_fix(location: Location, device: Device) -> None:
    _pair_config()
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    newer = Location.objects.create(
        device=device,
        latitude=Decimal("41.195000"),
        longitude=Decimal("-73.889000"),
        timestamp=timezone.now(),
        accuracy=10,
        received_via="mqtt",
    )

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        relay_location_to_domesti_bot(location)
        relay_location_to_domesti_bot(newer)

    assert_that(mock_urlopen.call_count, equal_to(2))


def test_relay_delivers_sub_meter_coordinate_differences(location: Location, device: Device) -> None:
    _pair_config()
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    nearby = Location.objects.create(
        device=device,
        latitude=Decimal("41.1940851"),
        longitude=Decimal("-73.8883651"),
        timestamp=location.timestamp,
        accuracy=12,
        received_via="mqtt",
    )

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        relay_location_to_domesti_bot(location)
        relay_location_to_domesti_bot(nearby)

    assert_that(mock_urlopen.call_count, equal_to(2))


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


@pytest.mark.asyncio
async def test_mqtt_handle_location_triggers_relay(owner: User, device: Device) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.mqtt.plugin import OwnTracksPlugin

    ts = int(timezone.now().timestamp())
    serialized = {
        "id": 101,
        "device": device.pk,
        "timestamp_unix": ts,
        "device_name": f"{owner.username}/pixel7pro",
    }
    mock_location = MagicMock()
    mock_location.device.owner = owner
    mock_qs = MagicMock()
    mock_qs.get.return_value = mock_location

    plugin = OwnTracksPlugin(MagicMock())
    payload = {
        "device": device.device_id,
        "latitude": 41.194085,
        "longitude": -73.888365,
        "timestamp": timezone.now(),
        "mqtt_user": owner.username,
        "tls_cn": owner.username,
        "transport": "mqtt-tls",
    }

    with (
        patch("app.mqtt.plugin.save_location_to_db", return_value=serialized),
        patch("app.mqtt.plugin.Location.objects.select_related", return_value=mock_qs),
        patch("app.domesti_relay.relay_location_to_domesti_bot") as mock_relay,
        patch.object(plugin, "_broadcast_location", AsyncMock()),
    ):
        await plugin._handle_location(payload)

    mock_relay.assert_called_once()


def test_http_location_create_does_not_trigger_relay(owner: User) -> None:
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
    mock_relay.assert_not_called()
