"""App configuration for my_tracks application."""

import asyncio
import atexit
import logging
import os
import sys
import threading
from typing import Any

from amqtt.errors import BrokerError
from django.apps import AppConfig

from config.runtime import CONFIG_FILE, get_mqtt_port, update_runtime_config
from my_tracks.mqtt.broker import MQTTBroker

logger = logging.getLogger(__name__)

# Shutdown polling interval in seconds
# Lower value = faster shutdown response but more CPU cycles
_SHUTDOWN_POLL_INTERVAL_SECONDS = 0.1


class _MqttBrokerState:
    """Holder for MQTT broker thread state.

    Encapsulates all mutable state for the broker lifecycle so that
    module-level globals and ``global`` statements are unnecessary.
    """

    def __init__(self) -> None:
        self.broker: Any = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.shutting_down: threading.Event = threading.Event()


_state = _MqttBrokerState()


def _stop_mqtt_broker() -> None:
    """Stop the MQTT broker on process exit."""
    _state.shutting_down.set()

    if _state.broker is not None and _state.loop is not None:
        if _state.broker.is_running:
            future = asyncio.run_coroutine_threadsafe(
                _state.broker.stop(), _state.loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                logger.warning("Timeout stopping MQTT broker")
        if not _state.loop.is_closed():
            _state.loop.call_soon_threadsafe(_state.loop.stop)
        if _state.thread is not None:
            _state.thread.join(timeout=5)


def _run_mqtt_broker(mqtt_port: int) -> None:
    """Run the MQTT broker in a dedicated thread with its own event loop.

    The broker needs its own asyncio event loop because Daphne does not
    support the ASGI lifespan protocol, so we cannot rely on lifespan
    events to start/stop the broker.

    Args:
        mqtt_port: TCP port for MQTT connections (0 = OS allocates)
    """
    _state.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_state.loop)

    # TODO: Decide on authentication strategy for MQTT connections.
    # Currently anonymous access is allowed so the phone can connect
    # without Django user credentials.  Options to evaluate:
    #   1. Keep anonymous (simple, single-user setup)
    #   2. Enable DjangoAuthPlugin with a dedicated MQTT user
    #   3. Token-based auth via a custom plugin
    _state.broker = MQTTBroker(
        mqtt_port=mqtt_port,
        allow_anonymous=True,
        use_django_auth=False,
    )

    async def _start_and_run() -> None:
        assert _state.broker is not None
        await _state.broker.start()

        # If port was 0, discover and publish the actual port
        actual_port = _state.broker.actual_mqtt_port
        if actual_port is not None and actual_port != mqtt_port:
            logger.info(
                "MQTT broker listening on OS-allocated port %d", actual_port
            )
            update_runtime_config("actual_mqtt_port", actual_port)

        logger.info(
            "MQTT broker started on port %d", actual_port or mqtt_port
        )

        # Keep the event loop alive while the broker is running
        while _state.broker.is_running:
            await asyncio.sleep(_SHUTDOWN_POLL_INTERVAL_SECONDS)

    try:
        _state.loop.run_until_complete(_start_and_run())
    except RuntimeError as exc:
        # _stop_mqtt_broker() sets _state.shutting_down before stopping the
        # loop, which causes run_until_complete() to raise:
        #   RuntimeError: Event loop stopped before Future completed.
        # Only treat it as expected when we know shutdown was requested.
        if _state.shutting_down.is_set():
            logger.debug("MQTT broker event loop stopped (normal shutdown)")
        else:
            logger.exception("MQTT broker runtime error")
    except BrokerError as exc:
        cause = exc.__cause__
        if isinstance(cause, OSError) and cause.errno in (48, 98):
            # errno 48 = macOS EADDRINUSE, errno 98 = Linux EADDRINUSE
            logger.critical(
                "MQTT broker port %d already in use — cannot start. "
                "Stop the other process or use --mqtt-port to choose a different port.",
                mqtt_port,
            )
        else:
            logger.critical("MQTT broker failed to start: %s", exc)
        # Fatal: bring down the entire server — a half-running server
        # (HTTP up, MQTT down) would silently drop all location updates.
        os._exit(1)
    except Exception:
        logger.critical("MQTT broker startup failed unexpectedly")
        logger.exception("Details:")
        os._exit(1)
    finally:
        _state.loop.close()


def get_mqtt_broker() -> "MQTTBroker | None":
    """Return the running MQTTBroker instance, or None if not started."""
    return _state.broker


def get_mqtt_event_loop() -> "asyncio.AbstractEventLoop | None":
    """Return the event loop used by the MQTT broker thread."""
    return _state.loop


_ASGI_SERVER_BINARIES = {'daphne', 'uvicorn'}


def _is_management_command() -> bool:
    """Detect if the process is running a management command (not the server).

    Returns True for commands like createsuperuser, migrate, makemigrations, etc.
    Returns False for server processes (runserver, daphne) and unknown contexts.

    Detection strategy:
    - Direct ASGI servers (daphne, uvicorn) appear as sys.argv[0] binary name
    - Django's runserver appears as sys.argv[1] via manage.py
    - If neither matches and there's a command arg, it's a management command
    """
    from pathlib import PurePath

    prog = PurePath(sys.argv[0]).stem
    if prog in _ASGI_SERVER_BINARIES:
        return False
    if len(sys.argv) >= 2 and sys.argv[1] == 'runserver':
        return False
    return len(sys.argv) >= 2


class MyTracksConfig(AppConfig):
    """Configuration for the my_tracks app."""

    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'my_tracks'
    verbose_name: str = 'My Tracks'

    def ready(self) -> None:
        """Start the MQTT broker if enabled in runtime config.

        The broker only starts when:
        1. A runtime config file exists (written by ``my-tracks-server``)
        2. The process is running the server (not a management command)
        """
        if not CONFIG_FILE.exists():
            logger.debug("No runtime config — skipping MQTT broker startup")
            return

        if _is_management_command():
            logger.debug("Management command detected — skipping MQTT broker startup")
            return

        mqtt_port = get_mqtt_port()
        if mqtt_port < 0:
            logger.info("MQTT broker disabled (port=%d)", mqtt_port)
            return

        _state.thread = threading.Thread(
            target=_run_mqtt_broker,
            args=(mqtt_port,),
            daemon=True,
            name="mqtt-broker",
        )
        _state.thread.start()
        atexit.register(_stop_mqtt_broker)
        logger.info("MQTT broker thread started (port=%d)", mqtt_port)
