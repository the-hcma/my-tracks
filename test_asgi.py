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
from hamcrest import assert_that, contains_string, equal_to, is_, not_none


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


class TestGetMqttTlsPort:
    """Tests for get_mqtt_tls_port function."""

    def test_default_tls_port(self, tmp_path: Path) -> None:
        """Returns 8883 (standard MQTT TLS) when config file doesn't exist."""
        from config.runtime import get_mqtt_tls_port

        with patch("config.runtime.CONFIG_FILE", tmp_path / "nonexistent.json"):
            assert_that(get_mqtt_tls_port(), is_(equal_to(8883)))

    def test_custom_tls_port(self, tmp_path: Path) -> None:
        """Returns custom TLS port from config file."""
        from config.runtime import get_mqtt_tls_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_tls_port": 8883}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_mqtt_tls_port(), is_(equal_to(8883)))

    def test_tls_port_disabled(self, tmp_path: Path) -> None:
        """Returns -1 when TLS is explicitly disabled."""
        from config.runtime import get_mqtt_tls_port

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mqtt_tls_port": -1}))

        with patch("config.runtime.CONFIG_FILE", config_file):
            assert_that(get_mqtt_tls_port(), is_(equal_to(-1)))


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
            patch.object(apps_module, "CONFIG_FILE", config_file),
            patch.object(apps_module, "_is_management_command", return_value=False),
            patch.object(apps_module, "get_mqtt_port", return_value=1883),
            patch.object(apps_module, "get_mqtt_tls_port", return_value=-1),
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
        assert_that(call_kwargs["args"], is_(equal_to((1883, -1))))
        mock_thread_instance.start.assert_called_once()
        mock_atexit.assert_called_once()

    def test_skips_broker_when_no_config_file(self, tmp_path: Path) -> None:
        """Broker does not start when runtime config file is missing."""
        import my_tracks.apps as apps_module

        missing_file = tmp_path / "nonexistent.json"

        with (
            patch.object(apps_module, "CONFIG_FILE", missing_file),
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
            patch.object(apps_module, "CONFIG_FILE", config_file),
            patch.object(apps_module, "_is_management_command", return_value=False),
            patch.object(apps_module, "get_mqtt_port", return_value=-1),
            patch.object(apps_module, "get_mqtt_tls_port", return_value=-1),
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
            patch.object(apps_module, "CONFIG_FILE", config_file),
            patch.object(apps_module, "_is_management_command", return_value=False),
            patch.object(apps_module, "get_mqtt_port", return_value=0),
            patch.object(apps_module, "get_mqtt_tls_port", return_value=-1),
            patch.object(apps_module._state, "thread", None),
            patch("threading.Thread", mock_thread_class),
            patch("atexit.register"),
        ):
            from my_tracks.apps import MyTracksConfig

            app_config = MyTracksConfig("my_tracks", apps_module)
            app_config.ready()

        call_kwargs = mock_thread_class.call_args[1]
        assert_that(call_kwargs["args"], is_(equal_to((0, -1))))
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
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
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
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch.object(apps_module, "update_runtime_config") as mock_update,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(0)

        mock_update.assert_called_once_with("actual_mqtt_port", 54321)

    def test_handles_broker_exception(self) -> None:
        """Generic exception during startup logs critical and exits."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()

        async def mock_start() -> None:
            raise ConnectionError("Port in use")

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch("my_tracks.apps.os._exit") as mock_exit,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(1883)

        mock_logger.critical.assert_any_call("MQTT broker startup failed unexpectedly")
        mock_exit.assert_called_once_with(1)

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
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
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
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
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


class TestIsManagementCommand:
    """Tests for _is_management_command detection.

    IMPORTANT: Daphne/uvicorn argv[0] is the binary path, argv[1] is a flag
    (e.g. "-b"), NOT the binary name. Tests MUST use realistic argv from the
    actual server startup script (my-tracks-server) to prevent regressions.
    """

    # --- Realistic argv from my-tracks-server ---
    # daphne -b 0.0.0.0 -p 8080 --verbosity 0 config.asgi:application
    REAL_DAPHNE_ARGV = [
        ".venv/bin/daphne", "-b", "0.0.0.0", "-p", "8080",
        "--verbosity", "0", "config.asgi:application",
    ]
    REAL_UVICORN_ARGV = [
        ".venv/bin/uvicorn", "config.asgi:application",
        "--host", "0.0.0.0", "--port", "8080",
    ]

    def test_returns_true_for_createsuperuser(self) -> None:
        """Management commands like createsuperuser are detected."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = ["manage.py", "createsuperuser"]
            assert_that(_is_management_command(), is_(True))

    def test_returns_true_for_migrate(self) -> None:
        """The migrate command is detected as a management command."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = ["manage.py", "migrate"]
            assert_that(_is_management_command(), is_(True))

    def test_returns_true_for_makemigrations(self) -> None:
        """The makemigrations command is detected."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = ["manage.py", "makemigrations"]
            assert_that(_is_management_command(), is_(True))

    def test_returns_true_for_shell(self) -> None:
        """The shell command is detected as a management command."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = ["manage.py", "shell"]
            assert_that(_is_management_command(), is_(True))

    def test_returns_false_for_runserver(self) -> None:
        """The runserver command is not considered a management command."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = ["manage.py", "runserver"]
            assert_that(_is_management_command(), is_(False))

    def test_returns_false_for_real_daphne_argv(self) -> None:
        """Daphne detected via argv[0] binary name with real server argv."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = self.REAL_DAPHNE_ARGV
            assert_that(_is_management_command(), is_(False))

    def test_returns_false_for_real_uvicorn_argv(self) -> None:
        """Uvicorn detected via argv[0] binary name with real server argv."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = self.REAL_UVICORN_ARGV
            assert_that(_is_management_command(), is_(False))

    def test_returns_false_when_no_args(self) -> None:
        """Returns False when sys.argv has no command argument."""
        from my_tracks.apps import _is_management_command

        with patch("my_tracks.apps.sys") as mock_sys:
            mock_sys.argv = ["manage.py"]
            assert_that(_is_management_command(), is_(False))

    def test_daphne_argv1_is_a_flag_not_binary_name(self) -> None:
        """Guard: real daphne argv[1] is a flag, NOT 'daphne'.

        This test exists to prevent the original bug where detection relied
        on argv[1] containing the server name. Daphne puts flags in argv[1].
        """
        assert_that(
            self.REAL_DAPHNE_ARGV[1], is_(equal_to("-b")),
        )

    def test_uvicorn_argv1_is_module_not_binary_name(self) -> None:
        """Guard: real uvicorn argv[1] is the ASGI module, NOT 'uvicorn'."""
        assert_that(
            self.REAL_UVICORN_ARGV[1], is_(equal_to("config.asgi:application")),
        )


