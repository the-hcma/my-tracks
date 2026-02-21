"""
MQTT Broker for OwnTracks.

This module provides an embedded MQTT broker using amqtt that can run
alongside the Django/Daphne server in the same asyncio event loop.

The broker handles OwnTracks MQTT protocol for:
- Location updates from devices
- Bidirectional communication (commands to devices)
- Last Will & Testament (device offline detection)
"""

import asyncio
import logging
from typing import Any

from amqtt.broker import Broker

logger = logging.getLogger(__name__)


def get_default_config(
    mqtt_port: int = 1883,
    mqtt_ws_port: int = 8083,
    allow_anonymous: bool = True,
    use_django_auth: bool = False,
    use_owntracks_handler: bool = True,
) -> dict[str, Any]:
    """
    Get the default MQTT broker configuration.

    Args:
        mqtt_port: TCP port for MQTT connections (default: 1883)
        mqtt_ws_port: WebSocket port for MQTT over WS (default: 8083)
        allow_anonymous: Allow anonymous connections (default: True for initial setup)
        use_django_auth: Use Django authentication plugin (default: False)
        use_owntracks_handler: Use OwnTracks message handler plugin (default: True)

    Returns:
        Configuration dictionary for amqtt Broker
    """
    plugins = [
        "amqtt.plugins.sys.broker.BrokerSysPlugin",
    ]

    # Add OwnTracks handler plugin if requested (requires Django)
    if use_owntracks_handler:
        plugins.append("my_tracks.mqtt.plugin.OwnTracksPlugin")

    auth_config: dict[str, Any] = {
        "allow-anonymous": allow_anonymous,
    }

    if use_django_auth:
        plugins.append("my_tracks.mqtt.auth.DjangoAuthPlugin")
        # When using Django auth, anonymous should typically be disabled
        if not allow_anonymous:
            auth_config["plugins"] = ["my_tracks.mqtt.auth.DjangoAuthPlugin"]

    return {
        "listeners": {
            "default": {
                "type": "tcp",
                "bind": f"0.0.0.0:{mqtt_port}",
                "max_connections": 100,
            },
            "ws-mqtt": {
                "type": "ws",
                "bind": f"0.0.0.0:{mqtt_ws_port}",
                "max_connections": 50,
            },
        },
        "sys_interval": 30,  # $SYS topic update interval in seconds
        "auth": auth_config,
        "plugins": plugins,
    }


