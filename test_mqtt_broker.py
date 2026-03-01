"""Tests for the MQTT broker module."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import (assert_that, equal_to, greater_than, has_key, is_,
                      is_not, not_none)

from my_tracks.mqtt.broker import (MQTTBroker, create_and_start_broker,
                                   get_default_config)


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

    def test_default_ws_port(self) -> None:
        """Default WebSocket port should be 8083."""
        config = get_default_config()
        assert_that(config["listeners"]["ws-mqtt"]["bind"], equal_to("0.0.0.0:8083"))

    def test_custom_ws_port(self) -> None:
        """Custom WebSocket port should be respected."""
        config = get_default_config(mqtt_ws_port=18083)
        assert_that(config["listeners"]["ws-mqtt"]["bind"], equal_to("0.0.0.0:18083"))

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
        assert_that(broker.mqtt_ws_port, equal_to(8083))

    def test_custom_ports(self) -> None:
        """Broker should accept custom ports."""
        broker = MQTTBroker(mqtt_port=11883, mqtt_ws_port=18083)
        assert_that(broker.mqtt_port, equal_to(11883))
        assert_that(broker.mqtt_ws_port, equal_to(18083))

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

    def test_actual_ws_port_none_before_start(self) -> None:
        """actual_ws_port should return None before broker starts."""
        broker = MQTTBroker()
        assert_that(broker.actual_ws_port, is_(None))


class TestMQTTBrokerLifecycle:
    """Tests for MQTTBroker start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self) -> None:
        """Starting the broker should set is_running to True."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            assert_that(broker.is_running, is_(True))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_actual_mqtt_port_after_start(self) -> None:
        """actual_mqtt_port should return port after broker starts."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            # After start, actual_mqtt_port should return a valid port
            actual = broker.actual_mqtt_port
            assert_that(actual, is_(not_none()))
            assert_that(actual, greater_than(0))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self) -> None:
        """Stopping the broker should set is_running to False."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        await broker.start()
        await broker.stop()
        assert_that(broker.is_running, is_(False))

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(self) -> None:
        """Starting an already running broker should raise RuntimeError."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
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
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        with pytest.raises(RuntimeError, match="not running"):
            await broker.stop()

    @pytest.mark.asyncio
    async def test_run_forever_can_be_cancelled(self) -> None:
        """run_forever should handle cancellation gracefully."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)

        async def run_then_cancel() -> None:
            task = asyncio.create_task(broker.run_forever())
            await asyncio.sleep(0.5)  # Let it start
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_then_cancel()
        # Broker should be stopped after cancellation
        assert_that(broker.is_running, is_(False))


class TestOSAllocatedPorts:
    """Tests for OS-allocated port functionality (port 0)."""

    @pytest.mark.asyncio
    async def test_mqtt_port_zero_allocates_actual_port(self) -> None:
        """Starting broker with port 0 should allocate a real port."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            assert_that(broker.is_running, is_(True))
            # actual_mqtt_port should return the OS-allocated port
            actual_mqtt_port = broker.actual_mqtt_port
            assert_that(actual_mqtt_port, is_(not_none()))
            # OS should allocate an ephemeral port (typically > 1024)
            assert_that(actual_mqtt_port, greater_than(0))
            # Should not be 0 anymore
            assert_that(actual_mqtt_port, is_not(equal_to(0)))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_ws_port_zero_allocates_actual_port(self) -> None:
        """Starting broker with WS port 0 should allocate a real port."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            actual_ws_port = broker.actual_ws_port
            assert_that(actual_ws_port, is_(not_none()))
            assert_that(actual_ws_port, greater_than(0))
            assert_that(actual_ws_port, is_not(equal_to(0)))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_mqtt_and_ws_ports_are_different(self) -> None:
        """OS-allocated MQTT and WS ports should be different."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            mqtt_port = broker.actual_mqtt_port
            ws_port = broker.actual_ws_port
            assert_that(mqtt_port, is_(not_none()))
            assert_that(ws_port, is_(not_none()))
            assert_that(mqtt_port, is_not(equal_to(ws_port)))
        finally:
            if broker.is_running:
                await broker.stop()