class TestSkipBrokerForManagementCommand:
    """Tests for skipping broker startup during management commands."""

    def test_skips_broker_for_management_command(self, tmp_path: Path) -> None:
        """Broker does not start when running a management command."""
        import my_tracks.apps as apps_module

        config_file = tmp_path / ".runtime-config.json"
        config_file.write_text(json.dumps({"mqtt_port": 0}))

        with (
            patch.object(apps_module, "CONFIG_FILE", config_file),
            patch.object(apps_module, "_is_management_command", return_value=True),
            patch("threading.Thread") as mock_thread_class,
        ):
            from my_tracks.apps import MyTracksConfig

            app_config = MyTracksConfig("my_tracks", apps_module)
            app_config.ready()

        mock_thread_class.assert_not_called()


class TestBrokerErrorHandling:
    """Tests for fatal BrokerError handling in _run_mqtt_broker."""

    def test_address_in_use_logs_critical_and_exits(self) -> None:
        """BrokerError wrapping errno 48 (macOS) logs critical and exits."""
        from amqtt.errors import BrokerError

        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        os_error = OSError(48, "Address already in use")

        async def mock_start() -> None:
            raise BrokerError("Broker can't be started") from os_error

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch("my_tracks.apps.os._exit") as mock_exit,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(0)

        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args[0][0]
        assert_that(call_args, contains_string("already in use"))
        mock_exit.assert_called_once_with(1)

    def test_address_in_use_errno_98_logs_critical_and_exits(self) -> None:
        """BrokerError wrapping errno 98 (Linux) logs critical and exits."""
        from amqtt.errors import BrokerError

        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        os_error = OSError(98, "Address already in use")

        async def mock_start() -> None:
            raise BrokerError("Broker can't be started") from os_error

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch("my_tracks.apps.os._exit") as mock_exit,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(0)

        mock_logger.critical.assert_called_once()
        mock_exit.assert_called_once_with(1)

    def test_other_broker_error_logs_critical_and_exits(self) -> None:
        """BrokerError without address-in-use cause logs critical and exits."""
        from amqtt.errors import BrokerError

        import my_tracks.apps as apps_module

        mock_broker = MagicMock()

        async def mock_start() -> None:
            raise BrokerError("Some other broker issue")

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker),
            patch("my_tracks.apps.logger") as mock_logger,
            patch("my_tracks.apps.os._exit") as mock_exit,
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            from my_tracks.apps import _run_mqtt_broker

            _run_mqtt_broker(0)

        mock_logger.critical.assert_called()
        mock_exit.assert_called_once_with(1)


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
                assert_that(handler, is_(not_none()))
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
            assert_that(handler, is_(not_none()))
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
            assert_that(handler, is_(not_none()))
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


