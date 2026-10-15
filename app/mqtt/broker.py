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
import os
import ssl
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amqtt.broker import Broker
from amqtt.contrib.listeners import ReloadableExternalTLSListener
from cryptography import x509

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


def _exception_from_asyncio_context(context: dict[str, Any]) -> BaseException | None:
    """Return the exception from an asyncio handler context, including orphan tasks."""
    exception = context.get("exception")
    if exception is not None:
        return exception
    future = context.get("future")
    if future is None:
        return None
    try:
        if future.cancelled():
            return None
        return future.exception()
    except asyncio.CancelledError:
        return None


def _mqtt_asyncio_exception_handler(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, Any],
    original_handler: Any,
) -> None:
    """Asyncio exception handler for the embedded MQTT broker event loop.

    Intercepts exceptions that otherwise appear only as asyncio ``base_events``
    ERROR lines (TLS handshake failures, ``client_connected_cb`` shutdown
    timeouts, and "Task exception was never retrieved" from QoS 1 publishes).
    """
    message = context.get("message") or ""
    exception = _exception_from_asyncio_context(context)

    if isinstance(exception, (ssl.SSLError, ssl.SSLCertVerificationError, ConnectionResetError)):
        transport = context.get("transport")
        peername = "unknown"
        if transport is not None:
            try:
                peer = transport.get_extra_info("peername")
                if peer:
                    peername = f"{peer[0]}:{peer[1]}"
            except Exception:
                pass
        logger.warning(
            "[mqtt-tls] Handshake failed from %s: %s",
            peername,
            exception,
        )
        return

    if "client_connected_cb" in message:
        if isinstance(exception, TimeoutError):
            logger.warning(
                "[mqtt-tls] Connection closed during SSL shutdown: %s",
                exception,
            )
        elif exception is not None:
            logger.warning(
                "[mqtt-tls] Unhandled client connection callback error: %s",
                exception,
                exc_info=exception,
            )
        else:
            logger.warning("[mqtt-tls] %s", message)
        return

    if isinstance(exception, TimeoutError):
        logger.warning("[mqtt] Asyncio timeout: %s", exception)
        return

    if callable(original_handler):
        original_handler(context)
    else:
        loop.default_exception_handler(context)


def get_default_config(
    mqtt_port: int = 1883,
    allow_anonymous: bool = True,
    use_django_auth: bool = False,
    use_owntracks_handler: bool = True,
) -> dict[str, Any]:
    """
    Get the default MQTT broker configuration.

    Args:
        mqtt_port: TCP port for MQTT connections (default: 1883)
        allow_anonymous: Allow anonymous connections (default: True for initial setup)
        use_django_auth: Use Django authentication plugin (default: False)
        use_owntracks_handler: Use OwnTracks message handler plugin (default: True)

    Returns:
        Configuration dictionary for amqtt Broker

    Note:
        The ``mqtt-tls`` listener is always declared as an ``external`` listener so the
        broker can accept hand-offs from the ``ReloadableExternalTLSListener`` that
        ``MQTTBroker`` starts when TLS is enabled (and can enable TLS later without
        restarting the broker).

        When using the ``plugins`` dict config style, amqtt ignores
        the top-level ``auth`` section.  Authentication must be handled
        by including an auth plugin directly in the ``plugins`` dict
        (e.g. ``AnonymousAuthPlugin`` or ``DjangoAuthPlugin``).
    """
    plugins: dict[str, dict[str, Any]] = {
        "amqtt.plugins.sys.broker.BrokerSysPlugin": {"sys_interval": 30, "qos": 0},
    }

    if use_django_auth and not allow_anonymous:
        plugins["app.mqtt.auth.DjangoAuthPlugin"] = {}
    else:
        plugins["amqtt.plugins.authentication.AnonymousAuthPlugin"] = {
            "allow_anonymous": allow_anonymous,
        }

    if use_owntracks_handler:
        plugins["app.mqtt.plugin.OwnTracksPlugin"] = {}

    listeners: dict[str, dict[str, Any]] = {
        "default": {
            "type": "tcp",
            "bind": f"0.0.0.0:{mqtt_port}",
            "max_connections": 100,
        },
    }

    # The bind value is never opened by amqtt for external listeners; it only has to exist.
    # amqtt does not enforce max_connections for external listeners; _CappedTLSListener does.
    listeners["mqtt-tls"] = {"type": "external", "bind": "0.0.0.0:0"}

    return {
        "listeners": listeners,
        "plugins": plugins,
    }


_TLS_LISTENER_NAME = "mqtt-tls"
_TLS_BIND_HOST = "0.0.0.0"
_TLS_MAX_CONNECTIONS = 100


