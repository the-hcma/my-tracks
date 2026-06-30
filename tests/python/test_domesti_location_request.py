"""Tests for domesti-bot request-location machine API."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_entries,
    has_key,
    has_length,
)
from rest_framework import status
from rest_framework.test import APIClient

from app.domesti_bot import pair_domesti_bot
from app.domesti_bot_auth import DOMESTI_API_KEY_HEADER
from app.domesti_location_request import (
    LOCATION_REQUEST_APPROACH_MONITORING_USER_COOLDOWN_SECONDS,
    LOCATION_REQUEST_USER_COOLDOWN_SECONDS_DEFAULT,
)
from app.models import Device, DomestiBotConfig

ALL_DEVICES_URL = "/api/domesti-bot/users/{user_id}/request-location/"
DEVICE_URL = "/api/domesti-bot/users/{user_id}/devices/{device_id}/request-location/"


@pytest.fixture
def tracked_user(db: Any) -> User:
    return User.objects.create_user(username="kristen")


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _pair_and_enable_remote_request() -> None:
    config = DomestiBotConfig.get_solo()
    pair_domesti_bot(
        config,
        api_key="domesti-secret-key",
        user_location_test_url="http://192.168.1.10:8003/v1/webhooks/presence/test",
        user_location_update_url="http://192.168.1.10:8003/v1/webhooks/presence",
        domesti_base_url="http://192.168.1.10:8003",
    )
    config.remote_request_location_enabled = True
    config.save(update_fields=["remote_request_location_enabled", "updated_at"])


def _auth_headers(api_key: str = "domesti-secret-key") -> dict[str, str]:
    return {DOMESTI_API_KEY_HEADER: api_key}


def _request_body(**overrides: Any) -> dict[str, str]:
    body = {"reason": "accuracy_streak"}
    body.update(overrides)
    return body


def test_request_location_requires_relay_key(api_client: APIClient, db: Any) -> None:
    _pair_and_enable_remote_request()

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id="kristen"),
        _request_body(),
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
    assert_that(response.json()["detail"], equal_to("Invalid or missing domesti-bot API key"))


def test_request_location_rejects_invalid_relay_key(api_client: APIClient, db: Any) -> None:
    _pair_and_enable_remote_request()

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id="kristen"),
        _request_body(),
        format="json",
        headers=_auth_headers("wrong-key"),
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_request_location_rejects_when_capability_disabled(api_client: APIClient, db: Any) -> None:
    config = DomestiBotConfig.get_solo()
    pair_domesti_bot(
        config,
        api_key="domesti-secret-key",
        user_location_test_url="http://192.168.1.10:8003/v1/webhooks/presence/test",
        user_location_update_url="http://192.168.1.10:8003/v1/webhooks/presence",
        domesti_base_url="http://192.168.1.10:8003",
    )

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id="kristen"),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
    assert_that(
        response.json()["detail"],
        equal_to("Remote request-location via API key is disabled"),
    )


def test_request_location_rejects_when_unpaired(api_client: APIClient, db: Any) -> None:
    response = api_client.post(
        ALL_DEVICES_URL.format(user_id="kristen"),
        _request_body(),
        format="json",
        headers=_auth_headers("unused"),
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
    assert_that(response.json()["detail"], equal_to("Not paired"))


def test_admin_export_rejects_relay_key(api_client: APIClient, db: Any) -> None:
    _pair_and_enable_remote_request()

    response = api_client.get(
        "/api/admin/users-with-devices/",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_request_location_unknown_user(api_client: APIClient, db: Any) -> None:
    _pair_and_enable_remote_request()

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id="missing-user"),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    assert_that(response.json()["detail"], contains_string("missing-user"))


def test_request_location_inactive_user(api_client: APIClient, db: Any) -> None:
    _pair_and_enable_remote_request()
    User.objects.create_user(username="inactive-user", is_active=False)

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id="inactive-user"),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    assert_that(response.json()["detail"], contains_string("inactive-user"))


def test_request_all_devices_no_owned_device(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id=tracked_user.username),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    assert_that(response.json()["detail"], contains_string("No owned devices"))


def test_request_location_invalid_reason(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id=tracked_user.username),
        _request_body(reason="invalid"),
        format="json",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_request_all_devices_mqtt_unavailable(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    with patch(
        "app.domesti_location_request.async_to_sync",
        side_effect=RuntimeError("No MQTT client configured"),
    ):
        response = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(),
            format="json",
            headers=_auth_headers(),
        )

    assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
    assert_that(response.json()["detail"], equal_to("MQTT broker unavailable"))
    config = DomestiBotConfig.get_solo()
    assert_that(cast(dict[str, str], config.last_location_request_at_by_user), equal_to({}))


def test_request_all_devices_success(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )
    Device.objects.create(
        owner=tracked_user,
        device_id="ipad",
        mqtt_user=tracked_user.username,
    )

    mock_request_location = MagicMock(return_value=True)
    with patch("app.domesti_location_request.async_to_sync", return_value=mock_request_location):
        response = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason="deferred_edge", rule_id="rule-1", geofence_id="home"),
            format="json",
            headers=_auth_headers(),
        )

    assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
    body = response.json()
    assert_that(body["user_id"], equal_to(tracked_user.username))
    assert_that(body["reason"], equal_to("deferred_edge"))
    assert_that(body["device_ids"], has_length(2))
    assert_that(body, has_key("requested_at"))
    assert_that(body, has_key("cooldown_until"))
    assert_that(body["user_cooldown_seconds"], equal_to(LOCATION_REQUEST_USER_COOLDOWN_SECONDS_DEFAULT))
    assert_that(body["device_cooldown_seconds"], equal_to(2))
    assert_that(
        body["user_cooldown_seconds_by_reason"],
        has_entries({"approach_monitoring": LOCATION_REQUEST_APPROACH_MONITORING_USER_COOLDOWN_SECONDS}),
    )
    assert_that(mock_request_location.call_count, equal_to(2))

    username = str(tracked_user.username)
    config = DomestiBotConfig.get_solo()
    last_by_user = cast(dict[str, str], config.last_location_request_at_by_user)
    assert_that(last_by_user[username], equal_to(body["requested_at"]))


def test_request_single_device_success(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )
    Device.objects.create(
        owner=tracked_user,
        device_id="ipad",
        mqtt_user=tracked_user.username,
    )

    mock_request_location = MagicMock(return_value=True)
    with patch("app.domesti_location_request.async_to_sync", return_value=mock_request_location):
        response = api_client.post(
            DEVICE_URL.format(user_id=tracked_user.username, device_id="ipad"),
            _request_body(reason="boundary_proximity"),
            format="json",
            headers=_auth_headers(),
        )

    assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
    assert_that(
        response.json(),
        has_entries(
            {
                "user_id": tracked_user.username,
                "device_id": f"{tracked_user.username}/ipad",
                "reason": "boundary_proximity",
                "device_cooldown_seconds": 2,
            }
        ),
    )
    mock_request_location.assert_called_once()


def test_request_single_device_unknown_device(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    response = api_client.post(
        DEVICE_URL.format(user_id=tracked_user.username, device_id="missing"),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    assert_that(response.json()["detail"], contains_string("Unknown device"))


def test_request_device_enforces_cooldown(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    requested_at = timezone.now()
    mqtt_device_id = f"{tracked_user.username}/pixel7pro"
    config = DomestiBotConfig.get_solo()
    config.last_location_request_at_by_device = {
        mqtt_device_id: requested_at.isoformat().replace("+00:00", "Z"),
    }
    config.save(update_fields=["last_location_request_at_by_device", "updated_at"])

    response = api_client.post(
        DEVICE_URL.format(user_id=tracked_user.username, device_id="pixel7pro"),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )

    assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
    body = response.json()
    assert_that(body["detail"], equal_to("Device location request cooldown active"))
    assert_that(body, has_key("cooldown_until"))


def test_request_all_devices_enforces_user_cooldown(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    requested_at = timezone.now()
    config = DomestiBotConfig.get_solo()
    config.last_location_request_at_by_user = {
        tracked_user.username: requested_at.isoformat().replace("+00:00", "Z"),
    }
    config.save(update_fields=["last_location_request_at_by_user", "updated_at"])

    response = api_client.post(
        ALL_DEVICES_URL.format(user_id=tracked_user.username),
        _request_body(),
        format="json",
        headers=_auth_headers(),
    )

    assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
    body = response.json()
    assert_that(body["detail"], equal_to("Location request cooldown active"))
    assert_that(body, has_key("cooldown_until"))
    assert_that(body["user_cooldown_seconds"], equal_to(LOCATION_REQUEST_USER_COOLDOWN_SECONDS_DEFAULT))
    assert_that(
        body["user_cooldown_seconds_by_reason"],
        has_entries({"approach_monitoring": LOCATION_REQUEST_APPROACH_MONITORING_USER_COOLDOWN_SECONDS}),
    )


@pytest.mark.parametrize("reason", ["stale_watchdog", "approach_monitoring"])
def test_monitoring_reasons_accepted(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
    reason: str,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    with patch("app.domesti_location_request.async_to_sync", return_value=MagicMock(return_value=True)):
        response = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason=reason),
            format="json",
            headers=_auth_headers(),
        )

    assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
    assert_that(response.json()["reason"], equal_to(reason))


def test_approach_monitoring_allows_shorter_user_cooldown(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
) -> None:
    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    requested_at = timezone.now() - timedelta(seconds=10)
    config = DomestiBotConfig.get_solo()
    config.last_location_request_at_by_user = {
        tracked_user.username: requested_at.isoformat().replace("+00:00", "Z"),
    }
    config.save(update_fields=["last_location_request_at_by_user", "updated_at"])

    with patch("app.domesti_location_request.async_to_sync", return_value=MagicMock(return_value=True)):
        blocked = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason="stale_watchdog"),
            format="json",
            headers=_auth_headers(),
        )
        allowed = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason="approach_monitoring"),
            format="json",
            headers=_auth_headers(),
        )

    assert_that(blocked.status_code, equal_to(status.HTTP_409_CONFLICT))
    assert_that(allowed.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_user_cooldown_default_is_thirty_seconds() -> None:
    assert_that(LOCATION_REQUEST_USER_COOLDOWN_SECONDS_DEFAULT, equal_to(30))


@pytest.fixture
def background_location_request_worker() -> Iterator[None]:
    """Use the in-memory worker thread instead of inline processing."""
    from app.domesti_location_request_queue import (
        drain_location_request_queue,
        set_inline_processing,
        start_location_request_worker,
        stop_location_request_worker,
    )

    set_inline_processing(False)
    start_location_request_worker()
    try:
        yield
    finally:
        try:
            drain_location_request_queue()
        finally:
            stop_location_request_worker()
            set_inline_processing(True)


@pytest.mark.django_db(transaction=True)
def test_async_queue_returns_before_worker_finishes(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
    background_location_request_worker: None,
) -> None:
    from app.domesti_location_request_queue import drain_location_request_queue

    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    publish_gate = threading.Event()

    def blocked_publish(*_args: object, **_kwargs: object) -> bool:
        publish_gate.wait(timeout=1.0)
        return True

    mock_request_location = MagicMock(side_effect=blocked_publish)
    with patch("app.domesti_location_request.async_to_sync", return_value=mock_request_location):
        response = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason="stale_watchdog"),
            format="json",
            headers=_auth_headers(),
        )

        assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
        assert_that(mock_request_location.call_count, equal_to(0))
        publish_gate.set()
        drain_location_request_queue()
        assert_that(mock_request_location.call_count, equal_to(1))


@pytest.mark.django_db(transaction=True)
def test_async_queue_processes_multiple_users_sequentially(
    api_client: APIClient,
    db: Any,
    background_location_request_worker: None,
) -> None:
    from app.domesti_location_request_queue import drain_location_request_queue

    _pair_and_enable_remote_request()
    hcma = User.objects.create_user(username="hcma")
    kristen = User.objects.create_user(username="kristen")
    for user, device_id in ((hcma, "pixel7pro"), (kristen, "pixel7")):
        Device.objects.create(
            owner=user,
            device_id=device_id,
            mqtt_user=user.username,
        )

    mock_request_location = MagicMock(return_value=True)
    with patch("app.domesti_location_request.async_to_sync", return_value=mock_request_location):
        for user_id in ("hcma", "kristen"):
            response = api_client.post(
                ALL_DEVICES_URL.format(user_id=user_id),
                _request_body(reason="stale_watchdog"),
                format="json",
                headers=_auth_headers(),
            )
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))

        drain_location_request_queue()
        assert_that(mock_request_location.call_count, equal_to(2))

    config = DomestiBotConfig.get_solo()
    last_by_user = cast(dict[str, str], config.last_location_request_at_by_user)
    assert_that(last_by_user, has_key("hcma"))
    assert_that(last_by_user, has_key("kristen"))


@pytest.mark.django_db(transaction=True)
def test_async_queue_honors_pending_user_cooldown_before_worker_persists(
    api_client: APIClient,
    db: Any,
    tracked_user: User,
    background_location_request_worker: None,
) -> None:
    from app.domesti_location_request_queue import drain_location_request_queue

    _pair_and_enable_remote_request()
    Device.objects.create(
        owner=tracked_user,
        device_id="pixel7pro",
        mqtt_user=tracked_user.username,
    )

    publish_gate = threading.Event()

    def blocked_publish(*_args: object, **_kwargs: object) -> bool:
        publish_gate.wait(timeout=1.0)
        return True

    mock_request_location = MagicMock(side_effect=blocked_publish)
    with patch("app.domesti_location_request.async_to_sync", return_value=mock_request_location):
        first = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason="stale_watchdog"),
            format="json",
            headers=_auth_headers(),
        )
        second = api_client.post(
            ALL_DEVICES_URL.format(user_id=tracked_user.username),
            _request_body(reason="stale_watchdog"),
            format="json",
            headers=_auth_headers(),
        )

        assert_that(first.status_code, equal_to(status.HTTP_202_ACCEPTED))
        assert_that(second.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(second.json()["detail"], equal_to("Location request cooldown active"))

        publish_gate.set()
        drain_location_request_queue()
        assert_that(mock_request_location.call_count, equal_to(1))
