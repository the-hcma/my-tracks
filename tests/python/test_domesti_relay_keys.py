"""Relay key protocol 2 (storage side): verifier-only outbound key, wrong-direction rejection, auth-check."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from hamcrest import assert_that, equal_to, is_, not_
from rest_framework import status
from rest_framework.test import APIClient

from app.domesti_bot import encrypt_api_key
from app.domesti_bot_auth import (
    DOMESTI_API_KEY_HEADER,
    DOMESTI_PAIRING_ID_HEADER,
    DomestiRelayApiKeyPermission,
    DomestiRelayAuthCheckPermission,
)
from app.domesti_relay_keys import (
    MAX_RELAY_KEY_LENGTH,
    PROTOCOL_VERSION_LEGACY,
    PROTOCOL_VERSION_SPLIT,
    pending_pairing_is_live,
    relay_key_verifier,
    verifier_matches,
)
from app.models import DomestiBotConfig

# Built rather than written as literals so secret scanners do not flag them.
_K_IN = "-".join(["inbound", "relay", "key", "0123456789"])
_K_OUT = "-".join(["outbound", "relay", "key", "9876543210"])
_K_NEW = "-".join(["staged", "outbound", "key", "5555555555"])
AUTH_CHECK_URL = "/api/domesti-bot/auth-check/"
REQUEST_URL = "/api/domesti-bot/users/kristen/request-location/"


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _paired_v2(*, remote_request: bool = True) -> DomestiBotConfig:
    """A protocol 2 pairing: ``_K_IN`` is stored encrypted (it is presented outward), ``_K_OUT`` only as a verifier."""
    config = DomestiBotConfig.get_solo()
    config.encrypted_api_key = encrypt_api_key(_K_IN)
    config.outbound_key_verifier = relay_key_verifier(_K_OUT)
    config.protocol_version = PROTOCOL_VERSION_SPLIT
    config.paired_at = timezone.now()
    config.domesti_base_url = "http://192.168.1.10:8003"
    config.user_location_update_url = "http://192.168.1.10:8003/v1/webhooks/location_update"
    config.user_location_test_url = "http://192.168.1.10:8003/v1/webhooks/location_update/test"
    config.remote_request_location_enabled = remote_request
    config.save()
    return config


def _pending(pairing_id: str = "pair-1", *, expires_in: timedelta = timedelta(minutes=10)) -> dict[str, Any]:
    return {
        "pairing_id": pairing_id,
        "expires_at": (timezone.now() + expires_in).isoformat(),
        "outbound_key_verifier": relay_key_verifier(_K_NEW),
    }


def _headers(key: str, pairing_id: str | None = None) -> dict[str, str]:
    headers = {DOMESTI_API_KEY_HEADER: key}
    if pairing_id is not None:
        headers[DOMESTI_PAIRING_ID_HEADER] = pairing_id
    return headers


# --- verifier -----------------------------------------------------------------------------------------------


def test_verifier_is_deterministic_keyed_and_does_not_contain_the_key() -> None:
    assert_that(relay_key_verifier(_K_OUT), equal_to(relay_key_verifier(_K_OUT)))
    assert_that(relay_key_verifier(_K_OUT), not_(equal_to(relay_key_verifier(_K_IN))))
    verifier = relay_key_verifier(_K_OUT)
    assert_that(len(verifier), equal_to(64))
    assert_that(_K_OUT in verifier, is_(False))


@pytest.mark.parametrize("presented", ["", "clé-secrète", "☃" * 10, "x" * (MAX_RELAY_KEY_LENGTH + 1), _K_IN])
def test_verifier_rejects_wrong_empty_non_ascii_and_oversized_keys_without_raising(presented: str) -> None:
    assert_that(verifier_matches(presented, relay_key_verifier(_K_OUT)), is_(False))


def test_verifier_accepts_the_right_key_and_an_empty_verifier_never_matches() -> None:
    assert_that(verifier_matches(_K_OUT, relay_key_verifier(_K_OUT)), is_(True))
    assert_that(verifier_matches(_K_OUT, ""), is_(False))


def test_a_stored_verifier_is_not_a_credential(db: Any) -> None:
    """Presenting the stored verifier as the key must not authenticate (it is only an HMAC of the key)."""
    config = _paired_v2()
    assert_that(config.outbound_key_matches(str(config.outbound_key_verifier)), is_(False))


# --- config.outbound_key_matches ----------------------------------------------------------------------------


def test_protocol_1_still_compares_against_the_single_shared_key(db: Any) -> None:
    config = DomestiBotConfig.get_solo()
    config.encrypted_api_key = encrypt_api_key(_K_IN)
    config.paired_at = timezone.now()
    config.save()
    assert_that(config.protocol_version, equal_to(PROTOCOL_VERSION_LEGACY))
    assert_that(config.outbound_key_matches(_K_IN), is_(True))
    assert_that(config.outbound_key_matches(_K_OUT), is_(False))
    assert_that(config.outbound_key_matches("clé"), is_(False))


def test_protocol_2_rejects_the_inbound_key_in_the_outbound_direction(db: Any) -> None:
    config = _paired_v2()
    assert_that(config.outbound_key_matches(_K_OUT), is_(True))
    assert_that(config.outbound_key_matches(_K_IN), is_(False))


def test_protocol_2_accepts_the_previous_outbound_key_only_until_it_expires(db: Any) -> None:
    config = _paired_v2()
    config.previous_outbound_key_verifier = relay_key_verifier(_K_NEW)
    config.previous_outbound_key_expires_at = timezone.now() + timedelta(seconds=30)
    config.save()
    assert_that(config.outbound_key_matches(_K_NEW), is_(True))

    config.previous_outbound_key_expires_at = timezone.now() - timedelta(seconds=1)
    config.save()
    assert_that(config.outbound_key_matches(_K_NEW), is_(False))
    assert_that(config.outbound_key_matches(_K_OUT), is_(True))


def test_a_database_dump_of_a_protocol_2_pairing_holds_nothing_that_authenticates_the_outbound_key(db: Any) -> None:
    config = _paired_v2()
    config.refresh_from_db()
    columns = {
        field.name: getattr(config, field.name)
        for field in DomestiBotConfig._meta.get_fields()
        if hasattr(field, "attname")
    }
    flattened = " ".join(
        value.decode("latin-1") if isinstance(value, bytes | memoryview) else str(value)
        for value in (bytes(v) if isinstance(v, memoryview) else v for v in columns.values())
    )
    assert_that(_K_OUT in flattened, is_(False))
    # And no stored value works as the outbound credential.
    for value in columns.values():
        if isinstance(value, str) and value:
            assert_that(config.outbound_key_matches(value), is_(False))


# --- request-location permission ----------------------------------------------------------------------------


def test_request_location_accepts_the_outbound_key_and_rejects_the_inbound_key_in_protocol_2(
    api_client: APIClient, db: Any
) -> None:
    _paired_v2()
    wrong = api_client.post(REQUEST_URL, {"reason": "x"}, format="json", headers=_headers(_K_IN))
    assert_that(wrong.status_code, equal_to(status.HTTP_403_FORBIDDEN))
    assert_that(wrong.json()["detail"], equal_to("Invalid or missing domesti-bot API key"))

    staged_not_active = api_client.post(REQUEST_URL, {"reason": "x"}, format="json", headers=_headers(_K_NEW))
    assert_that(staged_not_active.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    right = api_client.post(REQUEST_URL, {"reason": "x"}, format="json", headers=_headers(_K_OUT))
    assert_that(right.status_code, not_(equal_to(status.HTTP_403_FORBIDDEN)))


# --- auth-check endpoint ------------------------------------------------------------------------------------


def test_auth_check_accepts_the_active_outbound_key(api_client: APIClient, db: Any) -> None:
    _paired_v2()
    response = api_client.get(AUTH_CHECK_URL, headers=_headers(_K_OUT))
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    assert_that(response.json(), equal_to({"ok": True, "key": "active", "protocol_version": 2}))


def test_auth_check_does_not_need_the_request_location_opt_in(api_client: APIClient, db: Any) -> None:
    _paired_v2(remote_request=False)
    assert_that(api_client.get(AUTH_CHECK_URL, headers=_headers(_K_OUT)).status_code, equal_to(status.HTTP_200_OK))
    assert_that(
        api_client.post(REQUEST_URL, {"reason": "x"}, format="json", headers=_headers(_K_OUT)).status_code,
        equal_to(status.HTTP_403_FORBIDDEN),
    )


def test_auth_check_accepts_a_staged_key_only_with_the_live_pairing_id(api_client: APIClient, db: Any) -> None:
    config = _paired_v2()
    config.pending_pairing = _pending("pair-1")
    config.save()

    ok = api_client.get(AUTH_CHECK_URL, headers=_headers(_K_NEW, "pair-1"))
    assert_that(ok.status_code, equal_to(status.HTTP_200_OK))
    assert_that(ok.json()["key"], equal_to("pending"))

    for headers in (_headers(_K_NEW), _headers(_K_NEW, "other"), _headers(_K_NEW, "")):
        assert_that(api_client.get(AUTH_CHECK_URL, headers=headers).status_code, equal_to(status.HTTP_403_FORBIDDEN))
    # The staged key is not accepted by request-location, which queues work.
    assert_that(
        api_client.post(REQUEST_URL, {"reason": "x"}, format="json", headers=_headers(_K_NEW, "pair-1")).status_code,
        equal_to(status.HTTP_403_FORBIDDEN),
    )


def test_auth_check_rejects_an_expired_staged_pairing(api_client: APIClient, db: Any) -> None:
    config = _paired_v2()
    config.pending_pairing = _pending("pair-1", expires_in=timedelta(seconds=-5))
    config.save()
    response = api_client.get(AUTH_CHECK_URL, headers=_headers(_K_NEW, "pair-1"))
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_auth_check_works_before_the_first_pairing_completes_only_for_the_staged_key(
    api_client: APIClient, db: Any
) -> None:
    config = DomestiBotConfig.get_solo()
    config.pending_pairing = _pending("first")
    config.save()
    assert_that(
        api_client.get(AUTH_CHECK_URL, headers=_headers(_K_NEW, "first")).status_code, equal_to(status.HTTP_200_OK)
    )
    assert_that(
        api_client.get(AUTH_CHECK_URL, headers=_headers(_K_OUT)).status_code, equal_to(status.HTTP_403_FORBIDDEN)
    )


@pytest.mark.parametrize("bad", ["", "clé-secrète", "☃" * 20, "x" * 5000])
def test_auth_check_answers_unusual_keys_and_pairing_ids_with_403_never_500(
    api_client: APIClient, db: Any, bad: str
) -> None:
    config = _paired_v2()
    config.pending_pairing = _pending("pair-1")
    config.save()
    for headers in ({DOMESTI_API_KEY_HEADER: bad}, {DOMESTI_API_KEY_HEADER: _K_NEW, DOMESTI_PAIRING_ID_HEADER: bad}):
        try:
            response = api_client.get(AUTH_CHECK_URL, headers=headers)
        except UnicodeEncodeError, ValueError:
            continue  # the test client cannot even encode that header
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_pending_pairing_liveness() -> None:
    assert_that(pending_pairing_is_live(None), is_(False))
    assert_that(pending_pairing_is_live({}), is_(False))
    assert_that(pending_pairing_is_live({"expires_at": "not a date"}), is_(False))
    assert_that(pending_pairing_is_live(_pending(expires_in=timedelta(minutes=1))), is_(True))
    assert_that(pending_pairing_is_live(_pending(expires_in=timedelta(minutes=-1))), is_(False))


# --- the key permissions guard exactly the intended routes --------------------------------------------------


def _views_with_permission(permission: Any) -> set[str]:
    found: set[str] = set()

    def walk(patterns: list[Any], prefix: str) -> None:
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(cast(list[Any], entry.url_patterns), prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                view_class = getattr(entry.callback, "cls", None)
                if view_class is not None and permission in getattr(view_class, "permission_classes", []):
                    found.add(entry.name or prefix + str(entry.pattern))

    walk(cast(list[Any], get_resolver().url_patterns), "")
    return found


def test_the_request_location_permission_guards_only_the_two_request_location_views() -> None:
    assert_that(
        _views_with_permission(DomestiRelayApiKeyPermission),
        equal_to({"domesti-bot-request-all-locations", "domesti-bot-request-device-location"}),
    )


def test_the_auth_check_permission_guards_only_the_auth_check_view() -> None:
    assert_that(_views_with_permission(DomestiRelayAuthCheckPermission), equal_to({"domesti-bot-auth-check"}))
