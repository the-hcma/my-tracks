"""
Tests for ASGI configuration, runtime config, MQTT broker integration,
and client disconnect handling.

These tests verify that runtime configuration works correctly,
that the MQTT broker starts via AppConfig.ready(), and that client
disconnections are handled gracefully by the ASGI middleware.
"""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
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
            assert_that(config_file.exists(), is_(True))
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


class TestMqttBrokerStartup:
    """Tests for MQTT broker startup via AppConfig.ready()."""

    def test_starts_broker_when_config_exists(self, tmp_path: Path) -> None:
        """Broker thread starts when runtime config file exists with port >= 0."""
        import my_tracks.apps as apps_module

        config_file = tmp_path / ".runtime-config.json"
        config_file.write_text(json.dumps({"mqtt_port": 1883}))

        mock_thread_class = MagicMock()
        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        with (
            patch("config.runtime.CONFIG_FILE", config_file),
            patch.object(apps_module._state, "thread", None),
            patch("threading.Thread", mock_thread_class),
            patch("atexit.register") as mock_atexit,
        ):
            from my_tracks.apps import MyTracksConfig

            app_config = MyTracksConfig("my_tracks", apps_module)
            app_config.ready()

        mock_thread_class.assert_called_once()
        call_kwargs = mock_thread_class.call_args[1]
        assert_that(call_kwargs["daemon"], is_(True))
        assert_that(call_kwargs["name"], is_(equal_to("mqtt-broker")))
        assert_that(call_kwargs["args"], is_(equal_to((1883,))))
        mock_thread_instance.start.assert_called_once()
        mock_atexit.assert_called_once()

    def test_skips_broker_when_no_config_file(self, tmp_path: Path) -> None:
        """Broker does not start when runtime config file is missing."""
        import my_tracks.apps as apps_module

        missing_file = tmp_path / "nonexistent.json"

        with (
            patch("config.runtime.CONFIG_FILE", missing_file),
            patch("threading.Thread") as mock_thread_class,
        ):
            from my_tracks.apps import MyTracksConfig

            app_config = MyTracksConfig("my_tracks", apps_module)
            app_config.ready()

        mock_thread_class.assert_not_called()

    def test_skips_broker_when_mqtt_disabled(self, tmp_path: Path) -> None:
        """Broker does not start when mqtt_port is negative."""
        import my_tracks.apps as apps_module

        config_file = tmp_path / ".runtime-config.json"
        config_file.write_text(json.dumps({"mqtt_port": -1}))

        with (
            patch("config.runtime.CONFIG_FILE", config_file),
            patch("threading.Thread") as mock_thread_class,
        ):
            from my_tracks.apps import MyTracksConfig

            app_config = MyTracksConfig("my_tracks", apps_module)
            app_config.ready()

        mock_thread_class.assert_not_called()

    def test_starts_broker_with_os_allocated_port(self, tmp_path: Path) -> None:
        """Broker thread starts with port 0 for OS allocation."""
        import my_tracks.apps as apps_module

        config_file = tmp_path / ".runtime-config.json"
        config_file.write_text(json.dumps({"mqtt_port": 0}))

        mock_thread_class = MagicMock()
        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        with (
            patch("config.runtime.CONFIG_FILE", config_file),
            patch.object(apps_module._state, "thread", None),
            patch("threading.Thread", mock_thread_class),
            patch("atexit.register"),
        ):
            from my_tracks.apps import MyTracksConfig

            app_config = MyTracksConfig("my_tracks", apps_module)
            app_config.ready()

        call_kwargs = mock_thread_class.call_args[1]
        assert_that(call_kwargs["args"], is_(equal_to((0,))))
        mock_thread_instance.start.assert_called_once()


