"""Tests for the MQTT broker module."""

import asyncio
import dataclasses
import logging
import os
import ssl
import tempfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from amqtt.contrib.listeners import ReloadableExternalTLSListener
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    greater_than,
    has_key,
    has_length,
    is_,
    is_not,
    none,
    not_none,
)
from tiny_pki import generate_crl, get_certificate_serial_number

from app.mqtt.broker import (
    MQTTBroker,
    TLSConfig,
    _CappedTLSListener,
    _demote_listener_shutdown_timeouts,
    _ListenerShutdownTimeoutFilter,
    _mqtt_asyncio_exception_handler,
    _TLSConnectionRegistry,
    build_server_ssl_context,
    create_and_start_broker,
    get_default_config,
)
from app.pki import generate_ca_certificate, generate_client_certificate, generate_server_certificate


class TestGetDefaultConfig:
    """Tests for get_default_config function."""

    def test_returns_dict_with_listeners(self) -> None:
        """Config should have listeners section."""
        config = get_default_config()
        assert_that(config, has_key("listeners"))

    def test_default_mqtt_port(self) -> None:
        """Default MQTT port should be 1883."""
        config = get_default_config()
        assert_that(config["listeners"]["default"]["bind"], equal_to("0.0.0.0:1883"))

    def test_custom_mqtt_port(self) -> None:
        """Custom MQTT port should be respected."""
        config = get_default_config(mqtt_port=11883)
        assert_that(config["listeners"]["default"]["bind"], equal_to("0.0.0.0:11883"))

    def test_allow_anonymous_default(self) -> None:
        """Anonymous connections should include AnonymousAuthPlugin."""
        config = get_default_config()
        assert_that(
            "amqtt.plugins.authentication.AnonymousAuthPlugin" in config["plugins"],
            is_(True),
        )
        plugin_cfg = config["plugins"]["amqtt.plugins.authentication.AnonymousAuthPlugin"]
        assert_that(plugin_cfg["allow_anonymous"], is_(True))

    def test_allow_anonymous_disabled(self) -> None:
        """Disabling anonymous should pass allow_anonymous=False to plugin."""
        config = get_default_config(allow_anonymous=False)
        plugin_cfg = config["plugins"]["amqtt.plugins.authentication.AnonymousAuthPlugin"]
        assert_that(plugin_cfg["allow_anonymous"], is_(False))

    def test_sys_plugin_broadcasts_at_qos_0(self) -> None:
        """Stock BrokerSysPlugin is configured for best-effort QoS 0 (no local subclass)."""
        config = get_default_config()
        sys_plugin = config["plugins"]["amqtt.plugins.sys.broker.BrokerSysPlugin"]
        assert_that(sys_plugin["qos"], equal_to(0))

    def test_no_auth_section(self) -> None:
        """Config should not have a top-level auth section (handled by plugins)."""
        config = get_default_config()
        assert_that("auth" in config, is_(False))


class TestMQTTBrokerInit:
    """Tests for MQTTBroker initialization."""

    def test_default_ports(self) -> None:
        """Broker should use default ports."""
        broker = MQTTBroker()
        assert_that(broker.mqtt_port, equal_to(1883))

    def test_custom_ports(self) -> None:
        """Broker should accept custom ports."""
        broker = MQTTBroker(mqtt_port=11883)
        assert_that(broker.mqtt_port, equal_to(11883))

    def test_not_running_initially(self) -> None:
        """Broker should not be running after initialization."""
        broker = MQTTBroker()
        assert_that(broker.is_running, is_(False))

    def test_custom_config(self) -> None:
        """Broker should accept custom config."""
        custom_config = {"listeners": {"test": {"type": "tcp", "bind": "0.0.0.0:9999"}}}
        broker = MQTTBroker(config=custom_config)
        assert_that(broker.config, equal_to(custom_config))

    def test_actual_mqtt_port_none_before_start(self) -> None:
        """actual_mqtt_port should return None before broker starts."""
        broker = MQTTBroker()
        assert_that(broker.actual_mqtt_port, is_(None))


class TestMQTTBrokerLifecycle:
    """Tests for MQTTBroker start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self) -> None:
        """Starting the broker should set is_running to True."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            assert_that(broker.is_running, is_(True))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_actual_mqtt_port_after_start(self) -> None:
        """actual_mqtt_port should return port after broker starts."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            actual = broker.actual_mqtt_port
            assert_that(actual, is_(not_none()))
            assert_that(actual, greater_than(0))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self) -> None:
        """Stopping the broker should set is_running to False."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        await broker.start()
        await broker.stop()
        assert_that(broker.is_running, is_(False))

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(self) -> None:
        """Starting an already running broker should raise RuntimeError."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            with pytest.raises(RuntimeError, match="already running"):
                await broker.start()
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_stop_not_running_raises_error(self) -> None:
        """Stopping a non-running broker should raise RuntimeError."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        with pytest.raises(RuntimeError, match="not running"):
            await broker.stop()

    @pytest.mark.asyncio
    async def test_run_forever_can_be_cancelled(self) -> None:
        """run_forever should handle cancellation gracefully."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)

        async def run_then_cancel() -> None:
            task = asyncio.create_task(broker.run_forever())
            await asyncio.sleep(0.5)  # Let it start
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_then_cancel()
        assert_that(broker.is_running, is_(False))


class TestStartHoldsReloadLock:
    """A TLS reload that fires during startup must wait until the listener exists."""

    @pytest.mark.asyncio
    async def test_reload_lock_is_held_while_the_tls_listener_starts(self) -> None:
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, use_owntracks_handler=False, tls_config=_make_tls_config())
        held_during_listener_start: list[bool] = []

        async def fake_start_tls_listener(*_args: object) -> MagicMock:
            held_during_listener_start.append(broker.reload_in_progress)
            return MagicMock()

        inner = MagicMock(start=AsyncMock(), shutdown=AsyncMock())
        with (
            patch("app.mqtt.broker.Broker", return_value=inner),
            patch.object(broker, "_start_tls_listener", side_effect=fake_start_tls_listener),
        ):
            await broker.start()
        assert_that(held_during_listener_start, equal_to([True]))
        assert_that(broker.reload_in_progress, is_(False))
        assert_that(broker.is_running, is_(True))

    @pytest.mark.asyncio
    async def test_reload_lock_is_released_when_startup_fails(self) -> None:
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, use_owntracks_handler=False, tls_config=_make_tls_config())
        inner = MagicMock(start=AsyncMock(), shutdown=AsyncMock())
        with (
            patch("app.mqtt.broker.Broker", return_value=inner),
            patch.object(broker, "_start_tls_listener", AsyncMock(side_effect=OSError("address in use"))),
        ):
            with pytest.raises(OSError):
                await broker.start()
        assert_that(broker.reload_in_progress, is_(False))
        assert_that(broker.is_running, is_(False))


class TestOSAllocatedPorts:
    """Tests for OS-allocated port functionality (port 0)."""

    @pytest.mark.asyncio
    async def test_mqtt_port_zero_allocates_actual_port(self) -> None:
        """Starting broker with port 0 should allocate a real port."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            assert_that(broker.is_running, is_(True))
            actual_mqtt_port = broker.actual_mqtt_port
            assert_that(actual_mqtt_port, is_(not_none()))
            assert_that(actual_mqtt_port, greater_than(0))
            assert_that(actual_mqtt_port, is_not(equal_to(0)))
        finally:
            if broker.is_running:
                await broker.stop()


