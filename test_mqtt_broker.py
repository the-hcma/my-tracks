"""Tests for the MQTT broker module."""

import asyncio

import pytest
from hamcrest import (assert_that, equal_to, greater_than, has_key, is_,
                      is_not, not_none)

from my_tracks.mqtt.broker import MQTTBroker, get_default_config


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