class TestStopMqttBroker:
    """Tests for _stop_mqtt_broker atexit handler."""

    def test_stops_running_broker(self) -> None:
        """Stops a running broker and joins the thread."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        mock_broker.is_running = True
        # Use MagicMock (not AsyncMock) for stop — the coroutine is fed to
        # the mocked run_coroutine_threadsafe, so we don't need a real coroutine.

        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_loop.is_closed.return_value = False
        mock_loop.call_soon_threadsafe = MagicMock()

        mock_thread = MagicMock()

        with (
            patch("asyncio.run_coroutine_threadsafe", return_value=mock_future) as mock_rct,
            patch.object(apps_module._state, "broker", mock_broker),
            patch.object(apps_module._state, "loop", mock_loop),
            patch.object(apps_module._state, "thread", mock_thread),
        ):
            from my_tracks.apps import _stop_mqtt_broker

            _stop_mqtt_broker()

        mock_rct.assert_called_once()
        mock_future.result.assert_called_once_with(timeout=5)
        mock_loop.call_soon_threadsafe.assert_called_once_with(mock_loop.stop)
        mock_thread.join.assert_called_once_with(timeout=5)

    def test_handles_stop_timeout(self) -> None:
        """Logs warning when broker stop times out."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        mock_broker.is_running = True

        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.result.side_effect = TimeoutError("stop timed out")
        mock_loop.is_closed.return_value = False
        mock_loop.call_soon_threadsafe = MagicMock()

        mock_thread = MagicMock()

        with (
            patch("asyncio.run_coroutine_threadsafe", return_value=mock_future),
            patch.object(apps_module._state, "broker", mock_broker),
            patch.object(apps_module._state, "loop", mock_loop),
            patch.object(apps_module._state, "thread", mock_thread),
            patch("my_tracks.apps.logger") as mock_logger,
        ):
            from my_tracks.apps import _stop_mqtt_broker

            _stop_mqtt_broker()

        mock_logger.warning.assert_called_once_with("Timeout stopping MQTT broker")
        # Should still stop the loop and join the thread
        mock_loop.call_soon_threadsafe.assert_called_once_with(mock_loop.stop)
        mock_thread.join.assert_called_once_with(timeout=5)

    def test_noop_when_no_broker(self) -> None:
        """Does nothing when broker is None."""
        import my_tracks.apps as apps_module

        with (
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
            patch.object(apps_module._state, "thread", None),
        ):
            from my_tracks.apps import _stop_mqtt_broker

            # Should not raise
            _stop_mqtt_broker()