class TestProtocolListening:
    """Verify the broker is actually listening on each protocol's port."""

    @pytest.mark.asyncio
    async def test_tcp_mqtt_port_accepting_connections(self) -> None:
        """The MQTT TCP listener should accept raw TCP connections."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            port = broker.actual_mqtt_port
            assert_that(port, is_(not_none()))

            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_tcp_mqtt_port_not_listening_after_stop(self) -> None:
        """After stopping, the MQTT TCP port should refuse connections."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        await broker.start()
        port = broker.actual_mqtt_port
        assert_that(port, is_(not_none()))
        await broker.stop()

        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)


class TestAmqttBrokerProperty:
    """Tests for amqtt_broker property."""

    def test_none_before_start(self) -> None:
        """amqtt_broker should be None before start."""
        broker = MQTTBroker()
        assert_that(broker.amqtt_broker, is_(None))

    @pytest.mark.asyncio
    async def test_set_after_start(self) -> None:
        """amqtt_broker should reference the underlying Broker after start."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            assert_that(broker.amqtt_broker, is_(not_none()))
        finally:
            if broker.is_running:
                await broker.stop()


class TestDiscoverPort:
    """Tests for _discover_port method."""

    def test_returns_none_when_broker_is_none(self) -> None:
        """Should return None when internal broker has not been created."""
        broker = MQTTBroker()
        result = broker._discover_port("default")
        assert_that(result, is_(None))

    def test_handles_exception_gracefully(self) -> None:
        """Should return None when discovery raises an exception."""
        broker = MQTTBroker()
        mock_amqtt = MagicMock()
        mock_amqtt._servers.get.side_effect = RuntimeError("broken")
        broker._broker = mock_amqtt
        result = broker._discover_port("default")
        assert_that(result, is_(None))

    def test_returns_none_when_no_servers_attribute(self) -> None:
        """Should return None when broker lacks _servers attribute."""
        broker = MQTTBroker()
        broker._broker = MagicMock(spec=[])
        result = broker._discover_port("default")
        assert_that(result, is_(None))

    def test_returns_none_when_listener_not_found(self) -> None:
        """Should return None when the requested listener is not in _servers."""
        broker = MQTTBroker()
        mock_amqtt = MagicMock()
        mock_servers = MagicMock()
        mock_servers.get.return_value = None
        mock_amqtt._servers = mock_servers
        broker._broker = mock_amqtt
        result = broker._discover_port("nonexistent")
        assert_that(result, is_(None))


class TestPortCaching:
    """Tests for port caching and fallback in actual_mqtt_port."""

    def test_actual_mqtt_port_returns_cached_value(self) -> None:
        """Should return cached MQTT port without calling _discover_port."""
        broker = MQTTBroker()
        broker._actual_mqtt_port = 12345
        assert_that(broker.actual_mqtt_port, equal_to(12345))

    def test_actual_mqtt_port_fallback_to_configured(self) -> None:
        """Should fall back to configured mqtt_port when discovery fails."""
        broker = MQTTBroker(mqtt_port=1883)
        broker._broker = MagicMock()
        with patch.object(broker, "_discover_port", return_value=None):
            result = broker.actual_mqtt_port
        assert_that(result, equal_to(1883))


class TestCreateAndStartBroker:
    """Tests for create_and_start_broker convenience function."""

    @pytest.mark.asyncio
    async def test_creates_running_broker(self) -> None:
        """Should create and start a broker with the given parameters."""
        broker = await create_and_start_broker(
            mqtt_port=0,
            allow_anonymous=True,
        )
        try:
            assert_that(broker.is_running, is_(True))
            assert_that(broker.allow_anonymous, is_(True))
            assert_that(broker.actual_mqtt_port, is_(not_none()))
            assert_that(broker.actual_mqtt_port, greater_than(0))
        finally:
            if broker.is_running:
                await broker.stop()


class TestDjangoAuthConfig:
    """Tests for Django auth plugin configuration."""

    def test_django_auth_plugin_when_enabled(self) -> None:
        """Should include DjangoAuthPlugin when use_django_auth=True and anonymous=False."""
        config = get_default_config(use_django_auth=True, allow_anonymous=False)
        assert_that(
            "app.mqtt.auth.DjangoAuthPlugin" in config["plugins"],
            is_(True),
        )
        assert_that(
            "amqtt.plugins.authentication.AnonymousAuthPlugin" in config["plugins"],
            is_(False),
        )

    def test_django_auth_with_anonymous_uses_anonymous_plugin(self) -> None:
        """When django_auth=True but allow_anonymous=True, should use anonymous plugin."""
        config = get_default_config(use_django_auth=True, allow_anonymous=True)
        assert_that(
            "amqtt.plugins.authentication.AnonymousAuthPlugin" in config["plugins"],
            is_(True),
        )
        assert_that(
            "app.mqtt.auth.DjangoAuthPlugin" in config["plugins"],
            is_(False),
        )

    def test_owntracks_handler_disabled(self) -> None:
        """Should omit OwnTracksPlugin when use_owntracks_handler=False."""
        config = get_default_config(use_owntracks_handler=False)
        assert_that(
            "app.mqtt.plugin.OwnTracksPlugin" in config["plugins"],
            is_(False),
        )

    def test_owntracks_handler_enabled_by_default(self) -> None:
        """Should include OwnTracksPlugin by default."""
        config = get_default_config()
        assert_that(
            "app.mqtt.plugin.OwnTracksPlugin" in config["plugins"],
            is_(True),
        )


class TestDiscoverPortSuccessPath:
    """Tests for _discover_port success and edge-case paths."""

    def test_returns_port_from_valid_socket(self) -> None:
        """Should return port when server, instance, and sockets are valid."""
        broker = MQTTBroker()
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("0.0.0.0", 54321)

        mock_instance = MagicMock()
        mock_instance.sockets = [mock_socket]

        mock_server = MagicMock()
        mock_server.instance = mock_instance

        mock_amqtt = MagicMock()
        mock_amqtt._servers = {"default": mock_server}
        broker._broker = mock_amqtt

        result = broker._discover_port("default")
        assert_that(result, equal_to(54321))

    def test_returns_none_when_server_instance_is_none(self) -> None:
        """Should return None when server exists but instance is None."""
        broker = MQTTBroker()
        mock_server = MagicMock()
        mock_server.instance = None

        mock_amqtt = MagicMock()
        mock_amqtt._servers = {"default": mock_server}
        broker._broker = mock_amqtt

        result = broker._discover_port("default")
        assert_that(result, is_(None))

    def test_returns_none_when_instance_has_no_sockets(self) -> None:
        """Should return None when instance has no sockets attribute."""
        broker = MQTTBroker()
        mock_instance = MagicMock(spec=[])  # No sockets attribute

        mock_server = MagicMock()
        mock_server.instance = mock_instance

        mock_amqtt = MagicMock()
        mock_amqtt._servers = {"default": mock_server}
        broker._broker = mock_amqtt

        result = broker._discover_port("default")
        assert_that(result, is_(None))

    def test_returns_none_when_socket_address_too_short(self) -> None:
        """Should return None when socket.getsockname() returns a short tuple."""
        broker = MQTTBroker()
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("only_host",)

        mock_instance = MagicMock()
        mock_instance.sockets = [mock_socket]

        mock_server = MagicMock()
        mock_server.instance = mock_instance

        mock_amqtt = MagicMock()
        mock_amqtt._servers = {"default": mock_server}
        broker._broker = mock_amqtt

        result = broker._discover_port("default")
        assert_that(result, is_(None))


class TestPortDiscoveryCaching:
    """Tests for port discovery caching behavior."""

    def test_actual_mqtt_port_caches_discovered_value(self) -> None:
        """Once discovered, actual_mqtt_port should cache and return the same value."""
        broker = MQTTBroker()
        broker._broker = MagicMock()
        with patch.object(broker, "_discover_port", return_value=11111):
            first = broker.actual_mqtt_port
            assert_that(first, equal_to(11111))

        assert_that(broker.actual_mqtt_port, equal_to(11111))
        assert_that(broker._actual_mqtt_port, equal_to(11111))


class TestRunForeverAutoStart:
    """Tests for run_forever auto-start behavior."""

    @pytest.mark.asyncio
    async def test_auto_starts_when_not_running(self) -> None:
        """run_forever should call start() if broker is not yet running."""
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)

        async def cancel_soon() -> None:
            task = asyncio.create_task(broker.run_forever())
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await cancel_soon()
        assert_that(broker.is_running, is_(False))


def _make_tls_config(*, crl: bytes | None = None) -> TLSConfig:
    """Generate real (small-key) PKI material so context building is exercised for real."""
    ca_cert, ca_key = generate_ca_certificate(common_name="Unit Test CA", key_size=2048)
    server_cert, server_key = generate_server_certificate(
        ca_cert,
        ca_key,
        common_name="localhost",
        san_entries=["localhost"],
        key_size=2048,
    )
    return TLSConfig(server_cert_pem=server_cert, server_key_pem=server_key, ca_cert_pem=ca_cert, crl_pem=crl)


class TestTLSListenerConfig:
    """The TLS listener is declared as an external listener fed by ReloadableExternalTLSListener."""

    def test_tls_listener_always_declared_external(self) -> None:
        listeners = get_default_config()["listeners"]
        assert_that(listeners["mqtt-tls"]["type"], equal_to("external"))

    def test_actual_tls_port_none_when_disabled(self) -> None:
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=-1)
        assert_that(broker.actual_tls_port, is_(none()))

    def test_actual_tls_port_none_before_start(self) -> None:
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, tls_config=_make_tls_config())
        assert_that(broker.actual_tls_port, is_(none()))

    @pytest.mark.asyncio
    async def test_start_without_tls_does_not_create_listener(self) -> None:
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        with patch("app.mqtt.broker._CappedTLSListener") as listener_cls:
            await broker.start()
            await broker.stop()
        listener_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_with_tls_starts_listener_and_stop_closes_it(self) -> None:
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, tls_config=_make_tls_config(), use_owntracks_handler=False)
        listener = MagicMock(
            start=AsyncMock(), close=AsyncMock(), wait_connections_closed=AsyncMock(), actual_port=45678
        )
        with patch("app.mqtt.broker._CappedTLSListener", return_value=listener) as listener_cls:
            await broker.start()
            assert_that(broker.actual_tls_port, equal_to(45678))
            await broker.stop()
        assert_that(listener_cls.call_args.kwargs["listener_name"], equal_to("mqtt-tls"))
        listener.start.assert_awaited_once()
        listener.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_restores_event_loop_exception_handler(self) -> None:
        loop = asyncio.get_running_loop()
        before = loop.get_exception_handler()
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        await broker.start()
        assert_that(loop.get_exception_handler(), is_not(before))
        await broker.stop()
        assert_that(loop.get_exception_handler(), is_(before))

    @pytest.mark.asyncio
    async def test_failed_tls_listener_start_releases_the_broker(self) -> None:
        """A TLS bind/PEM failure must not leave the TCP broker bound or the loop handler installed."""
        loop = asyncio.get_running_loop()
        before = loop.get_exception_handler()
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, tls_config=_make_tls_config(), use_owntracks_handler=False)
        listener = MagicMock(start=AsyncMock(side_effect=OSError("address in use")))
        with patch("app.mqtt.broker._CappedTLSListener", return_value=listener):
            with pytest.raises(OSError):
                await broker.start()

        assert_that(broker.is_running, is_(False))
        assert_that(broker.amqtt_broker, is_(none()))
        assert_that(loop.get_exception_handler(), is_(before))

        # The TCP port was released, so the same instance can start again.
        broker.tls_config = None
        broker.mqtt_tls_port = -1
        await broker.start()
        await broker.stop()


class TestBuildServerSSLContext:
    """build_server_ssl_context enforces mutual TLS with no on-disk leftovers."""

    def test_requires_client_certificate(self) -> None:
        ctx = build_server_ssl_context(_make_tls_config())
        assert_that(ctx.verify_mode, equal_to(ssl.CERT_REQUIRED))

    def test_caps_at_tls_1_2(self) -> None:
        ctx = build_server_ssl_context(_make_tls_config())
        assert_that(ctx.maximum_version, equal_to(ssl.TLSVersion.TLSv1_2))

    def test_crl_enables_leaf_revocation_check(self) -> None:
        ca_cert, ca_key = generate_ca_certificate(common_name="CRL CA", key_size=2048)
        config = _make_tls_config(crl=generate_crl(ca_cert, ca_key, revoked_entries=[]))
        ctx = build_server_ssl_context(config)
        assert_that(bool(ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF), is_(True))

    def test_no_crl_leaves_revocation_check_off(self) -> None:
        ctx = build_server_ssl_context(_make_tls_config())
        assert_that(bool(ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF), is_(False))

    def test_registers_sni_callback_when_given(self) -> None:
        callback = MagicMock()
        ctx = build_server_ssl_context(_make_tls_config(), callback)
        assert_that(ctx.sni_callback, is_(not_none()))

    def test_leaves_no_key_material_on_disk(self) -> None:
        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*args: object, **kwargs: object) -> str:
            path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
            created.append(path)
            return path

        with patch("tempfile.mkdtemp", side_effect=spy):
            build_server_ssl_context(_make_tls_config())
        assert_that(created, has_length(1))
        assert_that(os.path.exists(created[0]), is_(False))

    def test_rejects_unparseable_material(self) -> None:
        bad = TLSConfig(server_cert_pem=b"x", server_key_pem=b"y", ca_cert_pem=b"z")
        with pytest.raises((ssl.SSLError, ValueError)):
            build_server_ssl_context(bad)


class TestMqttAsyncioExceptionHandler:
    """Tests for MQTT broker asyncio exception logging."""

    def test_logs_ssl_handshake_failure(self) -> None:
        """SSL handshake errors are logged at WARNING with peer info."""
        loop = asyncio.new_event_loop()
        broker_logger = logging.getLogger("app.mqtt.broker")
        try:
            with patch.object(broker_logger, "warning") as mock_warn:
                _mqtt_asyncio_exception_handler(
                    loop,
                    {
                        "exception": ssl.SSLError("cert verify failed"),
                        "transport": MagicMock(
                            get_extra_info=MagicMock(return_value=("10.0.0.1", 8883)),
                        ),
                    },
                    None,
                )
            mock_warn.assert_called_once()
            assert_that(mock_warn.call_args[0][0], contains_string("[mqtt-tls]"))
            assert_that(mock_warn.call_args[0][1], equal_to("10.0.0.1:8883"))
        finally:
            loop.close()

    def test_logs_client_connected_cb_ssl_shutdown_timeout(self) -> None:
        """Unhandled client_connected_cb SSL shutdown timeouts are logged at WARNING."""
        loop = asyncio.new_event_loop()
        broker_logger = logging.getLogger("app.mqtt.broker")
        exc = TimeoutError("SSL shutdown timed out")
        try:
            with patch.object(broker_logger, "warning") as mock_warn:
                _mqtt_asyncio_exception_handler(
                    loop,
                    {
                        "message": "Unhandled exception in client_connected_cb",
                        "exception": exc,
                    },
                    None,
                )
            mock_warn.assert_called_once()
            assert_that(mock_warn.call_args[0][0], contains_string("[mqtt-tls]"))
            assert_that(mock_warn.call_args[0][0], contains_string("SSL shutdown"))
        finally:
            loop.close()

    def test_forwards_unrelated_exceptions(self) -> None:
        """Non-MQTT exceptions are forwarded to the previous handler."""
        loop = asyncio.new_event_loop()
        fallback = MagicMock()
        try:
            _mqtt_asyncio_exception_handler(
                loop,
                {"exception": ValueError("unrelated")},
                fallback,
            )
            fallback.assert_called_once()
        finally:
            loop.close()


class TestReloadTLS:
    """Tests for MQTTBroker.reload_tls hot-reload (no amqtt broker restart)."""

    def _broker(self, **kwargs: object) -> tuple[MQTTBroker, AsyncMock]:
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False, **kwargs)  # type: ignore[arg-type]
        inner = AsyncMock()
        inner.sessions = {}
        broker._broker = inner
        broker._running = True
        return broker, inner

    @staticmethod
    def _listener(port: int = 0) -> MagicMock:
        return MagicMock(
            start=AsyncMock(),
            close=AsyncMock(),
            reload=AsyncMock(),
            wait_connections_closed=AsyncMock(),
            port=port,
            actual_port=port,
        )

    @pytest.mark.asyncio
    async def test_reload_does_not_restart_amqtt_broker(self) -> None:
        broker, inner = self._broker()
        await broker.reload_tls(None, mqtt_tls_port=-1)
        inner.shutdown.assert_not_called()
        assert_that(broker._broker, is_(inner))
        assert_that(broker._running, is_(True))

    @pytest.mark.asyncio
    async def test_reload_reloads_existing_listener_in_place(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=0, tls_config=_make_tls_config())
        listener = self._listener(port=0)
        broker._tls_listener = listener
        new_config = _make_tls_config()
        await broker.reload_tls(new_config, mqtt_tls_port=0)
        listener.reload.assert_awaited_once()
        listener.close.assert_not_called()
        assert_that(broker.tls_config, is_(new_config))
        assert_that(broker.tls_reload_failed, is_(False))

    @pytest.mark.asyncio
    async def test_reload_enables_tls_from_disabled(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=-1)
        listener = self._listener(port=45001)
        with patch("app.mqtt.broker._CappedTLSListener", return_value=listener):
            await broker.reload_tls(_make_tls_config(), mqtt_tls_port=45001)
        listener.start.assert_awaited_once()
        assert_that(broker.mqtt_tls_port, equal_to(45001))

    @pytest.mark.asyncio
    async def test_reload_disables_tls(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=0, tls_config=_make_tls_config())
        listener = self._listener()
        broker._tls_listener = listener
        await broker.reload_tls(None, mqtt_tls_port=-1)
        listener.close.assert_awaited_once()
        assert_that(broker._tls_listener, is_(none()))
        assert_that(broker.tls_config, is_(none()))
        assert_that(broker.mqtt_tls_port, equal_to(-1))

    @pytest.mark.asyncio
    async def test_reload_to_new_port_replaces_listener(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=45001, tls_config=_make_tls_config())
        old = self._listener(port=45001)
        broker._tls_listener = old
        new = self._listener(port=45002)
        with patch("app.mqtt.broker._CappedTLSListener", return_value=new):
            await broker.reload_tls(_make_tls_config(), mqtt_tls_port=45002)
        old.close.assert_awaited_once()
        new.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_port_change_keeps_the_old_listener(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=45001, tls_config=_make_tls_config())
        old_config = broker.tls_config
        old = self._listener(port=45001)
        broker._tls_listener = old
        new = self._listener(port=45002)
        new.start.side_effect = OSError("address in use")
        with patch("app.mqtt.broker._CappedTLSListener", return_value=new):
            with pytest.raises(OSError):
                await broker.reload_tls(_make_tls_config(), mqtt_tls_port=45002)

        old.close.assert_not_called()
        assert_that(broker._tls_listener, is_(old))
        assert_that(broker.mqtt_tls_port, equal_to(45001))
        assert_that(broker.tls_config, is_(old_config))
        assert_that(broker.tls_reload_failed, is_(True))

    @pytest.mark.asyncio
    async def test_port_change_starts_the_new_listener_before_closing_the_old(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=45001, tls_config=_make_tls_config())
        order: list[str] = []
        old = self._listener(port=45001)
        old.close.side_effect = lambda: order.append("close-old")
        broker._tls_listener = old
        new = self._listener(port=45002)
        new.start.side_effect = lambda: order.append("start-new")
        with patch("app.mqtt.broker._CappedTLSListener", return_value=new):
            await broker.reload_tls(_make_tls_config(), mqtt_tls_port=45002)
        assert_that(order, equal_to(["start-new", "close-old"]))

    @pytest.mark.asyncio
    async def test_failed_reload_stays_flagged(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=0, tls_config=_make_tls_config())
        listener = self._listener()
        listener.reload.side_effect = OSError("address in use")
        broker._tls_listener = listener
        with pytest.raises(OSError):
            await broker.reload_tls(_make_tls_config(), mqtt_tls_port=0)
        assert_that(broker.tls_reload_failed, is_(True))

    @pytest.mark.asyncio
    async def test_reload_in_progress_is_true_only_while_a_reload_runs(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=0, tls_config=_make_tls_config())
        observed: list[bool] = []
        listener = self._listener()
        listener.reload.side_effect = lambda *_: observed.append(broker.reload_in_progress)
        broker._tls_listener = listener
        assert_that(broker.reload_in_progress, is_(False))
        await broker.reload_tls(_make_tls_config(), mqtt_tls_port=0)
        assert_that(observed, equal_to([True]))
        assert_that(broker.reload_in_progress, is_(False))

    @pytest.mark.asyncio
    async def test_reload_serialized_by_lock(self) -> None:
        broker, _ = self._broker(mqtt_tls_port=0, tls_config=_make_tls_config())
        in_reload = 0
        max_in_reload = 0
        gate = asyncio.Event()

        async def slow_reload(*_: object) -> None:
            nonlocal in_reload, max_in_reload
            in_reload += 1
            max_in_reload = max(max_in_reload, in_reload)
            await gate.wait()
            in_reload -= 1

        listener = self._listener()
        listener.reload.side_effect = slow_reload
        broker._tls_listener = listener
        first = asyncio.create_task(broker.reload_tls(_make_tls_config(), mqtt_tls_port=0))
        second = asyncio.create_task(broker.reload_tls(_make_tls_config(), mqtt_tls_port=0))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(first, second)
        assert_that(max_in_reload, equal_to(1))


def _transport(*, closing: bool = False, ssl_object: object | None = None) -> MagicMock:
    """A stream writer stand-in whose ``ssl_object`` extra info is ``ssl_object``."""
    writer = MagicMock()
    writer.is_closing.return_value = closing
    writer.get_extra_info.return_value = ssl_object
    return writer


class TestTLSConnectionRegistry:
    """The registry counts each live TLS transport once and closes the ones whose trust changed."""

    def test_counts_each_transport_once_until_it_is_discarded(self) -> None:
        registry = _TLSConnectionRegistry()
        first, second = _transport(), _transport()
        registry.add(first)
        registry.add(first)
        registry.add(second)
        assert_that(len(registry), equal_to(2))
        registry.discard(first)
        registry.discard(first)
        assert_that(len(registry), equal_to(1))

    def test_close_matching_closes_only_matching_open_tls_transports(self) -> None:
        registry = _TLSConnectionRegistry()
        match = _transport(ssl_object=MagicMock(name="match"))
        keep = _transport(ssl_object=MagicMock(name="keep"))
        plain = _transport(ssl_object=None)
        closing = _transport(closing=True, ssl_object=MagicMock(name="match"))
        for writer in (match, keep, plain, closing):
            registry.add(writer)
        keep_object = keep.get_extra_info.return_value

        def drop_reason(ssl_object: ssl.SSLObject) -> str | None:
            return None if ssl_object is keep_object else "revoked"

        assert_that(registry.close_matching(drop_reason), equal_to(1))
        match.close.assert_called_once()
        for untouched in (keep, plain, closing):
            untouched.close.assert_not_called()


class TestCappedTLSListener:
    """The external TLS listener enforces the connection cap that amqtt skips for external listeners."""

    @staticmethod
    def _listener(max_connections: int, registry: _TLSConnectionRegistry | None = None) -> _CappedTLSListener:
        return _CappedTLSListener(
            max_connections=max_connections,
            registry=_TLSConnectionRegistry() if registry is None else registry,
            broker=MagicMock(),
            listener_name="mqtt-tls",
            host="127.0.0.1",
            port=0,
            ssl_context_factory=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_connection_over_the_cap_is_refused(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = _TLSConnectionRegistry()
        registry.add(_transport())
        registry.add(_transport())
        listener = self._listener(max_connections=2, registry=registry)
        writer = MagicMock()
        with patch.object(ReloadableExternalTLSListener, "_client_connected", new=AsyncMock()) as handoff:
            with caplog.at_level(logging.WARNING, logger="app.mqtt.broker"):
                await listener._client_connected(MagicMock(), writer)
        writer.close.assert_called_once()
        handoff.assert_not_awaited()
        assert_that(len(registry), equal_to(2))
        assert_that(caplog.text, contains_string("[mqtt-tls] Connection refused: limit reached (active=2, max=2)"))

    @pytest.mark.asyncio
    async def test_cap_spans_listener_generations_and_connections_waiting_for_connect(self) -> None:
        """One live connection on a replaced listener plus one pending on its successor fills a cap of 2."""
        registry = _TLSConnectionRegistry()
        old_generation = self._listener(max_connections=2, registry=registry)
        new_generation = self._listener(max_connections=2, registry=registry)
        release_old = asyncio.Event()
        release_pending = asyncio.Event()

        async def hold(event: asyncio.Event, *_args: object) -> None:
            await event.wait()

        async def hand_off_old(*args: object) -> None:
            await hold(release_old, *args)

        async def hand_off_pending(*args: object) -> None:
            await hold(release_pending, *args)

        with patch.object(ReloadableExternalTLSListener, "_client_connected", side_effect=hand_off_old):
            old_task = asyncio.create_task(old_generation._client_connected(MagicMock(), _transport()))
            await asyncio.sleep(0)
        with patch.object(ReloadableExternalTLSListener, "_client_connected", side_effect=hand_off_pending):
            pending_task = asyncio.create_task(new_generation._client_connected(MagicMock(), _transport()))
            await asyncio.sleep(0)
        assert_that(len(registry), equal_to(2))

        third = MagicMock()
        await new_generation._client_connected(MagicMock(), third)
        third.close.assert_called_once()

        release_old.set()
        release_pending.set()
        await asyncio.gather(old_task, pending_task)
        assert_that(len(registry), equal_to(0))

    @pytest.mark.asyncio
    async def test_connection_under_the_cap_is_registered_while_it_is_handled(self) -> None:
        registry = _TLSConnectionRegistry()
        listener = self._listener(max_connections=2, registry=registry)
        writer = MagicMock()
        seen: list[int] = []

        async def hand_off(*_args: object) -> None:
            seen.append(len(registry))

        with patch.object(ReloadableExternalTLSListener, "_client_connected", side_effect=hand_off):
            await listener._client_connected(MagicMock(), writer)
        writer.close.assert_not_called()
        assert_that(seen, equal_to([1]))
        assert_that(len(registry), equal_to(0))

    @pytest.mark.asyncio
    async def test_connection_is_unregistered_when_the_hand_off_fails(self) -> None:
        registry = _TLSConnectionRegistry()
        listener = self._listener(max_connections=2, registry=registry)
        with patch.object(ReloadableExternalTLSListener, "_client_connected", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await listener._client_connected(MagicMock(), MagicMock())
        assert_that(len(registry), equal_to(0))


class TestListenerShutdownTimeoutFilter:
    """amqtt's listener logs every connection failure as an ERROR; a TLS shutdown timeout is routine."""

    @staticmethod
    def _emit(exc: Exception) -> logging.LogRecord:
        records: list[logging.LogRecord] = []
        capture = logging.Handler()
        capture.emit = records.append  # type: ignore[method-assign]
        listener_logger = logging.getLogger(ReloadableExternalTLSListener.__module__)
        listener_logger.addHandler(capture)
        try:
            _demote_listener_shutdown_timeouts()
            try:
                raise exc
            except Exception:
                listener_logger.exception("External TLS listener '%s' connection failed", "mqtt-tls")
        finally:
            listener_logger.removeHandler(capture)
        return records[0]

    def test_shutdown_timeout_becomes_a_tagged_warning_without_traceback(self) -> None:
        record = self._emit(TimeoutError("SSL shutdown timed out"))
        assert_that(record.levelno, equal_to(logging.WARNING))
        assert_that(record.exc_info, is_(none()))
        message = record.getMessage()
        assert_that(message, contains_string("[mqtt-tls] Client connection closed during shutdown"))
        assert_that(message, contains_string("'mqtt-tls'"))
        assert_that(message, contains_string("SSL shutdown timed out"))

    def test_other_failures_keep_their_error_level_and_traceback(self) -> None:
        record = self._emit(RuntimeError("boom"))
        assert_that(record.levelno, equal_to(logging.ERROR))
        assert_that(record.exc_info, is_(not_none()))
        assert_that(record.getMessage(), contains_string("connection failed"))

    def test_an_unrelated_timeout_keeps_its_error_level_and_traceback(self) -> None:
        record = self._emit(TimeoutError("handshake timed out"))
        assert_that(record.levelno, equal_to(logging.ERROR))
        assert_that(record.exc_info, is_(not_none()))

    def test_installing_twice_adds_one_filter(self) -> None:
        listener_logger = logging.getLogger(ReloadableExternalTLSListener.__module__)
        _demote_listener_shutdown_timeouts()
        _demote_listener_shutdown_timeouts()
        installed = [f for f in listener_logger.filters if isinstance(f, _ListenerShutdownTimeoutFilter)]
        assert_that(installed, has_length(1))


