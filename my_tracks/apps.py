"""App configuration for my_tracks application."""

import asyncio
import atexit
import logging
import threading
from typing import Any

from django.apps import AppConfig

logger = logging.getLogger(__name__)


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
    from config.runtime import update_runtime_config
    from my_tracks.mqtt.broker import MQTTBroker

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
            await asyncio.sleep(1)

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
    except Exception:
        logger.exception("MQTT broker error")
    finally:
        _state.loop.close()


class MyTracksConfig(AppConfig):
    """Configuration for the my_tracks app."""

    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'my_tracks'
    verbose_name: str = 'My Tracks'

    def ready(self) -> None:
        """Start the MQTT broker if enabled in runtime config.

        The broker only starts when a runtime config file exists (written
        by the ``my-tracks-server`` script). This prevents the broker from
        starting during tests or management commands.
        """
        from config.runtime import CONFIG_FILE, get_mqtt_port

        if not CONFIG_FILE.exists():
            logger.debug("No runtime config — skipping MQTT broker startup")
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
