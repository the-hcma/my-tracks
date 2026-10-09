"""Relay key protocol 2 pairing: stage, probe, activate, abort and state (nothing switches before activation)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from hamcrest import assert_that, contains_string, equal_to, is_, not_
from rest_framework import status
from rest_framework.test import APIClient

from app.domesti_bot_auth import DOMESTI_API_KEY_HEADER, DOMESTI_PAIRING_ID_HEADER
from app.domesti_relay_keys import relay_key_verifier
from app.models import DomestiBotConfig

# Built rather than written as literals so secret scanners do not flag them.
_K_IN = "-".join(["inbound", "relay", "key", "0123456789"])
_K_OUT = "-".join(["outbound", "relay", "key", "9876543210"])
_K_OLD = "-".join(["shared", "legacy", "key", "1111111111"])
_PAIRING = "pairing-0001-abcdef"
PAIR = "/api/admin/domesti-bot/pair/"
ACTIVATE = "/api/admin/domesti-bot/pair/activate/"
ABORT = "/api/admin/domesti-bot/pair/abort/"
STATE = "/api/admin/domesti-bot/pair/state/"
TEST_UPDATE = "/api/admin/domesti-bot/test-location-update/"
AUTH_CHECK = "/api/domesti-bot/auth-check/"
REQUEST_LOCATION = "/api/domesti-bot/users/kristen/request-location/"


@pytest.fixture
def admin_client(db: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=User.objects.create_user(username="admin", password="x", is_staff=True))
    return client


@pytest.fixture
def user_client(db: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=User.objects.create_user(username="henrique", password="x"))
    return client


def _payload(**overrides: Any) -> dict[str, str]:
    body = {
        "protocol_version": 2,
        "pairing_id": _PAIRING,
        "api_key": _K_IN,
        "outbound_api_key": _K_OUT,
        "user_location_test_url": "http://192.168.1.10:8003/v1/webhooks/location_update/test",
        "user_location_update_url": "http://192.168.1.10:8003/v1/webhooks/location_update",
        "domesti_base_url": "http://192.168.1.10:8003",
    }
    body.update(overrides)
    return cast(dict[str, str], body)


def _pending_of(config: DomestiBotConfig) -> dict[str, Any]:
    return cast(dict[str, Any], config.pending_pairing)


def _expire_pending(config: DomestiBotConfig) -> None:
    config.pending_pairing = {**_pending_of(config), "expires_at": (timezone.now() - timedelta(seconds=1)).isoformat()}
    config.save()


def _legacy_pair(client: APIClient) -> None:
    body = _payload()
    body.pop("protocol_version")
    body.pop("pairing_id")
    body.pop("outbound_api_key")
    body["api_key"] = _K_OLD
    assert_that(client.post(PAIR, body, format="json").status_code, equal_to(status.HTTP_200_OK))


# --- stage --------------------------------------------------------------------------------------------------


def test_stage_keeps_the_active_pairing_untouched_and_reports_staged(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    before = DomestiBotConfig.get_solo()
    old_cipher, old_paired_at = cast(bytes, before.encrypted_api_key), before.paired_at

    response = admin_client.post(PAIR, _payload(), format="json")

    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["status"], equal_to("staged"))
    assert_that(body["protocol_version"], equal_to(2))
    assert_that(body["pairing_id"], equal_to(_PAIRING))
    config = DomestiBotConfig.get_solo()
    assert_that(cast(bytes, config.encrypted_api_key), equal_to(old_cipher))
    assert_that(config.paired_at, equal_to(old_paired_at))
    assert_that(config.protocol_version, equal_to(1))
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))
    assert_that(config.outbound_key_matches(_K_OUT), is_(False))


def test_stage_works_on_a_my_tracks_that_was_never_paired(admin_client: APIClient) -> None:
    response = admin_client.post(PAIR, _payload(), format="json")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    config = DomestiBotConfig.get_solo()
    assert_that(config.is_paired, is_(False))
    assert_that(bool(config.pending_pairing), is_(True))


def test_stage_stores_no_plaintext_key_and_never_logs_or_returns_one(
    admin_client: APIClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = admin_client.post(PAIR, _payload(), format="json")
    config = DomestiBotConfig.get_solo()
    stored = str(config.pending_pairing)
    for text in (response.content.decode(), stored, caplog.text):
        assert_that(_K_IN in text, is_(False))
        assert_that(_K_OUT in text, is_(False))
    assert_that(_pending_of(config)["outbound_key_verifier"], equal_to(relay_key_verifier(_K_OUT)))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"pairing_id": ""}, "pairing_id is required"),
        ({"pairing_id": "short"}, "pairing_id is required"),
        ({"pairing_id": "bad id with spaces!"}, "pairing_id is required"),
        ({"outbound_api_key": ""}, "outbound_api_key are required"),
        ({"api_key": ""}, "outbound_api_key are required"),
        ({"outbound_api_key": _K_IN}, "must differ"),
        ({"user_location_update_url": "not-a-url"}, "URL must use http or https"),
        ({"protocol_version": "two"}, "protocol_version must be an integer"),
        ({"protocol_version": 0}, "at least 1"),
    ],
)
def test_stage_rejects_bad_requests_without_changing_anything(
    admin_client: APIClient, overrides: dict[str, str], message: str
) -> None:
    response = admin_client.post(PAIR, _payload(**overrides), format="json")
    assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
    assert_that(response.json()["errors"][0], contains_string(message))
    assert_that(bool(DomestiBotConfig.get_solo().pending_pairing), is_(False))


def test_a_newer_protocol_request_is_answered_with_version_2(admin_client: APIClient) -> None:
    response = admin_client.post(PAIR, _payload(protocol_version=7), format="json")
    assert_that(response.json()["protocol_version"], equal_to(2))


def test_a_second_stage_replaces_the_first(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(PAIR, _payload(pairing_id="pairing-0002-abcdef"), format="json")
    assert_that(_pending_of(DomestiBotConfig.get_solo())["pairing_id"], equal_to("pairing-0002-abcdef"))
    assert_that(admin_client.get(STATE, {"pairing_id": _PAIRING}).json()["status"], equal_to("unknown"))


def test_a_version_1_request_still_pairs_as_before_and_drops_protocol_2_state(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    assert_that(DomestiBotConfig.get_solo().protocol_version, equal_to(2))

    _legacy_pair(admin_client)

    config = DomestiBotConfig.get_solo()
    assert_that(config.protocol_version, equal_to(1))
    assert_that(config.outbound_key_verifier, equal_to(""))
    assert_that(config.activated_pairing_id, equal_to(""))
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))
    assert_that(config.outbound_key_matches(_K_OUT), is_(False))


def test_staging_requires_an_admin(user_client: APIClient) -> None:
    for url in (PAIR, ACTIVATE, ABORT):
        assert_that(user_client.post(url, _payload(), format="json").status_code, equal_to(status.HTTP_403_FORBIDDEN))
    assert_that(user_client.get(STATE).status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- probe --------------------------------------------------------------------------------------------------


def _ok_response() -> MagicMock:
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b"{}"
    mock_response.__enter__.return_value = mock_response
    return mock_response


def test_probe_posts_to_the_staged_url_with_the_staged_inbound_key(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    User.objects.create_user(username="kristen")
    admin_client.post(PAIR, _payload(user_location_test_url="http://192.168.1.99:8003/staged/test"), format="json")
    with patch("app.domesti_bot.urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        response = admin_client.post(TEST_UPDATE, {"user_id": "kristen", "pairing_id": _PAIRING}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    sent = urlopen.call_args.args[0]
    assert_that(sent.full_url, equal_to("http://192.168.1.99:8003/staged/test"))
    assert_that(sent.get_header("X-domesti-api-key"), equal_to(_K_IN))


def test_without_a_pairing_id_the_test_still_uses_the_active_pairing(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    User.objects.create_user(username="kristen")
    admin_client.post(PAIR, _payload(), format="json")
    with patch("app.domesti_bot.urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        admin_client.post(TEST_UPDATE, {"user_id": "kristen"}, format="json")
    assert_that(urlopen.call_args.args[0].get_header("X-domesti-api-key"), equal_to(_K_OLD))


def test_probe_of_an_unknown_expired_or_missing_pairing_is_refused(admin_client: APIClient) -> None:
    User.objects.create_user(username="kristen")
    unknown = admin_client.post(TEST_UPDATE, {"user_id": "kristen", "pairing_id": "nope-nope-nope"}, format="json")
    assert_that(unknown.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    admin_client.post(PAIR, _payload(), format="json")
    config = DomestiBotConfig.get_solo()
    _expire_pending(config)
    expired = admin_client.post(TEST_UPDATE, {"user_id": "kristen", "pairing_id": _PAIRING}, format="json")
    assert_that(expired.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- activate -----------------------------------------------------------------------------------------------


def test_activate_promotes_the_staged_pairing_and_is_idempotent(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    admin_client.post(PAIR, _payload(), format="json")

    first = admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    second = admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")

    assert_that(first.status_code, equal_to(status.HTTP_200_OK))
    assert_that(first.json()["status"], equal_to("active"))
    assert_that(second.status_code, equal_to(status.HTTP_200_OK))
    config = DomestiBotConfig.get_solo()
    assert_that(config.protocol_version, equal_to(2))
    assert_that(config.get_api_key(), equal_to(_K_IN))
    assert_that(config.outbound_key_matches(_K_OUT), is_(True))
    assert_that(config.outbound_key_matches(_K_IN), is_(False))
    assert_that(config.pending_pairing, equal_to({}))
    assert_that(config.activated_pairing_id, equal_to(_PAIRING))
    assert_that(config.is_paired, is_(True))


def test_the_old_shared_key_keeps_working_for_a_short_grace_then_stops(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")

    config = DomestiBotConfig.get_solo()
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))

    config.previous_outbound_key_expires_at = timezone.now() - timedelta(seconds=1)
    config.save()
    assert_that(config.outbound_key_matches(_K_OLD), is_(False))
    assert_that(config.outbound_key_matches(_K_OUT), is_(True))


def test_a_second_activation_keeps_only_the_one_previous_key(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    second_out = "-".join(["second", "outbound", "key", "2222222222"])
    admin_client.post(PAIR, _payload(pairing_id="pairing-0002-abcdef", outbound_api_key=second_out), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": "pairing-0002-abcdef"}, format="json")

    config = DomestiBotConfig.get_solo()
    assert_that(config.outbound_key_matches(second_out), is_(True))
    assert_that(config.outbound_key_matches(_K_OUT), is_(True))  # the previous one, in its grace window
    config.previous_outbound_key_expires_at = timezone.now() - timedelta(seconds=1)
    config.save()
    assert_that(config.outbound_key_matches(_K_OUT), is_(False))


def test_activate_unknown_and_expired_pairings(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    unknown = admin_client.post(ACTIVATE, {"pairing_id": "does-not-exist"}, format="json")
    assert_that(unknown.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    assert_that(unknown.json()["status"], equal_to("unknown"))
    assert_that(admin_client.post(ACTIVATE, {}, format="json").status_code, equal_to(status.HTTP_404_NOT_FOUND))

    admin_client.post(PAIR, _payload(), format="json")
    config = DomestiBotConfig.get_solo()
    _expire_pending(config)
    expired = admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    assert_that(expired.status_code, equal_to(status.HTTP_410_GONE))
    config = DomestiBotConfig.get_solo()
    assert_that(config.protocol_version, equal_to(1))
    assert_that(config.pending_pairing, equal_to({}))
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))


def test_activate_of_a_different_pairing_id_does_not_promote_the_staged_one(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    response = admin_client.post(ACTIVATE, {"pairing_id": "some-other-pairing"}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    assert_that(DomestiBotConfig.get_solo().protocol_version, equal_to(1))
    assert_that(bool(DomestiBotConfig.get_solo().pending_pairing), is_(True))


# --- abort and state ----------------------------------------------------------------------------------------


def test_abort_discards_a_staged_pairing_and_is_idempotent(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    admin_client.post(PAIR, _payload(), format="json")
    first = admin_client.post(ABORT, {"pairing_id": _PAIRING}, format="json")
    second = admin_client.post(ABORT, {"pairing_id": _PAIRING}, format="json")
    assert_that(first.json()["status"], equal_to("aborted"))
    assert_that(second.status_code, equal_to(status.HTTP_200_OK))
    assert_that(second.json()["status"], equal_to("unknown"))
    config = DomestiBotConfig.get_solo()
    assert_that(config.pending_pairing, equal_to({}))
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))


def test_abort_after_activation_is_refused_and_changes_nothing(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    response = admin_client.post(ABORT, {"pairing_id": _PAIRING}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
    assert_that(DomestiBotConfig.get_solo().protocol_version, equal_to(2))


def test_state_walks_through_the_lifecycle(admin_client: APIClient) -> None:
    def state() -> str:
        return admin_client.get(STATE, {"pairing_id": _PAIRING}).json()["status"]

    assert_that(state(), equal_to("unknown"))
    admin_client.post(PAIR, _payload(), format="json")
    assert_that(state(), equal_to("staged"))
    config = DomestiBotConfig.get_solo()
    _expire_pending(config)
    assert_that(state(), equal_to("expired"))
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    assert_that(state(), equal_to("active"))


# --- end to end ---------------------------------------------------------------------------------------------


def test_full_rotation_from_a_shared_key_to_two_keys(admin_client: APIClient) -> None:
    client = APIClient()
    _legacy_pair(admin_client)
    config = DomestiBotConfig.get_solo()
    config.remote_request_location_enabled = True
    config.save()
    headers_old = {DOMESTI_API_KEY_HEADER: _K_OLD}
    assert_that(client.get(AUTH_CHECK, headers=headers_old).status_code, equal_to(status.HTTP_200_OK))

    admin_client.post(PAIR, _payload(), format="json")
    staged = {DOMESTI_API_KEY_HEADER: _K_OUT, DOMESTI_PAIRING_ID_HEADER: _PAIRING}
    assert_that(client.get(AUTH_CHECK, headers=staged).json()["key"], equal_to("pending"))
    assert_that(client.get(AUTH_CHECK, headers=headers_old).status_code, equal_to(status.HTTP_200_OK))

    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    active = client.get(AUTH_CHECK, headers={DOMESTI_API_KEY_HEADER: _K_OUT})
    assert_that(active.json(), equal_to({"ok": True, "key": "active", "protocol_version": 2}))
    assert_that(
        client.get(AUTH_CHECK, headers={DOMESTI_API_KEY_HEADER: _K_IN}).status_code, equal_to(status.HTTP_403_FORBIDDEN)
    )
    assert_that(
        client.post(
            REQUEST_LOCATION, {"reason": "x"}, format="json", headers={DOMESTI_API_KEY_HEADER: _K_OUT}
        ).status_code,
        not_(equal_to(status.HTTP_403_FORBIDDEN)),
    )


def test_admin_panel_shows_the_protocol_version_and_a_staged_pairing(admin_client: APIClient) -> None:
    from django.test import Client

    browser = Client()
    browser.force_login(User.objects.get(username="admin"))
    _legacy_pair(admin_client)
    body = browser.get("/admin-panel/").content.decode()
    assert_that(body, contains_string("Version 1: one shared key for both directions"))
    assert_that(body, not_(contains_string("staged and waiting")))

    admin_client.post(PAIR, _payload(), format="json")
    assert_that(browser.get("/admin-panel/").content.decode(), contains_string("staged and waiting"))

    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    body = browser.get("/admin-panel/").content.decode()
    assert_that(body, contains_string("Version 2: separate keys per direction"))
    assert_that(body, not_(contains_string(_K_IN)))
    assert_that(body, not_(contains_string(_K_OUT)))


# --- review fixes -------------------------------------------------------------------------------------------


def test_staging_the_id_of_the_active_pairing_is_refused_and_nothing_changes(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    before = DomestiBotConfig.get_solo()
    verifier = before.outbound_key_verifier

    response = admin_client.post(
        PAIR, _payload(outbound_api_key="-".join(["other", "out", "key", "3333333333"])), format="json"
    )

    assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
    assert_that(response.json()["errors"][0], contains_string("already the active pairing"))
    config = DomestiBotConfig.get_solo()
    assert_that(config.pending_pairing, equal_to({}))
    assert_that(config.outbound_key_verifier, equal_to(verifier))


@pytest.mark.parametrize("bad", ["x" * 200, "has space here", "short", "ünïcödé-pairing"])
def test_a_malformed_pairing_id_is_an_unknown_pairing_never_a_500(admin_client: APIClient, bad: str) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    assert_that(admin_client.post(ACTIVATE, {"pairing_id": bad}, format="json").status_code, equal_to(404))
    assert_that(admin_client.post(ABORT, {"pairing_id": bad}, format="json").json()["status"], equal_to("unknown"))
    assert_that(admin_client.get(STATE, {"pairing_id": bad}).json()["status"], equal_to("unknown"))
    probe = admin_client.post(TEST_UPDATE, {"pairing_id": bad}, format="json")
    assert_that(probe.status_code, equal_to(404))
    assert_that(bool(DomestiBotConfig.get_solo().pending_pairing), is_(True))


@pytest.mark.parametrize("version", ["2", 2.0, "2.0", True])
def test_protocol_version_given_as_a_string_float_or_bool(admin_client: APIClient, version: Any) -> None:
    response = admin_client.post(PAIR, _payload(protocol_version=version), format="json")
    if version in ("2", 2.0):
        assert_that(response.json()["status"], equal_to("staged"))
    else:
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@pytest.mark.parametrize("damage", ["not a dict", {"pairing_id": _PAIRING}, {"pairing_id": _PAIRING, "expires_at": 5}])
def test_a_damaged_staged_record_is_unknown_and_activation_clears_it(admin_client: APIClient, damage: Any) -> None:
    _legacy_pair(admin_client)
    config = DomestiBotConfig.get_solo()
    config.pending_pairing = damage
    config.save()
    assert_that(admin_client.get(STATE, {"pairing_id": _PAIRING}).json()["status"], equal_to("unknown"))
    response = admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    config = DomestiBotConfig.get_solo()
    assert_that(config.pending_pairing, equal_to({}))
    assert_that(config.protocol_version, equal_to(1))
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))


def test_a_staged_record_with_bad_base64_does_not_activate_and_is_cleared(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    admin_client.post(PAIR, _payload(), format="json")
    config = DomestiBotConfig.get_solo()
    config.pending_pairing = {**_pending_of(config), "encrypted_api_key": "***not base64***"}
    config.save()
    response = admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    config = DomestiBotConfig.get_solo()
    assert_that(config.pending_pairing, equal_to({}))
    assert_that(config.outbound_key_matches(_K_OLD), is_(True))


def test_activation_succeeds_even_when_the_old_shared_key_cannot_be_decrypted(admin_client: APIClient) -> None:
    _legacy_pair(admin_client)
    config = DomestiBotConfig.get_solo()
    config.encrypted_api_key = b"this is not a valid fernet token"
    config.save()
    admin_client.post(PAIR, _payload(), format="json")

    response = admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")

    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    config = DomestiBotConfig.get_solo()
    assert_that(config.protocol_version, equal_to(2))
    assert_that(config.outbound_key_matches(_K_OUT), is_(True))
    assert_that(config.previous_outbound_key_verifier, equal_to(""))


def test_probe_with_an_undecryptable_staged_key_is_refused_without_a_500(admin_client: APIClient) -> None:
    User.objects.create_user(username="kristen")
    admin_client.post(PAIR, _payload(), format="json")
    config = DomestiBotConfig.get_solo()
    config.pending_pairing = {**_pending_of(config), "encrypted_api_key": "AAAA"}
    config.save()
    response = admin_client.post(TEST_UPDATE, {"user_id": "kristen", "pairing_id": _PAIRING}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_probe_of_a_staged_pairing_works_before_the_first_pairing_completes(admin_client: APIClient) -> None:
    User.objects.create_user(username="kristen")
    admin_client.post(PAIR, _payload(), format="json")
    assert_that(DomestiBotConfig.get_solo().is_paired, is_(False))
    with patch("app.domesti_bot.urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        response = admin_client.post(TEST_UPDATE, {"user_id": "kristen", "pairing_id": _PAIRING}, format="json")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    assert_that(urlopen.call_args.args[0].get_header("X-domesti-api-key"), equal_to(_K_IN))


def test_a_legacy_pair_after_an_activation_leaves_a_consistent_protocol_1_state(admin_client: APIClient) -> None:
    admin_client.post(PAIR, _payload(), format="json")
    admin_client.post(ACTIVATE, {"pairing_id": _PAIRING}, format="json")
    _legacy_pair(admin_client)
    state = admin_client.get(STATE, {"pairing_id": _PAIRING}).json()["status"]
    assert_that(state, equal_to("unknown"))
    config = DomestiBotConfig.get_solo()
    assert_that(
        (config.protocol_version, config.outbound_key_verifier, config.activated_pairing_id), equal_to((1, "", ""))
    )
    assert_that(config.get_api_key(), equal_to(_K_OLD))
    # And the same id can be staged again afterwards.
    assert_that(admin_client.post(PAIR, _payload(), format="json").json()["status"], equal_to("staged"))


def test_the_longest_accepted_pairing_id_always_activates_and_a_longer_one_is_rejected_at_stage(
    admin_client: APIClient,
) -> None:
    from app.domesti_bot import PAIRING_ID_MAX_LENGTH
    from app.models import DomestiBotConfig as Config

    assert PAIRING_ID_MAX_LENGTH == Config._meta.get_field("activated_pairing_id").max_length

    too_long = admin_client.post(PAIR, _payload(pairing_id="p" * (PAIRING_ID_MAX_LENGTH + 1)), format="json")
    assert_that(too_long.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
    assert_that(too_long.json()["errors"][0], contains_string(f"8-{PAIRING_ID_MAX_LENGTH}"))
    assert_that(bool(DomestiBotConfig.get_solo().pending_pairing), is_(False))

    longest = "p" * PAIRING_ID_MAX_LENGTH
    assert_that(
        admin_client.post(PAIR, _payload(pairing_id=longest), format="json").json()["status"], equal_to("staged")
    )
    activated = admin_client.post(ACTIVATE, {"pairing_id": longest}, format="json")
    assert_that(activated.status_code, equal_to(status.HTTP_200_OK))
    assert_that(DomestiBotConfig.get_solo().activated_pairing_id, equal_to(longest))