class TestRunMqttBroker:
    """Tests for _run_mqtt_broker thread function."""

    def test_creates_broker_and_starts(self) -> None:
        """Creates broker, starts it, and runs until is_running becomes False."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        mock_broker.actual_mqtt_port = 1883
        call_order: list[str] = []

        # Track is_running: True until start completes, then False after one sleep
        sleep_count = 0

        async def mock_start() -> None:
            call_order.append("start")

        async def mock_sleep(seconds: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            call_order.append("sleep")
            # After first sleep, mark broker as stopped
            mock_broker.is_running = False

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch("my_tracks.mqtt.broker.MQTTBroker", return_value=mock_broker),
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(1883)

        assert_that(call_order, is_(equal_to(["start", "sleep"])))
        assert_that(sleep_count, is_(equal_to(1)))

    def test_updates_runtime_config_for_os_allocated_port(self) -> None:
        """Updates runtime config when OS allocates a different port."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        mock_broker.actual_mqtt_port = 54321  # OS-allocated

        async def mock_start() -> None:
            pass

        async def mock_sleep(seconds: float) -> None:
            mock_broker.is_running = False

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch("my_tracks.mqtt.broker.MQTTBroker", return_value=mock_broker),
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch("config.runtime.update_runtime_config") as mock_update,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(0)

        mock_update.assert_called_once_with("actual_mqtt_port", 54321)

    def test_handles_broker_exception(self) -> None:
        """Logs exception if broker startup fails."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()

        async def mock_start() -> None:
            raise ConnectionError("Port in use")

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch("my_tracks.mqtt.broker.MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(1883)

        mock_logger.exception.assert_called_once_with("MQTT broker error")

    def test_event_loop_stopped_during_shutdown_logs_debug(self) -> None:
        """RuntimeError during shutdown should be logged at DEBUG, not ERROR."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()

        async def mock_start() -> None:
            raise RuntimeError("Event loop stopped before Future completed.")

        mock_broker.start = mock_start
        mock_broker.is_running = True

        # Simulate _stop_mqtt_broker having set the flag
        shutdown_event = threading.Event()
        shutdown_event.set()

        with (
            patch("my_tracks.mqtt.broker.MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
            patch.object(apps_module._state, "shutting_down", shutdown_event),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(1883)

        mock_logger.debug.assert_any_call(
            "MQTT broker event loop stopped (normal shutdown)"
        )
        mock_logger.exception.assert_not_called()

    def test_runtime_error_without_shutdown_logs_exception(self) -> None:
        """RuntimeError when NOT shutting down should log at ERROR."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()

        async def mock_start() -> None:
            raise RuntimeError("Event loop stopped before Future completed.")

        mock_broker.start = mock_start
        mock_broker.is_running = True

        # _shutting_down is NOT set — this is unexpected
        shutdown_event = threading.Event()

        with (
            patch("my_tracks.mqtt.broker.MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
            patch.object(apps_module._state, "shutting_down", shutdown_event),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(1883)

        mock_logger.exception.assert_called_once_with(
            "MQTT broker runtime error"
        )


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

    @pytest.mark.asyncio
    async def test_installs_event_loop_exception_handler(self) -> None:
        """First call installs a custom exception handler on the event loop."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock()
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()
        try:
            await middleware(scope, receive, send)
            handler = loop.get_exception_handler()
            assert_that(handler is not None, is_(True))
        finally:
            loop.set_exception_handler(original_handler)

    @pytest.mark.asyncio
    async def test_exception_handler_suppresses_cancelled_error(self) -> None:
        """Custom exception handler silently drops CancelledError."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock()
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()
        try:
            await middleware(scope, receive, send)
            handler = loop.get_exception_handler()

            # Simulate the event loop calling our handler with a CancelledError
            ctx: dict[str, Any] = {
                "message": "CancelledError exception in shielded future",
                "exception": asyncio.CancelledError(),
                "future": asyncio.Future(),
            }
            # Should not raise or call default handler
            with patch("config.asgi.logger") as mock_logger:
                assert handler is not None
                handler(loop, ctx)
                mock_logger.debug.assert_called_once()
        finally:
            loop.set_exception_handler(original_handler)

    @pytest.mark.asyncio
    async def test_exception_handler_passes_through_other_errors(self) -> None:
        """Custom exception handler forwards non-CancelledError to default."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock()
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()

        # Install a mock as the "previous" handler BEFORE the middleware
        # captures it, so we can verify it's called for non-CancelledError
        mock_fallback = MagicMock()
        loop.set_exception_handler(mock_fallback)
        # Reset so middleware installs its handler fresh
        middleware._handler_installed = False

        try:
            await middleware(scope, receive, send)
            handler = loop.get_exception_handler()

            # Simulate the event loop calling our handler with a RuntimeError
            ctx: dict[str, Any] = {
                "message": "Something went wrong",
                "exception": RuntimeError("real error"),
            }
            assert handler is not None
            handler(loop, ctx)
            mock_fallback.assert_called_once_with(loop, ctx)
        finally:
            loop.set_exception_handler(original_handler)

    @pytest.mark.asyncio
    async def test_exception_handler_uses_default_when_no_existing(self) -> None:
        """When no prior handler exists, falls back to loop.default_exception_handler."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock()
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()

        # Ensure no custom handler is set
        loop.set_exception_handler(None)  # type: ignore[arg-type]
        middleware._handler_installed = False

        try:
            await middleware(scope, receive, send)
            handler = loop.get_exception_handler()

            ctx: dict[str, Any] = {
                "message": "Something went wrong",
                "exception": RuntimeError("real error"),
            }
            assert handler is not None
            # This should call loop.default_exception_handler which logs to stderr
            # We just verify it doesn't raise
            with patch.object(loop, "default_exception_handler") as mock_default:
                handler(loop, ctx)
                mock_default.assert_called_once_with(ctx)
        finally:
            loop.set_exception_handler(original_handler)

    @pytest.mark.asyncio
    async def test_exception_handler_installed_only_once(self) -> None:
        """Exception handler is installed on first call only, not on subsequent calls."""
        from config.asgi import ClientDisconnectMiddleware

        inner_app = AsyncMock()
        middleware = ClientDisconnectMiddleware(inner_app)

        scope = {"type": "http", "method": "GET", "path": "/test/"}
        receive = AsyncMock()
        send = AsyncMock()

        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()
        try:
            # First call installs handler
            await middleware(scope, receive, send)
            handler_after_first = loop.get_exception_handler()

            # Second call should NOT reinstall
            await middleware(scope, receive, send)
            handler_after_second = loop.get_exception_handler()

            assert_that(handler_after_first is handler_after_second, is_(True))
        finally:
            loop.set_exception_handler(original_handler)