class TestProtocolListening:
    """Verify the broker is actually listening on each protocol's port."""

    @pytest.mark.asyncio
    async def test_tcp_mqtt_port_accepting_connections(self) -> None:
        """The MQTT TCP listener should accept raw TCP connections."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            port = broker.actual_mqtt_port
            assert_that(port, is_(not_none()))

            # Open a plain TCP connection — the broker should accept it
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_ws_mqtt_port_accepting_connections(self) -> None:
        """The MQTT WebSocket listener should accept TCP connections."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            port = broker.actual_ws_port
            assert_that(port, is_(not_none()))

            # The WS listener is still a TCP server underneath —
            # verify it accepts the transport-level connection.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_tcp_mqtt_port_not_listening_after_stop(self) -> None:
        """After stopping, the MQTT TCP port should refuse connections."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        await broker.start()
        port = broker.actual_mqtt_port
        assert_that(port, is_(not_none()))
        await broker.stop()

        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

    @pytest.mark.asyncio
    async def test_ws_mqtt_port_not_listening_after_stop(self) -> None:
        """After stopping, the MQTT WebSocket port should refuse connections."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        await broker.start()
        port = broker.actual_ws_port
        assert_that(port, is_(not_none()))
        await broker.stop()

        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

    @pytest.mark.asyncio
    async def test_both_protocols_listening_simultaneously(self) -> None:
        """Both TCP and WS listeners should accept connections at the same time."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
        try:
            await broker.start()
            mqtt_port = broker.actual_mqtt_port
            ws_port = broker.actual_ws_port
            assert_that(mqtt_port, is_(not_none()))
            assert_that(ws_port, is_(not_none()))

            # Connect to both simultaneously
            tcp_reader, tcp_writer = await asyncio.open_connection(
                "127.0.0.1", mqtt_port
            )
            ws_reader, ws_writer = await asyncio.open_connection(
                "127.0.0.1", ws_port
            )

            # Both connections should be open
            assert_that(tcp_writer.is_closing(), is_(False))
            assert_that(ws_writer.is_closing(), is_(False))

            tcp_writer.close()
            ws_writer.close()
            await tcp_writer.wait_closed()
            await ws_writer.wait_closed()
        finally:
            if broker.is_running:
                await broker.stop()


class TestAmqttBrokerProperty:
    """Tests for amqtt_broker property."""

    def test_none_before_start(self) -> None:
        """amqtt_broker should be None before start."""
        broker = MQTTBroker()
        assert_that(broker.amqtt_broker, is_(None))

    @pytest.mark.asyncio
    async def test_set_after_start(self) -> None:
        """amqtt_broker should reference the underlying Broker after start."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)
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
    """Tests for port caching and fallback in actual_mqtt_port / actual_ws_port."""

    def test_actual_mqtt_port_returns_cached_value(self) -> None:
        """Should return cached MQTT port without calling _discover_port."""
        broker = MQTTBroker()
        broker._actual_mqtt_port = 12345
        assert_that(broker.actual_mqtt_port, equal_to(12345))

    def test_actual_ws_port_returns_cached_value(self) -> None:
        """Should return cached WS port without calling _discover_port."""
        broker = MQTTBroker()
        broker._actual_ws_port = 54321
        assert_that(broker.actual_ws_port, equal_to(54321))

    def test_actual_mqtt_port_fallback_to_configured(self) -> None:
        """Should fall back to configured mqtt_port when discovery fails."""
        broker = MQTTBroker(mqtt_port=1883)
        broker._broker = MagicMock()
        with patch.object(broker, "_discover_port", return_value=None):
            result = broker.actual_mqtt_port
        assert_that(result, equal_to(1883))

    def test_actual_ws_port_fallback_to_configured(self) -> None:
        """Should fall back to configured mqtt_ws_port when discovery fails."""
        broker = MQTTBroker(mqtt_ws_port=8083)
        broker._broker = MagicMock()
        with patch.object(broker, "_discover_port", return_value=None):
            result = broker.actual_ws_port
        assert_that(result, equal_to(8083))


class TestCreateAndStartBroker:
    """Tests for create_and_start_broker convenience function."""

    @pytest.mark.asyncio
    async def test_creates_running_broker(self) -> None:
        """Should create and start a broker with the given parameters."""
        broker = await create_and_start_broker(
            mqtt_port=0, mqtt_ws_port=0, allow_anonymous=True,
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

        # Second call should use cached value (no _discover_port call)
        assert_that(broker.actual_mqtt_port, equal_to(11111))
        assert_that(broker._actual_mqtt_port, equal_to(11111))

    def test_actual_ws_port_caches_discovered_value(self) -> None:
        """Once discovered, actual_ws_port should cache and return the same value."""
        broker = MQTTBroker()
        broker._broker = MagicMock()
        with patch.object(broker, "_discover_port", return_value=22222):
            first = broker.actual_ws_port
            assert_that(first, equal_to(22222))

        assert_that(broker.actual_ws_port, equal_to(22222))
        assert_that(broker._actual_ws_port, equal_to(22222))


class TestRunForeverAutoStart:
    """Tests for run_forever auto-start behavior."""

    @pytest.mark.asyncio
    async def test_auto_starts_when_not_running(self) -> None:
        """run_forever should call start() if broker is not yet running."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0, use_owntracks_handler=False)

        async def cancel_soon() -> None:
            task = asyncio.create_task(broker.run_forever())
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await cancel_soon()
        # Broker was started by run_forever and then stopped by cancellation
        assert_that(broker.is_running, is_(False))