class _RevocationFixture:
    """One CA, a revoked client certificate, an unrevoked one, and a CRL listing the first."""

    def __init__(self) -> None:
        self.ca_cert_pem, ca_key_pem = generate_ca_certificate(common_name="Revocation Test CA", key_size=2048)
        self.revoked_pem, _ = generate_client_certificate(
            self.ca_cert_pem, ca_key_pem, username="revoked", key_size=2048
        )
        self.valid_pem, _ = generate_client_certificate(self.ca_cert_pem, ca_key_pem, username="valid", key_size=2048)
        self.crl_pem = generate_crl(
            self.ca_cert_pem,
            ca_key_pem,
            revoked_entries=[(get_certificate_serial_number(self.revoked_pem), datetime.now(UTC))],
        )
        self.empty_crl_pem = generate_crl(self.ca_cert_pem, ca_key_pem, revoked_entries=[])

    @staticmethod
    def session(
        cert_pem: bytes | None, *, state: str = "connected", has_ssl: bool = True
    ) -> tuple[MagicMock, AsyncMock]:
        ssl_object = None
        if has_ssl:
            ssl_object = MagicMock()
            der = x509.load_pem_x509_certificate(cert_pem).public_bytes(Encoding.DER) if cert_pem else None
            ssl_object.getpeercert.return_value = der
        session = MagicMock(ssl_object=ssl_object)
        session.transitions.state = state
        handler = MagicMock(handle_disconnect=AsyncMock())
        return session, handler.handle_disconnect