class _CappedTLSListener(ReloadableExternalTLSListener):
    """Reloadable TLS listener that refuses connections beyond ``max_connections``.

    amqtt applies ``max_connections`` only to listeners it opens itself, so the cap that the
    old in-broker TLS listener had is enforced here for the external one.
    """

    def __init__(self, *, max_connections: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.max_connections = max_connections

    async def _client_connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.active_connection_count >= self.max_connections:
            logger.warning(
                "[mqtt-tls] Connection refused: limit reached (active=%d, max=%d)",
                self.active_connection_count,
                self.max_connections,
            )
            writer.close()
            return
        await super()._client_connected(reader, writer)


def _revoked_serial_numbers(crl_pem: bytes) -> set[int]:
    """Return the serial numbers listed in a PEM-encoded CRL."""
    return {revoked.serial_number for revoked in x509.load_pem_x509_crl(crl_pem)}


def _write_private_pem(directory: Path, name: str, data: bytes) -> str:
    """Write ``data`` to ``directory/name`` readable only by the owner and return the path."""
    path = directory / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return str(path)


def build_server_ssl_context(
    tls_config: TLSConfig,
    sni_callback: Callable[..., None] | None = None,
) -> ssl.SSLContext:
    """Build the mutual-TLS server context for the MQTT TLS listener.

    ``ssl`` can only load a certificate chain and a CRL from files, so the PEM
    material is written to a private temporary directory that is removed before
    this function returns (the context keeps its own copy).

    Client certificates are mandatory.  TLS 1.3 is intentionally excluded: it
    defers client certificate verification to a post-handshake exchange that
    asyncio does not propagate reliably, allowing invalid/expired/revoked certs
    through (cpython#83375, open since 2020).  When the config carries a CRL,
    leaf-level revocation checking is enabled.
    """
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cadata=tls_config.ca_cert_pem.decode("ascii"))
    with tempfile.TemporaryDirectory(prefix="my-tracks-tls-") as tmp:
        directory = Path(tmp)
        ctx.load_cert_chain(
            _write_private_pem(directory, "server.pem", tls_config.server_cert_pem),
            _write_private_pem(directory, "server.key", tls_config.server_key_pem),
        )
        if tls_config.crl_pem:
            ctx.load_verify_locations(cafile=_write_private_pem(directory, "crl.pem", tls_config.crl_pem))
            ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
            logger.info("[mqtt-tls] CRL enforcement enabled for revocation checking")
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    if sni_callback is not None:
        ctx.set_servername_callback(sni_callback)
    return ctx


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
        self.tls_reload_failed = False
        self.allow_anonymous = allow_anonymous
        self.use_django_auth = use_django_auth
        self.use_owntracks_handler = use_owntracks_handler

        if config is not None:
            self._config = config
        else:
            self._config = get_default_config(
                mqtt_port=mqtt_port,
                allow_anonymous=allow_anonymous,
                use_django_auth=use_django_auth,
                use_owntracks_handler=use_owntracks_handler,
            )

        self._broker: Broker | None = None
        self._tls_listener: _CappedTLSListener | None = None
        self._original_exception_handler: Any = None
        self._running = False
        self._actual_mqtt_port: int | None = None
        self._reload_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if the broker wrapper is running."""
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
                (e.g. ``"default"`` for TCP).

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
    def reload_in_progress(self) -> bool:
        """Return True while a TLS hot-reload is running (``tls_reload_failed`` is not meaningful then)."""
        return self._reload_lock.locked()

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

        Returns None if TLS is disabled or the TLS listener is not serving.
        """
        if self.mqtt_tls_port < 0:
            return None
        if self._tls_listener is not None:
            return self._tls_listener.actual_port
        return None

    def _sni_callback(self) -> Callable[..., None] | None:
        """Return amqtt's inbound-SNI capture hook for contexts amqtt does not build itself.

        amqtt only registers it on contexts it creates from listener config; a context handed to
        the external listener has to register it so ``Session.inbound_sni`` and the early
        post-TLS-disconnect diagnostic work.
        """
        if self._broker is None:
            return None
        return self._broker._sni_callback

    async def _start_tls_listener(self, tls_config: TLSConfig, mqtt_tls_port: int) -> _CappedTLSListener:
        """Create and start the reloadable TLS listener that hands connections to the broker.

        The caller owns the returned listener: nothing is stored on ``self`` so a failed or
        superseded start cannot leave a half-registered listener behind.
        """
        if self._broker is None:
            raise RuntimeError("Cannot start the TLS listener before the amqtt broker is running")
        listener = _CappedTLSListener(
            max_connections=_TLS_MAX_CONNECTIONS,
            broker=self._broker,
            listener_name=_TLS_LISTENER_NAME,
            host=_TLS_BIND_HOST,
            port=mqtt_tls_port,
            ssl_context_factory=lambda: build_server_ssl_context(tls_config, self._sni_callback()),
        )
        await listener.start()
        return listener

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

        self._broker = Broker(self._config)
        await self._broker.start()
        loop = asyncio.get_running_loop()
        self._original_exception_handler = loop.get_exception_handler()
        loop.set_exception_handler(
            lambda loop, ctx: _mqtt_asyncio_exception_handler(loop, ctx, self._original_exception_handler)
        )
        if self.tls_config and self.mqtt_tls_port >= 0:
            try:
                self._tls_listener = await self._start_tls_listener(self.tls_config, self.mqtt_tls_port)
            except BaseException:
                # Undo the partial start so the TCP port is released and a later start() can retry.
                loop.set_exception_handler(self._original_exception_handler)
                self._original_exception_handler = None
                await self._broker.shutdown()
                self._broker = None
                raise
        self._running = True

        logger.info("MQTT broker started successfully")

    async def _disconnect_revoked_sessions(self, crl_pem: bytes) -> int:
        """Disconnect connected TLS sessions whose peer certificate is listed in the CRL.

        A reload only affects new handshakes, so clients authenticated with a certificate that
        was revoked since they connected would otherwise stay connected until they reconnect.

        Returns:
            Number of sessions asked to disconnect.
        """
        if self._broker is None:
            return 0
        revoked_serials = _revoked_serial_numbers(crl_pem)
        if not revoked_serials:
            return 0
        dropped = 0
        for client_id, (session, handler) in list(self._broker.sessions.items()):
            ssl_object = session.ssl_object
            if ssl_object is None or session.transitions.state != "connected":
                continue
            der = ssl_object.getpeercert(binary_form=True)
            if der is None:
                continue
            serial = x509.load_der_x509_certificate(der).serial_number
            if serial not in revoked_serials:
                continue
            logger.info("[mqtt-tls] Dropping session of revoked certificate: client=%s serial=%x", client_id, serial)
            await handler.handle_disconnect(None)
            dropped += 1
        return dropped

    async def reload_tls(
        self,
        tls_config: TLSConfig | None,
        mqtt_tls_port: int = -1,
        reason: str = "configuration changed",
    ) -> None:
        """Hot-reload TLS configuration without restarting the amqtt broker.

        The TLS accept socket is rebuilt with the new certificate material (or
        started / closed when TLS is being enabled / disabled, or moved to a new
        port).  Existing MQTT connections are not interrupted: only new
        handshakes see the new certificates and CRL.

        Args:
            tls_config: New TLS certificates, or None to disable TLS.
            mqtt_tls_port: Port for the TLS listener (-1 = disabled).
            reason: Human-readable reason for the reload (included in logs).
        """
        async with self._reload_lock:
            logger.info("TLS hot-reload triggered — reason: %s", reason)

            # Cleared only when the new listener is up, so a reload that dies half-way
            # stays visible to the CRL refresh check.
            self.tls_reload_failed = True

            enabled = tls_config is not None and mqtt_tls_port >= 0
            old_listener = self._tls_listener
            if tls_config is not None and enabled:
                if old_listener is not None and old_listener.port == mqtt_tls_port:
                    # Same port: amqtt rebinds in place and restores the previous socket on failure.
                    await old_listener.reload(lambda: build_server_ssl_context(tls_config, self._sni_callback()))
                else:
                    # New port (or TLS newly enabled): start the replacement first so a bind failure
                    # leaves the old listener, and the configuration that describes it, untouched.
                    self._tls_listener = await self._start_tls_listener(tls_config, mqtt_tls_port)
                    if old_listener is not None:
                        await old_listener.close()
            elif old_listener is not None:
                await old_listener.close()
                self._tls_listener = None

            self.tls_config = tls_config
            self.mqtt_tls_port = mqtt_tls_port
            if enabled and tls_config is not None and tls_config.crl_pem:
                await self._disconnect_revoked_sessions(tls_config.crl_pem)

            tls_status = f"TLS on port {mqtt_tls_port}" if mqtt_tls_port >= 0 else "TLS disabled"
            self.tls_reload_failed = False
            logger.info("TLS hot-reload complete — %s", tls_status)

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

        if self._tls_listener is not None:
            await self._tls_listener.close()
            self._tls_listener = None
        asyncio.get_running_loop().set_exception_handler(self._original_exception_handler)
        self._original_exception_handler = None
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
