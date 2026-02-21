"""
Tests for ASGI configuration, runtime config, MQTT broker integration,
and client disconnect handling.

These tests verify that the ASGI lifespan events properly start
and stop the MQTT broker, that runtime configuration works correctly,
and that client disconnections are handled gracefully.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to, is_


class TestRuntimeConfig:
    """Tests for runtime configuration module."""

    def test_get_runtime_config_defaults(self, tmp_path: Path) -> None:
        """Returns defaults when config file doesn't exist."""
        from config.runtime import get_runtime_config

        with patch("config.runtime.CONFIG_FILE", tmp_path / "nonexistent.json"):
            config = get_runtime_config()
            assert_that(config["http_port"], is_(equal_to(8080)))
            assert_that(config["mqtt_port"], is_(equal_to(1883)))

    def test_get_runtime_config_from_file(self, tmp_path: Path) -> None:
        """Reads config from JSON file."""
        from config.runtime import get_runtime_config

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 1884, "http_port": 9090}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            config = get_runtime_config()
            assert_that(config["mqtt_port"], is_(equal_to(1884)))
            assert_that(config["http_port"], is_(equal_to(9090)))

    def test_write_runtime_config(self, tmp_path: Path) -> None:
        """Writes config to JSON file."""
        from config.runtime import write_runtime_config

        config_file = tmp_path / "config.json"

        with patch("config.runtime.CONFIG_FILE", config_file):
            write_runtime_config({"mqtt_port": 1885})
            assert config_file.exists()
            data = json.loads(config_file.read_text())
            assert_that(data["mqtt_port"], is_(equal_to(1885)))

    def test_update_runtime_config(self, tmp_path: Path) -> None:
        """Updates single key in config."""
        from config.runtime import update_runtime_config

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 1883}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            update_runtime_config("actual_mqtt_port", 12345)
            data = json.loads(config_file.read_text())
            assert_that(data["actual_mqtt_port"], is_(equal_to(12345)))
            assert_that(data["mqtt_port"], is_(equal_to(1883)))


class TestGetMqttPort:
    """Tests for get_mqtt_port function."""

    def test_default_port(self, tmp_path: Path) -> None:
        """Returns default port 1883 when config file doesn't exist."""
        from config.runtime import get_mqtt_port

        with patch("config.runtime.CONFIG_FILE", tmp_path / "nonexistent.json"):
            assert_that(get_mqtt_port(), is_(equal_to(1883)))

    def test_custom_port(self, tmp_path: Path) -> None:
        """Returns custom port from config file."""
        from config.runtime import get_mqtt_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 1884}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_mqtt_port(), is_(equal_to(1884)))

    def test_disabled_port(self, tmp_path: Path) -> None:
        """Returns negative when MQTT is disabled."""
        from config.runtime import get_mqtt_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": -1}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_mqtt_port(), is_(equal_to(-1)))

    def test_os_allocated_port(self, tmp_path: Path) -> None:
        """Returns 0 when OS should allocate port."""
        from config.runtime import get_mqtt_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 0}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_mqtt_port(), is_(equal_to(0)))


class TestGetHttpPort:
    """Tests for get_http_port function."""

    def test_default_http_port(self, tmp_path: Path) -> None:
        """Returns default port 8080 when config file doesn't exist."""
        from config.runtime import get_http_port

        with patch("config.runtime.CONFIG_FILE", tmp_path / "nonexistent.json"):
            assert_that(get_http_port(), is_(equal_to(8080)))

    def test_custom_http_port(self, tmp_path: Path) -> None:
        """Returns custom port from config file."""
        from config.runtime import get_http_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"http_port": 9090}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_http_port(), is_(equal_to(9090)))

    def test_disabled_http_port(self, tmp_path: Path) -> None:
        """Returns negative when HTTP is disabled."""
        from config.runtime import get_http_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"http_port": -1}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_http_port(), is_(equal_to(-1)))

    def test_os_allocated_http_port(self, tmp_path: Path) -> None:
        """Returns 0 when OS should allocate port."""
        from config.runtime import get_http_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"http_port": 0}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_http_port(), is_(equal_to(0)))


class TestActualPortFunctions:
    """Tests for get_actual_mqtt_port and get_actual_http_port."""

    def test_actual_mqtt_port_not_set(self, tmp_path: Path) -> None:
        """Returns None when actual_mqtt_port not set."""
        from config.runtime import get_actual_mqtt_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 0}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_actual_mqtt_port(), is_(None))

    def test_actual_mqtt_port_set(self, tmp_path: Path) -> None:
        """Returns the actual port after OS allocation."""
        from config.runtime import get_actual_mqtt_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_port": 0, "actual_mqtt_port": 54321}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_actual_mqtt_port(), is_(equal_to(54321)))

    def test_actual_http_port_not_set(self, tmp_path: Path) -> None:
        """Returns None when actual_http_port not set."""
        from config.runtime import get_actual_http_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"http_port": 0}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_actual_http_port(), is_(None))

    def test_actual_http_port_set(self, tmp_path: Path) -> None:
        """Returns the actual port after OS allocation."""
        from config.runtime import get_actual_http_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"http_port": 0, "actual_http_port": 49876}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_actual_http_port(), is_(equal_to(49876)))