@pytest.fixture(scope="module")
def pki() -> _RevocationFixture:
    return _RevocationFixture()


class TestDisconnectRevokedSessions:
    """Only connected TLS sessions whose peer certificate is in the new CRL are dropped on reload."""

    @staticmethod
    def _broker(sessions: dict[str, tuple[MagicMock, MagicMock]]) -> MQTTBroker:
        broker = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        inner = MagicMock()
        inner.sessions = sessions
        broker._broker = inner
        return broker

    @pytest.mark.asyncio
    async def test_revoked_connected_session_is_dropped(self, pki: _RevocationFixture) -> None:
        session, disconnect = pki.session(pki.revoked_pem)
        broker = self._broker({"revoked": (session, MagicMock(handle_disconnect=disconnect))})
        assert_that(await broker._disconnect_revoked_sessions(pki.crl_pem), equal_to(1))
        disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("label", "kwargs"),
        [
            ("unrevoked certificate", {"valid": True}),
            ("plain TCP session without an ssl object", {"has_ssl": False}),
            ("session that is not connected", {"state": "disconnected", "revoked": True}),
            ("peer that presented no certificate", {"cert": False}),
        ],
    )
    async def test_sessions_that_must_stay_are_skipped(
        self, pki: _RevocationFixture, label: str, kwargs: dict[str, object]
    ) -> None:
        cert_pem = None if kwargs.get("cert") is False else (pki.valid_pem if kwargs.get("valid") else pki.revoked_pem)
        session, disconnect = pki.session(
            cert_pem,
            state=str(kwargs.get("state", "connected")),
            has_ssl=bool(kwargs.get("has_ssl", True)),
        )
        broker = self._broker({"client": (session, MagicMock(handle_disconnect=disconnect))})
        assert_that(await broker._disconnect_revoked_sessions(pki.crl_pem), equal_to(0))
        disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_nothing_to_do_without_a_running_broker_or_a_revocation(self, pki: _RevocationFixture) -> None:
        stopped = MQTTBroker(mqtt_port=0, use_owntracks_handler=False)
        assert_that(await stopped._disconnect_revoked_sessions(pki.crl_pem), equal_to(0))
        session, disconnect = pki.session(pki.revoked_pem)
        running = self._broker({"c": (session, MagicMock(handle_disconnect=disconnect))})
        assert_that(await running._disconnect_revoked_sessions(pki.empty_crl_pem), equal_to(0))
        disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reload_stays_flagged_when_dropping_revoked_sessions_fails(self, pki: _RevocationFixture) -> None:
        base_config = _make_tls_config()
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, use_owntracks_handler=False, tls_config=base_config)
        broker._broker = AsyncMock()
        broker._broker.sessions = {}
        broker._running = True
        listener = MagicMock(
            start=AsyncMock(),
            close=AsyncMock(),
            reload=AsyncMock(),
            wait_connections_closed=AsyncMock(),
            port=0,
            actual_port=0,
        )
        broker._tls_listener = listener
        new_config = dataclasses.replace(base_config, crl_pem=pki.crl_pem)
        with patch.object(broker, "_disconnect_revoked_sessions", AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError):
                await broker.reload_tls(new_config, mqtt_tls_port=0)
        listener.reload.assert_awaited_once()
        assert_that(broker.tls_config, is_(new_config))
        assert_that(broker.tls_reload_failed, is_(True))


