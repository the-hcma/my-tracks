"""The MQTT TLS CRL is issued with a long lifetime and refreshed before it lapses."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
import time_machine
from cryptography import x509
from django.test import override_settings
from hamcrest import assert_that, calling, contains_string, equal_to, is_, not_none, raises
from tiny_pki import generate_crl, get_certificate_expiry, get_certificate_fingerprint

import app.apps as apps_module
from app.apps import (
    _CRL_VALIDITY_DAYS,
    _crl_check_interval_seconds,
    _crl_needs_refresh,
    _load_tls_config,
    _refresh_crl,
)
from app.models import CertificateAuthority, ServerCertificate
from app.mqtt.broker import TLSConfig
from app.pki import encrypt_private_key, generate_ca_certificate, generate_server_certificate

ISSUED_AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _crl(validity_days: int = _CRL_VALIDITY_DAYS) -> bytes:
    ca_pem, ca_key = generate_ca_certificate(common_name="CRL CA", key_size=2048)
    return generate_crl(ca_pem, ca_key, [], validity_days=validity_days)


class TestCrlNeedsRefresh:
    @pytest.fixture
    def crl_pem(self) -> bytes:
        with time_machine.travel(ISSUED_AT, tick=False):
            return _crl()

    @pytest.mark.parametrize(
        ("days_after_issue", "expected"),
        [(0, False), (22, False), (23, True), (29, True), (45, True)],
    )
    def test_refresh_starts_when_less_than_the_margin_remains(
        self, crl_pem: bytes, days_after_issue: int, expected: bool
    ) -> None:
        now = ISSUED_AT + timedelta(days=days_after_issue)

        assert_that(_crl_needs_refresh(crl_pem, now), is_(expected))


class TestRefreshCrl:
    @pytest.fixture
    def ca(self) -> tuple[bytes, bytes]:
        return generate_ca_certificate(common_name="CRL CA", key_size=2048)

    @pytest.fixture
    def broker(self) -> Iterator[MagicMock]:
        broker = MagicMock()
        broker.tls_reload_failed = False
        with patch.object(apps_module._state, "broker", broker):
            yield broker

    @staticmethod
    def _tls_config(ca: tuple[bytes, bytes], revoked_serials: list[int]) -> TLSConfig:
        entries = [(serial, ISSUED_AT) for serial in revoked_serials]
        crl_pem = generate_crl(ca[0], ca[1], entries, validity_days=_CRL_VALIDITY_DAYS)
        return TLSConfig(b"cert", b"key", b"ca", crl_pem=crl_pem)

    @pytest.mark.asyncio
    async def test_reloads_tls_when_revocations_changed_in_the_database(
        self, broker: MagicMock, ca: tuple[bytes, bytes]
    ) -> None:
        with time_machine.travel(ISSUED_AT, tick=False):
            broker.tls_config = self._tls_config(ca, [])
            fresh = self._tls_config(ca, [0xABC])
            with (
                patch.object(apps_module, "_load_tls_config", return_value=fresh),
                patch.object(apps_module, "trigger_tls_reload") as reload,
            ):
                await _refresh_crl()

        reload.assert_called_once_with(reason="CRL revocations changed", keep_tls_on_failure=True)

    @pytest.mark.asyncio
    async def test_reloads_tls_when_crl_is_nearly_expired(self, broker: MagicMock, ca: tuple[bytes, bytes]) -> None:
        with time_machine.travel(ISSUED_AT, tick=False):
            broker.tls_config = self._tls_config(ca, [0xABC])
            fresh = self._tls_config(ca, [0xABC])

        with time_machine.travel(ISSUED_AT + timedelta(days=25), tick=False):
            with (
                patch.object(apps_module, "_load_tls_config", return_value=fresh),
                patch.object(apps_module, "trigger_tls_reload") as reload,
            ):
                await _refresh_crl()

        reload.assert_called_once_with(reason="CRL nearing expiry", keep_tls_on_failure=True)

    @pytest.mark.asyncio
    async def test_retries_when_the_previous_reload_never_brought_tls_back(
        self, broker: MagicMock, ca: tuple[bytes, bytes]
    ) -> None:
        broker.tls_config = self._tls_config(ca, [0xABC])
        broker.tls_reload_failed = True

        with (
            patch.object(apps_module, "_load_tls_config") as load,
            patch.object(apps_module, "trigger_tls_reload") as reload,
        ):
            await _refresh_crl()

        load.assert_not_called()
        reload.assert_called_once_with(reason="previous TLS reload failed", keep_tls_on_failure=True)

    @pytest.mark.asyncio
    async def test_compares_against_the_config_loaded_after_the_database_read(
        self, broker: MagicMock, ca: tuple[bytes, bytes]
    ) -> None:
        """A revocation-triggered reload that lands mid-check must not cause a redundant reload."""
        broker.tls_config = self._tls_config(ca, [])
        fresh = self._tls_config(ca, [0xABC])

        def load_while_a_revocation_reload_lands() -> TLSConfig:
            broker.tls_config = fresh
            return fresh

        with (
            patch.object(apps_module, "_load_tls_config", side_effect=load_while_a_revocation_reload_lands),
            patch.object(apps_module, "trigger_tls_reload") as reload,
        ):
            await _refresh_crl()

        reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_leaves_an_unchanged_fresh_crl_alone(self, broker: MagicMock, ca: tuple[bytes, bytes]) -> None:
        with time_machine.travel(ISSUED_AT, tick=False):
            broker.tls_config = self._tls_config(ca, [0xABC])
            fresh = self._tls_config(ca, [0xABC])
            with (
                patch.object(apps_module, "_load_tls_config", return_value=fresh),
                patch.object(apps_module, "trigger_tls_reload") as reload,
            ):
                await _refresh_crl()

        reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_keeps_the_listener_when_certificates_cannot_be_loaded(
        self, broker: MagicMock, ca: tuple[bytes, bytes], caplog: pytest.LogCaptureFixture
    ) -> None:
        broker.tls_config = self._tls_config(ca, [])

        with (
            patch.object(apps_module, "_load_tls_config", return_value=None),
            patch.object(apps_module, "trigger_tls_reload") as reload,
            caplog.at_level(logging.WARNING, logger="app.apps"),
        ):
            await _refresh_crl()

        reload.assert_not_called()
        assert_that(caplog.text, contains_string("[mqtt-tls] CRL re-read skipped"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tls_config", [None, TLSConfig(b"cert", b"key", b"ca", crl_pem=None)])
    async def test_ignores_brokers_without_a_crl(self, broker: MagicMock, tls_config: TLSConfig | None) -> None:
        broker.tls_config = tls_config

        with (
            patch.object(apps_module, "_load_tls_config") as load,
            patch.object(apps_module, "trigger_tls_reload") as reload,
        ):
            await _refresh_crl()

        load.assert_not_called()
        reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_logged_and_never_raised(
        self, broker: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        broker.tls_config = TLSConfig(b"cert", b"key", b"ca", crl_pem=b"not a crl")

        with (
            patch.object(apps_module, "_load_tls_config", return_value=TLSConfig(b"c", b"k", b"ca", crl_pem=b"x")),
            caplog.at_level(logging.ERROR, logger="app.apps"),
        ):
            await _refresh_crl()

        assert_that(caplog.text, contains_string("[mqtt-tls] CRL refresh check failed"))

    @pytest.mark.asyncio
    async def test_does_nothing_without_a_broker(self) -> None:
        with (
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module, "trigger_tls_reload") as reload,
        ):
            await _refresh_crl()

        reload.assert_not_called()


class TestRunWithFreshDbConnection:
    def test_discards_stale_connections_before_and_closes_them_after(self) -> None:
        calls: list[str] = []

        with (
            patch.object(apps_module, "close_old_connections", side_effect=lambda: calls.append("close_old")),
            patch.object(apps_module.connections, "close_all", side_effect=lambda: calls.append("close_all")),
        ):
            result = apps_module._run_with_fresh_db_connection(lambda value: calls.append("call") or value, 42)

        assert_that(result, equal_to(42))
        assert_that(calls, equal_to(["close_old", "call", "close_all"]))

    def test_closes_connections_even_when_the_call_raises(self) -> None:
        def boom() -> None:
            raise RuntimeError("boom")

        with (
            patch.object(apps_module, "close_old_connections"),
            patch.object(apps_module.connections, "close_all") as close_all,
        ):
            assert_that(calling(apps_module._run_with_fresh_db_connection).with_args(boom), raises(RuntimeError))

        close_all.assert_called_once()


class TestCrlCheckInterval:
    def test_defaults_to_two_hours(self) -> None:
        assert_that(_crl_check_interval_seconds(), equal_to(2 * 3600))

    def test_is_configurable_in_hours(self) -> None:
        with override_settings(MQTT_CRL_REFRESH_INTERVAL_HOURS=0.5):
            assert_that(_crl_check_interval_seconds(), equal_to(1800))


@pytest.mark.django_db(transaction=True)
def test_loaded_crl_uses_the_long_validity() -> None:
    ca_pem, ca_key = generate_ca_certificate(common_name="Load CA", key_size=2048)
    ca = CertificateAuthority.objects.create(
        certificate_pem=ca_pem.decode(),
        encrypted_private_key=encrypt_private_key(ca_key),
        common_name="Load CA",
        fingerprint=get_certificate_fingerprint(ca_pem),
        not_valid_before=get_certificate_expiry(ca_pem),
        not_valid_after=get_certificate_expiry(ca_pem),
        key_size=2048,
        is_active=True,
    )
    srv_pem, srv_key = generate_server_certificate(
        ca_pem, ca_key, common_name="crl-srv", san_entries=["crl-srv"], key_size=2048
    )
    with patch("app.apps.trigger_tls_reload"):
        ServerCertificate.objects.create(
            issuing_ca=ca,
            certificate_pem=srv_pem.decode(),
            encrypted_private_key=encrypt_private_key(srv_key),
            common_name="crl-srv",
            fingerprint=get_certificate_fingerprint(srv_pem),
            not_valid_before=get_certificate_expiry(srv_pem),
            not_valid_after=get_certificate_expiry(srv_pem),
            key_size=2048,
            is_active=True,
        )

    tls_config = _load_tls_config()

    assert_that(tls_config, is_(not_none()))
    crl = x509.load_pem_x509_crl(cast(TLSConfig, tls_config).crl_pem or b"")
    next_update = cast(datetime, crl.next_update_utc)
    assert_that((next_update - crl.last_update_utc).days, equal_to(_CRL_VALIDITY_DAYS))


class TestTriggerTlsReloadKeepOnFailure:
    @pytest.fixture
    def running_broker(self) -> Iterator[MagicMock]:
        broker = MagicMock()
        loop = MagicMock()
        loop.is_closed.return_value = False
        with patch.object(apps_module._state, "broker", broker), patch.object(apps_module._state, "loop", loop):
            yield broker

    def test_unloadable_certificates_leave_the_listener_untouched(
        self, running_broker: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(apps_module, "_load_tls_config", return_value=None),
            patch.object(apps_module.asyncio, "run_coroutine_threadsafe") as schedule,
            caplog.at_level(logging.WARNING, logger="app.apps"),
        ):
            apps_module.trigger_tls_reload(reason="CRL nearing expiry", keep_tls_on_failure=True)

        schedule.assert_not_called()
        assert_that(caplog.text, contains_string("[mqtt-tls] TLS reload skipped"))

    def test_explicit_reload_still_disables_tls_when_certificates_are_gone(self, running_broker: MagicMock) -> None:
        with (
            patch.object(apps_module, "_load_tls_config", return_value=None),
            patch.object(apps_module, "get_mqtt_tls_port", return_value=-1),
            patch.object(apps_module.asyncio, "run_coroutine_threadsafe") as schedule,
        ):
            apps_module.trigger_tls_reload(reason="certificate deactivated")

        schedule.assert_called_once()
        running_broker.reload_tls.assert_called_once_with(None, -1, reason="certificate deactivated")