class TestLoadTlsConfig:
    """Tests for _load_tls_config: TLS cert loading from database."""

    def test_returns_none_when_no_server_cert(self) -> None:
        """No active server cert → returns None, warns, no cert info logged."""
        import my_tracks.apps as apps_module

        mock_server_cls = MagicMock()
        mock_server_cls.objects.filter.return_value.first.return_value = None

        with (
            patch.object(apps_module, "logger") as mock_log,
            patch("my_tracks.models.ServerCertificate", mock_server_cls),
        ):
            result = apps_module._load_tls_config()

        assert_that(result, is_(None))
        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0]
        assert_that(warning_msg, contains_string("no active server certificate"))
        mock_log.info.assert_not_called()

    def test_returns_none_when_no_ca(self) -> None:
        """Server cert exists but no active CA → returns None, warns."""
        import my_tracks.apps as apps_module

        mock_server_cls = MagicMock()
        mock_server_cls.objects.filter.return_value.first.return_value = MagicMock()

        mock_ca_cls = MagicMock()
        mock_ca_cls.objects.filter.return_value.first.return_value = None

        with (
            patch.object(apps_module, "logger") as mock_log,
            patch("my_tracks.models.ServerCertificate", mock_server_cls),
            patch("my_tracks.models.CertificateAuthority", mock_ca_cls),
        ):
            result = apps_module._load_tls_config()

        assert_that(result, is_(None))
        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0]
        assert_that(warning_msg, contains_string("no active CA"))

    def test_returns_tls_config_and_logs_cert_info(self) -> None:
        """Active server cert + CA → returns TLSConfig, calls _log_cert_info."""
        import my_tracks.apps as apps_module
        from my_tracks.pki import (encrypt_private_key,
                                   generate_ca_certificate,
                                   generate_server_certificate)

        ca_pem, ca_key = generate_ca_certificate(
            common_name="Test CA", key_size=2048,
        )
        srv_pem, srv_key = generate_server_certificate(
            ca_pem, ca_key, common_name="test-srv",
            san_entries=["test-srv"], key_size=2048,
        )

        mock_server_cert = MagicMock()
        mock_server_cert.certificate_pem = srv_pem.decode("utf-8")
        mock_server_cert.encrypted_private_key = encrypt_private_key(srv_key)

        mock_ca = MagicMock()
        mock_ca.certificate_pem = ca_pem.decode("utf-8")
        mock_ca.encrypted_private_key = encrypt_private_key(ca_key)

        mock_server_cls = MagicMock()
        mock_server_cls.objects.filter.return_value.first.return_value = mock_server_cert

        mock_ca_cls = MagicMock()
        mock_ca_cls.objects.filter.return_value.first.return_value = mock_ca

        mock_client_cls = MagicMock()
        mock_client_cls.objects.filter.return_value.values_list.return_value = []

        with (
            patch("my_tracks.models.ServerCertificate", mock_server_cls),
            patch("my_tracks.models.CertificateAuthority", mock_ca_cls),
            patch("my_tracks.models.ClientCertificate", mock_client_cls),
            patch.object(apps_module, "_log_cert_info") as mock_cert_log,
        ):
            result = apps_module._load_tls_config()

        assert_that(result, is_(not_none()))
        mock_cert_log.assert_called_once_with(srv_pem, ca_pem)
        assert_that(result.server_cert_pem, equal_to(srv_pem))
        assert_that(result.ca_cert_pem, equal_to(ca_pem))


class TestRunMqttBrokerTlsBehavior:
    """Tests for TLS-specific behavior in _run_mqtt_broker."""

    def test_tls_disabled_when_no_cert(self) -> None:
        """TLS port requested but no cert → TLS port set to -1, broker created without TLS."""
        import my_tracks.apps as apps_module

        mock_broker = MagicMock()
        mock_broker.actual_mqtt_port = 1883

        async def mock_start() -> None:
            pass

        async def mock_sleep(seconds: float) -> None:
            mock_broker.is_running = False

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker) as mock_cls,
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch.object(apps_module, "_load_tls_config", return_value=None),
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            apps_module._run_mqtt_broker(1883, mqtt_tls_port=8883)

        call_kwargs = mock_cls.call_args
        assert_that(call_kwargs.kwargs.get("mqtt_tls_port", call_kwargs[1].get("mqtt_tls_port", -99)),
                    equal_to(-1))
        assert_that(call_kwargs.kwargs.get("tls_config", call_kwargs[1].get("tls_config")),
                    is_(None))

    def test_tls_enabled_when_cert_exists(self) -> None:
        """TLS port requested with valid cert → broker created with TLS config."""
        import my_tracks.apps as apps_module

        mock_tls_config = MagicMock()
        mock_broker = MagicMock()
        mock_broker.actual_mqtt_port = 1883

        async def mock_start() -> None:
            pass

        async def mock_sleep(seconds: float) -> None:
            mock_broker.is_running = False

        mock_broker.start = mock_start
        mock_broker.is_running = True

        with (
            patch.object(apps_module, "MQTTBroker", return_value=mock_broker) as mock_cls,
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch.object(apps_module, "_load_tls_config", return_value=mock_tls_config),
            patch.object(apps_module._state, "broker", None),
            patch.object(apps_module._state, "loop", None),
        ):
            apps_module._run_mqtt_broker(1883, mqtt_tls_port=8883)

        call_kwargs = mock_cls.call_args
        assert_that(call_kwargs.kwargs.get("mqtt_tls_port", call_kwargs[1].get("mqtt_tls_port", -99)),
                    equal_to(8883))
        assert_that(call_kwargs.kwargs.get("tls_config", call_kwargs[1].get("tls_config")),
                    is_(mock_tls_config))


