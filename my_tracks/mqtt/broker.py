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
import ssl
import tempfile
from dataclasses import dataclass
from typing import Any

from amqtt.broker import Broker

logger = logging.getLogger(__name__)

# Shutdown polling interval in seconds
# Lower value = faster shutdown response but more CPU cycles
_SHUTDOWN_POLL_INTERVAL_SECONDS = 0.1


@dataclass
class TLSConfig:
    """TLS configuration for the MQTT broker.

    Holds PEM-encoded certificates and keys needed to set up
    a TLS listener with optional client certificate verification.
    """

    server_cert_pem: bytes
    server_key_pem: bytes
    ca_cert_pem: bytes
    crl_pem: bytes | None = None


class _CRLBroker(Broker):
    """Broker subclass that enforces mutual TLS with optional CRL checking.

    amqtt's ``_create_ssl_context`` hardcodes ``CERT_OPTIONAL``, which
    with TLS 1.3 silently accepts invalid client certificates.  This
    override switches to ``CERT_REQUIRED`` so that bad, expired, or
    untrusted client certs cause an immediate handshake failure.

    When ``_crl_pem`` is set, the override also enables leaf-level CRL
    revocation checking so that revoked certs are rejected.
    """

    _crl_pem: bytes | None = None

    @staticmethod
    def _create_ssl_context(listener: Any) -> ssl.SSLContext:
        ctx = Broker._create_ssl_context(listener)
        ctx.verify_mode = ssl.CERT_REQUIRED
        # TLS 1.3 defers client cert verification to post-handshake,
        # which asyncio.start_server does not propagate reliably.
        # Cap at TLS 1.2 so CERT_REQUIRED is enforced during the
        # initial handshake.  TLS 1.2 remains secure and is the
        # norm for MQTT / IoT devices.
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        if _CRLBroker._crl_pem is not None:
            ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
            logger.info("CRL enforcement enabled for revocation checking")
        return ctx


def get_default_config(
    mqtt_port: int = 1883,
    mqtt_tls_port: int = -1,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
    tls_cafile: str | None = None,
    allow_anonymous: bool = True,
    use_django_auth: bool = False,
    use_owntracks_handler: bool = True,
) -> dict[str, Any]:
    """
    Get the default MQTT broker configuration.

    Args:
        mqtt_port: TCP port for MQTT connections (default: 1883)
        mqtt_tls_port: TCP port for MQTT over TLS (default: -1 = disabled)
        tls_certfile: Path to server certificate PEM file (required when TLS enabled)
        tls_keyfile: Path to server private key PEM file (required when TLS enabled)
        tls_cafile: Path to CA certificate PEM file for client cert verification
        allow_anonymous: Allow anonymous connections (default: True for initial setup)
        use_django_auth: Use Django authentication plugin (default: False)
        use_owntracks_handler: Use OwnTracks message handler plugin (default: True)

    Returns:
        Configuration dictionary for amqtt Broker

    Note:
        When using the ``plugins`` dict config style, amqtt ignores
        the top-level ``auth`` section.  Authentication must be handled
        by including an auth plugin directly in the ``plugins`` dict
        (e.g. ``AnonymousAuthPlugin`` or ``DjangoAuthPlugin``).
    """
    plugins: dict[str, dict[str, Any]] = {
        "amqtt.plugins.sys.broker.BrokerSysPlugin": {},
    }

    if use_django_auth and not allow_anonymous:
        plugins["my_tracks.mqtt.auth.DjangoAuthPlugin"] = {}
    else:
        plugins["amqtt.plugins.authentication.AnonymousAuthPlugin"] = {
            "allow_anonymous": allow_anonymous,
        }

    if use_owntracks_handler:
        plugins["my_tracks.mqtt.plugin.OwnTracksPlugin"] = {}

    listeners: dict[str, dict[str, Any]] = {
        "default": {
            "type": "tcp",
            "bind": f"0.0.0.0:{mqtt_port}",
            "max_connections": 100,
        },
    }

    if mqtt_tls_port >= 0 and tls_certfile and tls_keyfile:
        tls_listener: dict[str, Any] = {
            "type": "tcp",
            "bind": f"0.0.0.0:{mqtt_tls_port}",
            "ssl": True,
            "certfile": tls_certfile,
            "keyfile": tls_keyfile,
            "max_connections": 100,
        }
        if tls_cafile:
            tls_listener["cafile"] = tls_cafile
        listeners["mqtt-tls"] = tls_listener

    return {
        "listeners": listeners,
        "sys_interval": 30,
        "plugins": plugins,
    }