class TestLifespanHandler:
    """Tests for ASGI lifespan handler."""

    @pytest.mark.asyncio
    async def test_startup_with_mqtt_enabled(self) -> None:
        """MQTT broker starts when port >= 0."""
        from config.asgi import lifespan_handler

        mock_broker = MagicMock()
        mock_broker.start = AsyncMock()
        mock_broker.actual_mqtt_port = 1883
        mock_broker.is_running = False

        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        with (
            patch("config.asgi.get_mqtt_port", return_value=1883),
            patch("config.asgi.MQTTBroker", return_value=mock_broker),
            patch("config.asgi._mqtt_broker", None),
        ):
            await lifespan_handler({}, receive, send)

        mock_broker.start.assert_called_once()
        send.assert_any_call({"type": "lifespan.startup.complete"})
        send.assert_any_call({"type": "lifespan.shutdown.complete"})

    @pytest.mark.asyncio
    async def test_startup_with_mqtt_disabled(self) -> None:
        """MQTT broker does not start when port < 0."""
        from config.asgi import lifespan_handler

        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        with (
            patch("config.asgi.get_mqtt_port", return_value=-1),
            patch("config.asgi.MQTTBroker") as mock_broker_class,
        ):
            await lifespan_handler({}, receive, send)

        mock_broker_class.assert_not_called()
        send.assert_any_call({"type": "lifespan.startup.complete"})

    @pytest.mark.asyncio
    async def test_startup_with_os_allocated_port(self) -> None:
        """MQTT broker starts when port = 0 (OS allocates)."""
        from config.asgi import lifespan_handler

        mock_broker = MagicMock()
        mock_broker.start = AsyncMock()
        mock_broker.actual_mqtt_port = 54321  # OS-allocated port
        mock_broker.is_running = False

        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        with (
            patch("config.asgi.get_mqtt_port", return_value=0),
            patch("config.asgi.MQTTBroker", return_value=mock_broker),
            patch("config.asgi.update_runtime_config") as mock_update,
            patch("config.asgi._mqtt_broker", None),
        ):
            await lifespan_handler({}, receive, send)

        mock_broker.start.assert_called_once()
        # Should update config with actual port
        mock_update.assert_called_with("actual_mqtt_port", 54321)
        send.assert_any_call({"type": "lifespan.startup.complete"})

    @pytest.mark.asyncio
    async def test_shutdown_stops_running_broker(self) -> None:
        """Running MQTT broker is stopped on shutdown."""
        from config.asgi import lifespan_handler

        mock_broker = MagicMock()
        mock_broker.start = AsyncMock()
        mock_broker.stop = AsyncMock()
        mock_broker.actual_mqtt_port = 1883
        mock_broker.is_running = True

        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        with (
            patch("config.asgi.get_mqtt_port", return_value=1883),
            patch("config.asgi.MQTTBroker", return_value=mock_broker),
        ):
            await lifespan_handler({}, receive, send)

        mock_broker.stop.assert_called_once()
        send.assert_any_call({"type": "lifespan.shutdown.complete"})

    @pytest.mark.asyncio
    async def test_startup_failure_sends_failed_message(self) -> None:
        """Startup failure sends lifespan.startup.failed message."""
        from config.asgi import lifespan_handler

        mock_broker = MagicMock()
        mock_broker.start = AsyncMock(side_effect=Exception("Broker failed"))

        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        with (
            patch("config.asgi.get_mqtt_port", return_value=1883),
            patch("config.asgi.MQTTBroker", return_value=mock_broker),
        ):
            await lifespan_handler({}, receive, send)

        # Check that startup.failed was sent
        calls = [call[0][0] for call in send.call_args_list]
        assert any(
            c.get("type") == "lifespan.startup.failed" for c in calls
        ), f"Expected lifespan.startup.failed in {calls}"


class TestClientDisconnectMiddleware:
    """Tests for the ClientDisconnectMiddleware ASGI middleware."""

    @pytest.mark.asyncio
    async def test_passes_normal_requests_through(self) -> None:
        """Normal requests are forwarded to the wrapped app unchanged."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock()
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        inner_app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_catches_cancelled_error_on_client_disconnect(self) -> None:
        """CancelledError from client disconnect is caught, not propagated."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock(side_effect=asyncio.CancelledError)
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/api/data/"}
        receive = AsyncMock()
        send = AsyncMock()

        # Should NOT raise — the middleware catches it
        await middleware(scope, receive, send)

    @pytest.mark.asyncio
    async def test_logs_disconnect_at_debug_level(self) -> None:
        """Client disconnect is logged at DEBUG with method and path."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock(side_effect=asyncio.CancelledError)
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "POST", "path": "/api/location/"}
        receive = AsyncMock()
        send = AsyncMock()

        with patch("config.asgi.logger") as mock_logger:
            await middleware(scope, receive, send)

        mock_logger.debug.assert_called_once_with(
            "Client disconnected during %s %s", "POST", "/api/location/"
        )

    @pytest.mark.asyncio
    async def test_propagates_other_exceptions(self) -> None:
        """Non-CancelledError exceptions are not caught."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock(side_effect=ValueError("something broke"))
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        with pytest.raises(ValueError, match="something broke"):
            await middleware(scope, receive, send)