class TestLogCertInfo:
    """Tests for _log_cert_info startup logging."""

    def test_logs_cert_details(self) -> None:
        """Should log CN, CA, expiry, and fingerprint at INFO level."""
        import my_tracks.apps as apps_module
        from my_tracks.pki import (generate_ca_certificate,
                                   generate_server_certificate)

        ca_pem, ca_key = generate_ca_certificate(
            common_name="Log Test CA", key_size=2048,
        )
        srv_pem, _ = generate_server_certificate(
            ca_pem, ca_key, common_name="myhost",
            san_entries=["myhost"], key_size=2048,
        )

        with patch.object(apps_module, "logger") as mock_log:
            apps_module._log_cert_info(srv_pem, ca_pem)

        mock_log.info.assert_called_once()
        msg = mock_log.info.call_args[0][0] % mock_log.info.call_args[0][1:]
        assert_that(msg, contains_string("myhost"))
        assert_that(msg, contains_string("Log Test CA"))
        assert_that(msg, contains_string("fingerprint="))
        mock_log.warning.assert_not_called()

    def test_warns_when_expiry_near(self) -> None:
        """Should emit WARNING when cert expires within 30 days."""
        import my_tracks.apps as apps_module
        from my_tracks.pki import (generate_ca_certificate,
                                   generate_server_certificate)

        ca_pem, ca_key = generate_ca_certificate(
            common_name="Expiry CA", key_size=2048,
        )
        srv_pem, _ = generate_server_certificate(
            ca_pem, ca_key, common_name="expiring",
            san_entries=["expiring"], validity_days=15, key_size=2048,
        )

        with patch.object(apps_module, "logger") as mock_log:
            apps_module._log_cert_info(srv_pem, ca_pem)

        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0] % mock_log.warning.call_args[0][1:]
        assert_that(warning_msg, contains_string("expires in"))
        assert_that(warning_msg, contains_string("consider renewing"))

    def test_warns_when_cert_already_expired(self) -> None:
        """Should emit WARNING when cert is already expired."""
        from datetime import UTC, datetime, timedelta

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        from cryptography.x509.oid import NameOID

        import my_tracks.apps as apps_module
        from my_tracks.pki import generate_ca_certificate

        ca_pem, ca_key_pem = generate_ca_certificate(
            common_name="Expired CA", key_size=2048,
        )
        ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
        if not isinstance(ca_key, RSAPrivateKey):
            raise ValueError("Expected RSA key")
        ca_cert = x509.load_pem_x509_certificate(ca_pem)

        srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expired-host")]))
            .issuer_name(ca_cert.subject)
            .public_key(srv_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=365))
            .not_valid_after(now - timedelta(days=1))
            .sign(ca_key, hashes.SHA256())
        )
        srv_pem = cert.public_bytes(serialization.Encoding.PEM)

        with patch.object(apps_module, "logger") as mock_log:
            apps_module._log_cert_info(srv_pem, ca_pem)

        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0] % mock_log.warning.call_args[0][1:]
        assert_that(warning_msg, contains_string("EXPIRED"))
        assert_that(warning_msg, contains_string("clients will reject"))

    def test_no_warning_when_expiry_far(self) -> None:
        """Should not emit WARNING when cert expires in more than 30 days."""
        import my_tracks.apps as apps_module
        from my_tracks.pki import (generate_ca_certificate,
                                   generate_server_certificate)

        ca_pem, ca_key = generate_ca_certificate(
            common_name="OK CA", key_size=2048,
        )
        srv_pem, _ = generate_server_certificate(
            ca_pem, ca_key, common_name="healthy",
            san_entries=["healthy"], validity_days=365, key_size=2048,
        )

        with patch.object(apps_module, "logger") as mock_log:
            apps_module._log_cert_info(srv_pem, ca_pem)

        mock_log.info.assert_called_once()
        mock_log.warning.assert_not_called()
