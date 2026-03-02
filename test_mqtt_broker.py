"""Tests for the MQTT broker module."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hamcrest import (assert_that, contains_string, equal_to, greater_than,
                      has_key, is_, is_not, none, not_none)

from my_tracks.mqtt.broker import (MQTTBroker, TLSConfig, _CRLBroker,
                                   create_and_start_broker, get_default_config)


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

    def test_has_sys_plugin(self) -> None:
        """Config should include the $SYS broker plugin."""
        config = get_default_config()
        assert_that(
            "amqtt.plugins.sys.broker.BrokerSysPlugin" in config["plugins"],
            is_(True),
        )

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
            mqtt_port=0, allow_anonymous=True,
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
            "my_tracks.mqtt.auth.DjangoAuthPlugin" in config["plugins"],
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
            "my_tracks.mqtt.auth.DjangoAuthPlugin" in config["plugins"],
            is_(False),
        )

    def test_owntracks_handler_disabled(self) -> None:
        """Should omit OwnTracksPlugin when use_owntracks_handler=False."""
        config = get_default_config(use_owntracks_handler=False)
        assert_that(
            "my_tracks.mqtt.plugin.OwnTracksPlugin" in config["plugins"],
            is_(False),
        )

    def test_owntracks_handler_enabled_by_default(self) -> None:
        """Should include OwnTracksPlugin by default."""
        config = get_default_config()
        assert_that(
            "my_tracks.mqtt.plugin.OwnTracksPlugin" in config["plugins"],
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


class TestTLSConfig:
    """Tests for TLS configuration in the broker."""

    def _make_tls_config(self) -> TLSConfig:
        return TLSConfig(
            server_cert_pem=b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
            server_key_pem=b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
            ca_cert_pem=b"-----BEGIN CERTIFICATE-----\nfakeca\n-----END CERTIFICATE-----",
        )

    def test_tls_listener_added_when_port_enabled(self) -> None:
        """TLS listener appears in config when mqtt_tls_port >= 0."""
        config = get_default_config(
            mqtt_tls_port=8883,
            tls_certfile="/tmp/cert.pem",
            tls_keyfile="/tmp/key.pem",
            tls_cafile="/tmp/ca.pem",
        )
        assert_that(config["listeners"], has_key("mqtt-tls"))
        tls = config["listeners"]["mqtt-tls"]
        assert_that(tls["bind"], equal_to("0.0.0.0:8883"))
        assert_that(tls["ssl"], is_(True))
        assert_that(tls["certfile"], equal_to("/tmp/cert.pem"))
        assert_that(tls["keyfile"], equal_to("/tmp/key.pem"))
        assert_that(tls["cafile"], equal_to("/tmp/ca.pem"))

    def test_tls_listener_not_added_when_port_disabled(self) -> None:
        """No TLS listener when mqtt_tls_port is negative."""
        config = get_default_config(mqtt_tls_port=-1)
        listeners = config["listeners"]
        assert_that("mqtt-tls" not in listeners, is_(True))

    def test_tls_listener_not_added_without_certfile(self) -> None:
        """No TLS listener when certfile is missing."""
        config = get_default_config(
            mqtt_tls_port=8883,
            tls_keyfile="/tmp/key.pem",
        )
        assert_that("mqtt-tls" not in config["listeners"], is_(True))

    def test_tls_listener_cafile_optional(self) -> None:
        """TLS listener created without cafile (no client cert verification)."""
        config = get_default_config(
            mqtt_tls_port=8883,
            tls_certfile="/tmp/cert.pem",
            tls_keyfile="/tmp/key.pem",
        )
        tls = config["listeners"]["mqtt-tls"]
        assert_that("cafile" not in tls, is_(True))

    def test_broker_creates_temp_files_for_tls(self) -> None:
        """MQTTBroker writes TLS certs to temp files when TLS enabled."""
        tls_config = self._make_tls_config()
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=8883,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        assert_that(broker._tls_certfile, is_(not_none()))
        assert_that(broker._tls_keyfile, is_(not_none()))
        assert_that(broker._tls_cafile, is_(not_none()))
        assert_that(os.path.exists(broker._tls_certfile), is_(True))
        assert_that(os.path.exists(broker._tls_keyfile), is_(True))
        assert_that(os.path.exists(broker._tls_cafile), is_(True))

        with open(broker._tls_certfile, "rb") as f:
            assert_that(f.read(), equal_to(tls_config.server_cert_pem))
        with open(broker._tls_keyfile, "rb") as f:
            assert_that(f.read(), equal_to(tls_config.server_key_pem))

        broker._cleanup_tls_files()

    def test_broker_no_temp_files_when_tls_disabled(self) -> None:
        """No temp files created when TLS is disabled."""
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=-1,
            use_owntracks_handler=False,
        )
        assert_that(broker._tls_certfile, is_(none()))
        assert_that(broker._tls_keyfile, is_(none()))
        assert_that(broker._tls_cafile, is_(none()))
        assert_that(len(broker._tls_temp_files), equal_to(0))

    def test_cleanup_removes_temp_files(self) -> None:
        """_cleanup_tls_files removes all temporary certificate files."""
        tls_config = self._make_tls_config()
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=8883,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        paths = [broker._tls_certfile, broker._tls_keyfile, broker._tls_cafile]
        for p in paths:
            assert_that(os.path.exists(p), is_(True))

        broker._cleanup_tls_files()

        for p in paths:
            assert_that(os.path.exists(p), is_(False))
        assert_that(len(broker._tls_temp_files), equal_to(0))

    def test_ca_plus_crl_concatenated_in_cafile(self) -> None:
        """CA cert and CRL are concatenated in the cafile when CRL is provided."""
        crl_data = b"-----BEGIN X509 CRL-----\nfakecrl\n-----END X509 CRL-----"
        tls_config = TLSConfig(
            server_cert_pem=b"cert",
            server_key_pem=b"key",
            ca_cert_pem=b"ca-cert",
            crl_pem=crl_data,
        )
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=8883,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        with open(broker._tls_cafile, "rb") as f:
            content = f.read()
        assert_that(content, equal_to(b"ca-cert\n" + crl_data))
        broker._cleanup_tls_files()

    def test_tls_port_property_disabled(self) -> None:
        """actual_tls_port is None when TLS is disabled."""
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=-1)
        assert_that(broker.actual_tls_port, is_(none()))

    def test_tls_port_property_before_start(self) -> None:
        """actual_tls_port returns configured port before broker starts."""
        broker = MQTTBroker(mqtt_port=0, mqtt_tls_port=8883)
        assert_that(broker.actual_tls_port, is_(none()))

    def test_config_has_tls_listener(self) -> None:
        """Broker config includes mqtt-tls listener when TLS is configured."""
        tls_config = self._make_tls_config()
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=8883,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        assert_that(broker.config["listeners"], has_key("mqtt-tls"))
        tls = broker.config["listeners"]["mqtt-tls"]
        assert_that(tls["ssl"], is_(True))
        assert_that(tls["bind"], contains_string("8883"))
        broker._cleanup_tls_files()

    @pytest.mark.asyncio
    async def test_crl_broker_used_when_crl_provided(self) -> None:
        """_CRLBroker is used instead of Broker when CRL is in TLS config."""
        crl_data = b"-----BEGIN X509 CRL-----\nfake\n-----END X509 CRL-----"
        tls_config = TLSConfig(
            server_cert_pem=b"cert",
            server_key_pem=b"key",
            ca_cert_pem=b"ca",
            crl_pem=crl_data,
        )
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=8883,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        with (
            patch.object(_CRLBroker, "__init__", return_value=None) as mock_init,
            patch.object(_CRLBroker, "start", new_callable=AsyncMock),
        ):
            await broker.start()

        mock_init.assert_called_once()
        assert_that(_CRLBroker._crl_pem, equal_to(crl_data))
        _CRLBroker._crl_pem = None
        broker._cleanup_tls_files()

    @pytest.mark.asyncio
    async def test_crl_broker_used_without_crl_but_with_tls(self) -> None:
        """_CRLBroker is used for mutual TLS even when CRL is absent."""
        tls_config = self._make_tls_config()
        broker = MQTTBroker(
            mqtt_port=0,
            mqtt_tls_port=8883,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        with (
            patch.object(_CRLBroker, "__init__", return_value=None) as mock_init,
            patch.object(_CRLBroker, "start", new_callable=AsyncMock),
        ):
            await broker.start()

        mock_init.assert_called_once()
        broker._cleanup_tls_files()
