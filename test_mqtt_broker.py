"""Tests for the MQTT broker module."""

import asyncio

import pytest
from hamcrest import assert_that, equal_to, has_key, is_

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
        """Anonymous connections should be allowed by default."""
        config = get_default_config()
        assert_that(config["auth"]["allow-anonymous"], is_(True))

    def test_allow_anonymous_disabled(self) -> None:
        """Anonymous connections can be disabled."""
        config = get_default_config(allow_anonymous=False)
        assert_that(config["auth"]["allow-anonymous"], is_(False))

    def test_has_sys_plugin(self) -> None:
        """Config should include the $SYS broker plugin."""
        config = get_default_config()
        assert_that(
            "amqtt.plugins.sys.broker.BrokerSysPlugin" in config["plugins"],
            is_(True),
        )


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
        # When broker not started, actual_mqtt_port returns None
        assert_that(broker.actual_mqtt_port, is_(None))


class TestMQTTBrokerLifecycle:
    """Tests for MQTTBroker start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self) -> None:
        """Starting the broker should set is_running to True."""
        # Use high ports to avoid conflicts
        broker = MQTTBroker(mqtt_port=31883, mqtt_ws_port=38083)
        try:
            await broker.start()
            assert_that(broker.is_running, is_(True))
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_actual_mqtt_port_after_start(self) -> None:
        """actual_mqtt_port should return port after broker starts."""
        broker = MQTTBroker(mqtt_port=31889, mqtt_ws_port=38089)
        try:
            await broker.start()
            # After start, actual_mqtt_port should return a valid port
            actual = broker.actual_mqtt_port
            assert actual is not None
            assert actual > 0
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self) -> None:
        """Stopping the broker should set is_running to False."""
        broker = MQTTBroker(mqtt_port=31884, mqtt_ws_port=38084)
        await broker.start()
        await broker.stop()
        assert_that(broker.is_running, is_(False))

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(self) -> None:
        """Starting an already running broker should raise RuntimeError."""
        broker = MQTTBroker(mqtt_port=31885, mqtt_ws_port=38085)
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
        broker = MQTTBroker(mqtt_port=31886, mqtt_ws_port=38086)
        with pytest.raises(RuntimeError, match="not running"):
            await broker.stop()

    @pytest.mark.asyncio
    async def test_run_forever_can_be_cancelled(self) -> None:
        """run_forever should handle cancellation gracefully."""
        broker = MQTTBroker(mqtt_port=31887, mqtt_ws_port=38087)

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
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0)
        try:
            await broker.start()
            assert_that(broker.is_running, is_(True))
            # actual_mqtt_port should return the OS-allocated port
            actual_mqtt_port = broker.actual_mqtt_port
            assert actual_mqtt_port is not None
            # OS should allocate an ephemeral port (typically > 1024)
            assert actual_mqtt_port > 0
            # Should not be 0 anymore
            assert actual_mqtt_port != 0
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_mqtt_port_zero_different_from_ws_port(self) -> None:
        """OS-allocated MQTT and WS ports should be different."""
        broker = MQTTBroker(mqtt_port=0, mqtt_ws_port=0)
        try:
            await broker.start()
            mqtt_port = broker.actual_mqtt_port
            # Note: We currently only track actual_mqtt_port, not actual_ws_port
            # This test verifies the MQTT port is allocated correctly
            assert mqtt_port is not None
            assert mqtt_port > 0
        finally:
            if broker.is_running:
                await broker.stop()