class TestReloadDropsSessionsOnTrustChange:
    """Disabling TLS or replacing the CA drops connected TLS sessions; a plain certificate rotation does not."""

    @staticmethod
    def _broker(config: TLSConfig) -> tuple[MQTTBroker, AsyncMock]:
        pki = _RevocationFixture()
        session, disconnect = pki.session(pki.valid_pem)
        plain_session, plain_disconnect = pki.session(None, has_ssl=False)
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, use_owntracks_handler=False, tls_config=config)
        inner = MagicMock()
        inner.sessions = {
            "tls": (session, MagicMock(handle_disconnect=disconnect)),
            "tcp": (plain_session, MagicMock(handle_disconnect=plain_disconnect)),
        }
        broker._broker = inner
        broker._running = True
        broker._tls_listener = MagicMock(
            start=AsyncMock(),
            close=AsyncMock(),
            reload=AsyncMock(),
            wait_connections_closed=AsyncMock(),
            port=0,
            actual_port=0,
        )
        return broker, disconnect

    @pytest.mark.asyncio
    async def test_disabling_tls_drops_tls_sessions_only(self) -> None:
        broker, disconnect = self._broker(_make_tls_config())
        await broker.reload_tls(None, mqtt_tls_port=-1)
        disconnect.assert_awaited_once()
        plain_disconnect = broker._broker.sessions["tcp"][1].handle_disconnect  # type: ignore[union-attr]
        plain_disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replacing_the_ca_drops_tls_sessions(self) -> None:
        broker, disconnect = self._broker(_make_tls_config())
        await broker.reload_tls(_make_tls_config(), mqtt_tls_port=0)
        disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rotating_only_the_server_certificate_keeps_sessions(self) -> None:
        config = _make_tls_config()
        broker, disconnect = self._broker(config)
        rotated = dataclasses.replace(config, server_cert_pem=b"rotated-server-certificate")
        await broker.reload_tls(rotated, mqtt_tls_port=0)
        disconnect.assert_not_awaited()