class MQTTBroker:
    """
    MQTT Broker wrapper for OwnTracks.

    This class manages the amqtt broker lifecycle and provides
    integration points for the Django application.

    Example:
        broker = MQTTBroker(mqtt_port=1883)
        await broker.start()
        # ... broker is running ...
        await broker.stop()
    """

    def __init__(
        self,
        mqtt_port: int = 1883,
        mqtt_tls_port: int = -1,
        tls_config: TLSConfig | None = None,
        allow_anonymous: bool = True,
        use_django_auth: bool = False,
        use_owntracks_handler: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the MQTT broker.

        Args:
            mqtt_port: TCP port for MQTT connections
            mqtt_tls_port: TCP port for MQTT over TLS (-1 = disabled)
            tls_config: TLS certificate configuration (required when mqtt_tls_port >= 0)
            allow_anonymous: Allow anonymous connections
            use_django_auth: Use Django authentication plugin for user auth
            use_owntracks_handler: Use OwnTracks message handler plugin (requires Django)
            config: Custom configuration (overrides defaults if provided)
        """
        self.mqtt_port = mqtt_port
        self.mqtt_tls_port = mqtt_tls_port
        self.tls_config = tls_config
        self.allow_anonymous = allow_anonymous
        self.use_django_auth = use_django_auth
        self.use_owntracks_handler = use_owntracks_handler

        self._tls_temp_files: list[tempfile.NamedTemporaryFile] = []  # type: ignore[type-arg]
        self._tls_certfile: str | None = None
        self._tls_keyfile: str | None = None
        self._tls_cafile: str | None = None

        if tls_config and mqtt_tls_port >= 0:
            self._setup_tls_files(tls_config)

        if config is not None:
            self._config = config
        else:
            self._config = get_default_config(
                mqtt_port=mqtt_port,
                mqtt_tls_port=mqtt_tls_port,
                tls_certfile=self._tls_certfile,
                tls_keyfile=self._tls_keyfile,
                tls_cafile=self._tls_cafile,
                allow_anonymous=allow_anonymous,
                use_django_auth=use_django_auth,
                use_owntracks_handler=use_owntracks_handler,
            )

        self._broker: Broker | None = None
        self._running = False
        self._actual_mqtt_port: int | None = None
        self._actual_tls_port: int | None = None

    def _setup_tls_files(self, tls_config: TLSConfig) -> None:
        """Write TLS certificates to temporary files for amqtt.

        amqtt requires file paths, not in-memory PEM data.
        Files are cleaned up when the broker stops.
        """
        cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        cert_file.write(tls_config.server_cert_pem)
        cert_file.flush()
        self._tls_temp_files.append(cert_file)
        self._tls_certfile = cert_file.name

        key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        key_file.write(tls_config.server_key_pem)
        key_file.flush()
        self._tls_temp_files.append(key_file)
        self._tls_keyfile = key_file.name

        ca_data = tls_config.ca_cert_pem
        if tls_config.crl_pem:
            ca_data = ca_data + b"\n" + tls_config.crl_pem
        ca_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        ca_file.write(ca_data)
        ca_file.flush()
        self._tls_temp_files.append(ca_file)
        self._tls_cafile = ca_file.name

    def _cleanup_tls_files(self) -> None:
        """Remove temporary TLS certificate files."""
        import os as _os

        for f in self._tls_temp_files:
            try:
                _os.unlink(f.name)
            except OSError:
                pass
        self._tls_temp_files.clear()

    @property
    def is_running(self) -> bool:
        """Check if the broker is running."""
        return self._running

    @property
    def config(self) -> dict[str, Any]:
        """Get the broker configuration."""
        return self._config

    @property
    def amqtt_broker(self) -> Broker | None:
        """Return the underlying amqtt Broker instance for internal publishing."""
        return self._broker

    def _discover_port(self, listener_name: str) -> int | None:
        """Discover the actual port a listener is bound to.

        Args:
            listener_name: Name of the listener in the broker config
                (e.g. ``"default"`` for TCP, ``"mqtt-tls"`` for TLS).

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
    def actual_tls_port(self) -> int | None:
        """
        Get the actual MQTT TLS port after startup.

        Returns None if TLS is disabled, broker hasn't started, or
        port discovery failed.
        """
        if self.mqtt_tls_port < 0:
            return None
        if self._actual_tls_port is not None:
            return self._actual_tls_port
        if self._broker is None:
            return None

        port = self._discover_port("mqtt-tls")
        if port is not None:
            self._actual_tls_port = port
            return port

        return self.mqtt_tls_port

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

        ports_msg = f"port {self.mqtt_port} (TCP)"
        if self.mqtt_tls_port >= 0:
            ports_msg += f" and {self.mqtt_tls_port} (TLS)"
        logger.info("Starting MQTT broker on %s", ports_msg)

        if self.tls_config:
            _CRLBroker._crl_pem = self.tls_config.crl_pem
            self._broker = _CRLBroker(self._config)
        else:
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
        self._cleanup_tls_files()
        _CRLBroker._crl_pem = None

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
                await asyncio.sleep(_SHUTDOWN_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            if self._running:
                await self.stop()
            raise


async def create_and_start_broker(
    mqtt_port: int = 1883,
    allow_anonymous: bool = True,
) -> MQTTBroker:
    """
    Create and start an MQTT broker.

    Convenience function for creating and starting a broker in one call.

    Args:
        mqtt_port: TCP port for MQTT connections
        allow_anonymous: Allow anonymous connections

    Returns:
        Running MQTTBroker instance
    """
    broker = MQTTBroker(
        mqtt_port=mqtt_port,
        allow_anonymous=allow_anonymous,
    )
    await broker.start()
    return broker