class MQTTBroker:
    """
    MQTT Broker wrapper for OwnTracks.

    This class manages the amqtt broker lifecycle and provides
    integration points for the Django application.

    Example:
        broker = MQTTBroker(mqtt_port=1883, mqtt_ws_port=8083)
        await broker.start()
        # ... broker is running ...
        await broker.stop()
    """

    def __init__(
        self,
        mqtt_port: int = 1883,
        mqtt_ws_port: int = 8083,
        allow_anonymous: bool = True,
        use_django_auth: bool = False,
        use_owntracks_handler: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the MQTT broker.

        Args:
            mqtt_port: TCP port for MQTT connections
            mqtt_ws_port: WebSocket port for MQTT over WS
            allow_anonymous: Allow anonymous connections
            use_django_auth: Use Django authentication plugin for user auth
            use_owntracks_handler: Use OwnTracks message handler plugin (requires Django)
            config: Custom configuration (overrides defaults if provided)
        """
        self.mqtt_port = mqtt_port
        self.mqtt_ws_port = mqtt_ws_port
        self.allow_anonymous = allow_anonymous
        self.use_django_auth = use_django_auth
        self.use_owntracks_handler = use_owntracks_handler

        if config is not None:
            self._config = config
        else:
            self._config = get_default_config(
                mqtt_port=mqtt_port,
                mqtt_ws_port=mqtt_ws_port,
                allow_anonymous=allow_anonymous,
                use_django_auth=use_django_auth,
                use_owntracks_handler=use_owntracks_handler,
            )

        self._broker: Broker | None = None
        self._running = False
        self._actual_mqtt_port: int | None = None
        self._actual_ws_port: int | None = None

    @property
    def is_running(self) -> bool:
        """Check if the broker is running."""
        return self._running

    @property
    def config(self) -> dict[str, Any]:
        """Get the broker configuration."""
        return self._config

    def _discover_port(self, listener_name: str) -> int | None:
        """Discover the actual port a listener is bound to.

        Args:
            listener_name: Name of the listener in the broker config
                (e.g. ``"default"`` for TCP, ``"ws-mqtt"`` for WebSocket).

        Returns:
            The port number, or ``None`` if the broker hasn't started or
            the listener is not found.
        """
        if self._broker is None:
            return None
        try:
            if hasattr(self._broker, "_servers") and self._broker._servers:
                server = self._broker._servers.get(listener_name)
                if server is not None:
                    instance = getattr(server, "instance", None)
                    if instance is not None and hasattr(instance, "sockets"):
                        for sock in instance.sockets:
                            addr = sock.getsockname()
                            if len(addr) >= 2:
                                return int(addr[1])
        except Exception:
            pass
        return None

    @property
    def actual_mqtt_port(self) -> int | None:
        """
        Get the actual MQTT TCP port after startup.

        This is useful when port 0 was specified to let the OS allocate.
        Returns None if broker hasn't started or port discovery failed.
        """
        if self._actual_mqtt_port is not None:
            return self._actual_mqtt_port
        if self._broker is None:
            return None

        port = self._discover_port("default")
        if port is not None:
            self._actual_mqtt_port = port
            return port

        # Fall back to configured port when running but discovery failed
        return self.mqtt_port

    @property
    def actual_ws_port(self) -> int | None:
        """
        Get the actual MQTT WebSocket port after startup.

        This is useful when port 0 was specified to let the OS allocate.
        Returns None if broker hasn't started or port discovery failed.
        """
        if self._actual_ws_port is not None:
            return self._actual_ws_port
        if self._broker is None:
            return None

        port = self._discover_port("ws-mqtt")
        if port is not None:
            self._actual_ws_port = port
            return port

        # Fall back to configured port when running but discovery failed
        return self.mqtt_ws_port

    async def start(self) -> None:
        """
        Start the MQTT broker.

        This method initializes and starts the amqtt broker.
        It should be called from an asyncio context.

        Raises:
            RuntimeError: If the broker is already running
        """
        if self._running:
            raise RuntimeError("MQTT broker is already running")

        logger.info(
            "Starting MQTT broker on ports %d (TCP) and %d (WebSocket)",
            self.mqtt_port,
            self.mqtt_ws_port,
        )

        self._broker = Broker(self._config)
        await self._broker.start()
        self._running = True

        logger.info("MQTT broker started successfully")

    async def stop(self) -> None:
        """
        Stop the MQTT broker.

        This method gracefully shuts down the broker.

        Raises:
            RuntimeError: If the broker is not running
        """
        if not self._running or self._broker is None:
            raise RuntimeError("MQTT broker is not running")

        logger.info("Stopping MQTT broker...")

        await self._broker.shutdown()
        self._broker = None
        self._running = False

        logger.info("MQTT broker stopped")

    async def run_forever(self) -> None:
        """
        Run the broker until cancelled.

        This is useful for running the broker as a standalone service
        or as a background task in the main event loop.
        """
        if not self._running:
            await self.start()

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            if self._running:
                await self.stop()
            raise


async def create_and_start_broker(
    mqtt_port: int = 1883,
    mqtt_ws_port: int = 8083,
    allow_anonymous: bool = True,
) -> MQTTBroker:
    """
    Create and start an MQTT broker.

    Convenience function for creating and starting a broker in one call.

    Args:
        mqtt_port: TCP port for MQTT connections
        mqtt_ws_port: WebSocket port for MQTT over WS
        allow_anonymous: Allow anonymous connections

    Returns:
        Running MQTTBroker instance
    """
    broker = MQTTBroker(
        mqtt_port=mqtt_port,
        mqtt_ws_port=mqtt_ws_port,
        allow_anonymous=allow_anonymous,
    )
    await broker.start()
    return broker
