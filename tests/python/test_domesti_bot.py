"""Tests for domesti-bot config model, API, and Admin Panel."""

from __future__ import annotations

from typing import Any, cast

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from hamcrest import assert_that, contains_string, equal_to, has_length, is_
from rest_framework import status
from rest_framework.test import APIClient

from app.domesti_bot import append_webhook_log_entry
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


def test_config_get_requires_admin(user_client: APIClient) -> None:
    response = user_client.get("/api/admin/domesti-bot/config/")
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_config_get_unpaired_empty(admin_client: APIClient) -> None:
    response = admin_client.get("/api/admin/domesti-bot/config/")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["is_paired"], is_(False))
    assert_that(body["api_key_configured"], is_(False))
    assert_that(body["location_updates_enabled"], is_(False))
    assert_that(body["domesti_base_url"], equal_to(""))
    assert_that(body["participant_location_update_url"], equal_to(""))
    assert_that(body["recent_webhook_log"], has_length(0))
    assert_that(body["domesti_bot_repo_url"], equal_to("https://github.com/the-hcma/domesti-bot"))


def test_pair_stores_encrypted_key_and_enables_updates(admin_client: APIClient) -> None:
    response = admin_client.post(
        "/api/admin/domesti-bot/pair/",
        {
            "api_key": "domesti-secret-key",
            "participant_location_update_url": "http://192.168.1.10:8003/v1/webhooks/presence",
            "domesti_base_url": "http://192.168.1.10:8003",
        },
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["api_key_configured"], is_(True))
    assert_that(body["location_updates_enabled"], is_(True))
    assert_that(
        body["participant_location_update_url"],
        equal_to("http://192.168.1.10:8003/v1/webhooks/presence"),
    )
    assert_that(body["paired_at"], is_(str))

    config = DomestiBotConfig.get_solo()
    assert_that(config.is_paired, is_(True))
    assert_that(config.get_api_key(), equal_to("domesti-secret-key"))


def test_pair_rejects_invalid_url(admin_client: APIClient) -> None:
    response = admin_client.post(
        "/api/admin/domesti-bot/pair/",
        {"api_key": "x", "participant_location_update_url": "not-a-url"},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
    assert_that(response.json()["errors"][0], contains_string("http"))


def test_patch_config_requires_pairing(admin_client: APIClient) -> None:
    response = admin_client.patch(
        "/api/admin/domesti-bot/config/",
        {"location_updates_enabled": False},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_patch_config_updates_toggle_when_paired(admin_client: APIClient) -> None:
    admin_client.post(
        "/api/admin/domesti-bot/pair/",
        {
            "api_key": "domesti-secret-key",
            "participant_location_update_url": "http://192.168.1.10:8003/v1/webhooks/presence",
        },
        format="json",
    )
    response = admin_client.patch(
        "/api/admin/domesti-bot/config/",
        {"location_updates_enabled": False},
        format="json",
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    assert_that(response.json()["location_updates_enabled"], is_(False))


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
    assert_that(recent_log[0]["participant_id"], equal_to("user6"))


def test_admin_panel_shows_not_paired_domesti_tab(django_admin_client: Client) -> None:
    response = django_admin_client.get("/admin-panel/")
    assert_that(response.status_code, equal_to(200))
    content = response.content.decode()
    assert_that(content, contains_string("Not paired"))
    assert_that(content, contains_string("github.com/the-hcma/domesti-bot"))
    assert_that(content, contains_string('name="domesti_location_updates_enabled" disabled'))


def test_admin_panel_save_domesti_when_paired(django_admin_client: Client, admin_client: APIClient) -> None:
    admin_client.post(
        "/api/admin/domesti-bot/pair/",
        {
            "api_key": "domesti-secret-key",
            "participant_location_update_url": "http://192.168.1.10:8003/v1/webhooks/presence",
        },
        format="json",
    )
    response = django_admin_client.post(
        "/admin-panel/",
        {
            "form_type": "save_domesti_bot",
            "domesti_base_url": "http://192.168.1.20:8003",
            "domesti_participant_location_update_url": "http://192.168.1.20:8003/v1/webhooks/presence",
            "domesti_location_updates_enabled": "on",
        },
        follow=True,
    )
    assert_that(response.status_code, equal_to(200))
    config = DomestiBotConfig.get_solo()
    assert_that(config.domesti_base_url, equal_to("http://192.168.1.20:8003"))
    assert_that(bool(config.location_updates_enabled), is_(True))

    response = django_admin_client.post(
        "/admin-panel/",
        {
            "form_type": "save_domesti_bot",
            "domesti_base_url": "http://192.168.1.20:8003",
            "domesti_participant_location_update_url": "http://192.168.1.20:8003/v1/webhooks/presence",
        },
        follow=True,
    )
    config.refresh_from_db()
    assert_that(bool(config.location_updates_enabled), is_(False))