class TestReloadLifecycle:
    """Reloads finish an interrupted drop, and shutdown and reloads exclude each other."""

    @staticmethod
    def _broker(config: TLSConfig) -> tuple[MQTTBroker, MagicMock]:
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=0, use_owntracks_handler=False, tls_config=config)
        inner = MagicMock(shutdown=AsyncMock())
        inner.sessions = {}
        broker._broker = inner
        broker._running = True
        listener = MagicMock(
            start=AsyncMock(),
            close=AsyncMock(),
            reload=AsyncMock(),
            wait_connections_closed=AsyncMock(),
            port=0,
            actual_port=0,
        )
        broker._tls_listener = listener
        return broker, listener

    @pytest.mark.asyncio
    async def test_a_retry_finishes_a_drop_that_failed_after_the_ca_was_replaced(self) -> None:
        broker, _ = self._broker(_make_tls_config())
        new_config = _make_tls_config()
        drops = AsyncMock(side_effect=[RuntimeError("boom"), 0])
        with patch.object(broker, "_drop_connections", drops):
            with pytest.raises(RuntimeError):
                await broker.reload_tls(new_config, mqtt_tls_port=0)
            assert_that(broker.tls_reload_failed, is_(True))
            # The configuration now equals the one on the retry, so only the remembered cause forces the drop.
            await broker.reload_tls(new_config, mqtt_tls_port=0)
        assert_that(drops.await_count, equal_to(2))
        assert_that(broker.tls_reload_failed, is_(False))
        await broker.reload_tls(new_config, mqtt_tls_port=0)
        assert_that(drops.await_count, equal_to(2))

    @pytest.mark.asyncio
    async def test_a_retry_finishes_a_drop_that_failed_while_disabling_tls(self) -> None:
        broker, _ = self._broker(_make_tls_config())
        drops = AsyncMock(side_effect=[RuntimeError("boom"), 0])
        with patch.object(broker, "_drop_connections", drops):
            with pytest.raises(RuntimeError):
                await broker.reload_tls(None, mqtt_tls_port=-1)
            await broker.reload_tls(None, mqtt_tls_port=-1)
        assert_that(drops.await_count, equal_to(2))
        assert_that(broker.tls_reload_failed, is_(False))

    @pytest.mark.asyncio
    async def test_disabling_tls_closes_connections_that_have_no_session_yet(self) -> None:
        broker, _ = self._broker(_make_tls_config())
        pending = _transport(ssl_object=MagicMock())
        broker._tls_connections.add(pending)
        await broker.reload_tls(None, mqtt_tls_port=-1)
        pending.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload_after_shutdown_is_rejected(self) -> None:
        broker, listener = self._broker(_make_tls_config())
        await broker.stop()
        with pytest.raises(RuntimeError, match="not running"):
            await broker.reload_tls(_make_tls_config(), mqtt_tls_port=0)
        listener.reload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stop_waits_for_a_reload_that_is_replacing_the_listener(self) -> None:
        broker, old = self._broker(_make_tls_config())
        started = asyncio.Event()
        release = asyncio.Event()
        replacement = MagicMock(close=AsyncMock(), wait_connections_closed=AsyncMock())

        async def slow_start(*_args: object) -> MagicMock:
            started.set()
            await release.wait()
            return replacement

        with patch.object(broker, "_start_tls_listener", side_effect=slow_start):
            reload_task = asyncio.create_task(broker.reload_tls(_make_tls_config(), mqtt_tls_port=45002))
            await started.wait()
            stop_task = asyncio.create_task(broker.stop())
            await asyncio.sleep(0)
            assert_that(stop_task.done(), is_(False))
            release.set()
            await asyncio.gather(reload_task, stop_task)
        replacement.close.assert_awaited_once()
        old.close.assert_awaited()
        assert_that(broker._tls_listener, is_(none()))

    @pytest.mark.asyncio
    async def test_finishing_a_pending_drop_leaves_the_listener_and_config_alone(self) -> None:
        config = _make_tls_config()
        broker, listener = self._broker(config)
        pending = _transport(ssl_object=MagicMock())
        broker._tls_connections.add(pending)
        broker._pending_trust_drop = "CA certificate replaced"
        broker.tls_reload_failed = True
        assert_that(broker.trust_drop_pending, is_(True))

        await broker.finish_pending_trust_drop()

        pending.close.assert_called_once()
        assert_that(broker.trust_drop_pending, is_(False))
        assert_that(broker.tls_reload_failed, is_(False))
        assert_that(broker.tls_config, is_(config))
        listener.reload.assert_not_awaited()
        listener.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finishing_nothing_pending_is_a_no_op(self) -> None:
        broker, _ = self._broker(_make_tls_config())
        pending = _transport(ssl_object=MagicMock())
        broker._tls_connections.add(pending)
        await broker.finish_pending_trust_drop()
        pending.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failed_finish_keeps_the_drop_pending(self) -> None:
        broker, _ = self._broker(_make_tls_config())
        broker._pending_trust_drop = "TLS disabled"
        with patch.object(broker, "_drop_connections", AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError):
                await broker.finish_pending_trust_drop()
        assert_that(broker.trust_drop_pending, is_(True))

    @pytest.mark.asyncio
    async def test_stop_closes_transports_that_have_no_session_and_drains_the_handlers(self) -> None:
        broker, listener = self._broker(_make_tls_config())
        pending = _transport(ssl_object=MagicMock())
        broker._tls_connections.add(pending)
        await broker.stop()
        pending.close.assert_called_once()
        listener.wait_connections_closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_still_completes_when_a_handler_will_not_end(self, caplog: pytest.LogCaptureFixture) -> None:
        broker, listener = self._broker(_make_tls_config())
        listener.wait_connections_closed = AsyncMock(side_effect=TimeoutError)
        with caplog.at_level(logging.WARNING, logger="app.mqtt.broker"):
            await broker.stop()
        assert_that(broker.is_running, is_(False))
        assert_that(caplog.text, contains_string("Connection handlers still running"))
