"""Tests for domesti-bot config model, API, and Admin Panel."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from hamcrest import assert_that, contains_string, equal_to, has_length, is_, not_
from rest_framework import status
from rest_framework.test import APIClient

from app.domesti_bot import (
    TEST_LOCATION_DEFAULT_LAT,
    TEST_LOCATION_DEFAULT_LON,
    append_webhook_log_entry,
    build_location_webhook_payload,
    location_post_url_for_source,
    send_location_webhook,
)
from app.models import DomestiBotConfig


@pytest.fixture
def admin_user(db: Any) -> User:
    return User.objects.create_user(username="admin", password="secret", is_staff=True)


@pytest.fixture
def regular_user(db: Any) -> User:
    return User.objects.create_user(username="henrique", password="secret")


@pytest.fixture
def admin_client(admin_user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def user_client(regular_user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def django_admin_client(admin_user: User) -> Client:
    client = Client()
    client.force_login(admin_user)
    return client


def _pair_payload() -> dict[str, str]:
    return {
        "api_key": "domesti-secret-key",
        "participant_location_update_url": "http://192.168.1.10:8003/v1/webhooks/presence",
        "participant_location_test_url": "http://192.168.1.10:8003/v1/webhooks/presence/test",
        "domesti_base_url": "http://192.168.1.10:8003",
    }


def test_config_get_requires_admin(user_client: APIClient) -> None:
    response = user_client.get("/api/admin/domesti-bot/config/")
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_config_get_unpaired_empty(admin_client: APIClient) -> None:
    response = admin_client.get("/api/admin/domesti-bot/config/")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["is_paired"], is_(False))
    assert_that(body["participant_location_test_url"], equal_to(""))
    assert_that(body["recent_webhook_log"], has_length(0))


def test_pair_stores_encrypted_key_and_enables_updates(admin_client: APIClient) -> None:
    response = admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["api_key_configured"], is_(True))
    assert_that(
        body["participant_location_test_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence/test"),
    )

    config = DomestiBotConfig.get_solo()
    assert_that(
        location_post_url_for_source(config, source="test"),
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence/test"),
    )
    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    assert_that(recent_log, has_length(1))
    assert_that(recent_log[0]["source"], equal_to("pairing"))
    assert_that(recent_log[0]["success"], is_(True))


def test_pair_rejects_invalid_url(admin_client: APIClient) -> None:
    response = admin_client.post(
        "/api/admin/domesti-bot/pair/",
        {"api_key": "x", "participant_location_update_url": "not-a-url", "participant_location_test_url": "x"},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
    recent_log = cast(list[dict[str, Any]], DomestiBotConfig.get_solo().recent_webhook_log)
    assert_that(recent_log, has_length(1))
    assert_that(recent_log[0]["source"], equal_to("pairing"))
    assert_that(recent_log[0]["success"], is_(False))


def test_reveal_api_key_when_paired(admin_client: APIClient) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    response = admin_client.get("/api/admin/domesti-bot/reveal-api-key/")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    assert_that(response.json()["api_key"], equal_to("domesti-secret-key"))


def test_patch_config_requires_pairing(admin_client: APIClient) -> None:
    response = admin_client.patch(
        "/api/admin/domesti-bot/config/",
        {"location_updates_enabled": False},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_patch_config_updates_toggle_when_paired(admin_client: APIClient) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    response = admin_client.patch(
        "/api/admin/domesti-bot/config/",
        {"location_updates_enabled": False},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    assert_that(response.json()["location_updates_enabled"], is_(False))


def test_test_location_update_uses_test_url(admin_client: APIClient, admin_user: User) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok":true}'

    with patch("app.domesti_bot.urllib.request.urlopen", return_value=mock_response):
        response = admin_client.post(
            "/api/admin/domesti-bot/test-location-update/",
            {"participant_id": admin_user.username},
            format="json",
        )

    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    assert_that(response.json()["ok"], is_(True))
    config = DomestiBotConfig.get_solo()
    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    assert_that(recent_log, has_length(2))
    assert_that(recent_log[0]["source"], equal_to("test"))
    assert_that(
        recent_log[0]["post_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence/test"),
    )


def test_test_location_update_reports_failure_with_url(admin_client: APIClient, admin_user: User) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    with patch(
        "app.domesti_bot.urllib.request.urlopen",
        side_effect=__import__("urllib").error.URLError("connection refused"),
    ):
        response = admin_client.post(
            "/api/admin/domesti-bot/test-location-update/",
            {"participant_id": admin_user.username},
            format="json",
        )

    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["ok"], is_(False))
    assert_that(
        body["post_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence/test"),
    )
    assert_that(body["message"], contains_string("connection refused"))
    assert_that(body["message"], contains_string(body["post_url"]))


def test_send_location_webhook_logs_unexpected_delivery_error(admin_client: APIClient, admin_user: User) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    config = DomestiBotConfig.get_solo()
    payload = build_location_webhook_payload(
        participant_id=str(admin_user.username),
        lat=TEST_LOCATION_DEFAULT_LAT,
        lon=TEST_LOCATION_DEFAULT_LON,
    )
    with patch("app.domesti_bot.urllib.request.urlopen", side_effect=RuntimeError("unexpected")):
        entry = send_location_webhook(config, payload=payload, source="test")

    assert_that(entry["success"], is_(False))
    assert_that(entry["response_preview"], contains_string("unexpected"))
    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    assert_that(recent_log[0]["source"], equal_to("test"))
    assert_that(recent_log[0]["success"], is_(False))
    assert_that(
        recent_log[0]["post_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence/test"),
    )


def test_webhook_log_ring_buffer_keeps_five(admin_client: APIClient) -> None:
    config = DomestiBotConfig.get_solo()
    for index in range(7):
        append_webhook_log_entry(
            config,
            {
                "sent_at": timezone.now().isoformat(),
                "success": index % 2 == 0,
                "http_status": 200 if index % 2 == 0 else 500,
                "participant_id": f"user{index}",
                "payload": {"n": index},
                "response_preview": "ok",
                "source": "live",
                "elapsed_ms": 10,
            },
        )
        config.refresh_from_db()

    recent_log = cast(list[dict[str, Any]], config.recent_webhook_log)
    assert_that(recent_log, has_length(5))


def test_admin_panel_integrations_tab(django_admin_client: Client, admin_client: APIClient) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    response = django_admin_client.get("/admin-panel/")
    assert_that(response.status_code, equal_to(200))
    content = response.content.decode()
    assert_that(content, contains_string('data-tab="integrations"'))
    assert_that(content, contains_string("Integrations"))
    assert_that(content, contains_string('class="pairing-badge paired">Paired</span>'))
    assert_that(
        content,
        contains_string(
            'href="http://192.168.1.10:8003" target="_blank" rel="noopener noreferrer">domesti-bot</a> again.'
        ),
    )
    assert_that(content, contains_string("Test location update webhook"))
    assert_that(content, contains_string("domesti-bot instance"))
    assert_that(content, contains_string("http://192.168.1.10:8003"))
    assert_that(content, contains_string('id="domesti-api-key-toggle"'))
    assert_that(content, contains_string("js-domesti-paired-at"))
    assert_that(content, not_(contains_string("Recent activity (last 5)")))
    assert_that(content, not_(contains_string("Save domesti-bot settings")))


def test_admin_panel_toggle_via_api(admin_client: APIClient) -> None:
    admin_client.post("/api/admin/domesti-bot/pair/", _pair_payload(), format="json")
    response = admin_client.patch(
        "/api/admin/domesti-bot/config/",
        {"location_updates_enabled": False},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    config = DomestiBotConfig.get_solo()
    assert_that(bool(config.location_updates_enabled), is_(False))
