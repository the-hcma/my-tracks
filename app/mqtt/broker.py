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
# asyncio raises TimeoutError("SSL shutdown timed out") when a peer never completes the TLS close.
_SSL_SHUTDOWN_TIMEOUT_TEXT = "SSL shutdown timed out"
_TLS_BIND_HOST = "0.0.0.0"
_TLS_MAX_CONNECTIONS = 100
# How long stop() waits for TLS connection handlers to end after their transports are closed.
_TLS_SHUTDOWN_DRAIN_SECONDS = 5.0


class _TLSConnectionRegistry:
    """Live TLS transports of the broker, shared by every listener generation.

    A transport is counted once from accept until it closes, so a client that has finished the
    handshake but not yet sent MQTT CONNECT is included, and a listener replaced by a port change
    does not take its connections out of the count. A reload uses it to close the transports whose
    trust changed, including the ones that have no MQTT session yet.
    """

    def __init__(self) -> None:
        self._writers: set[asyncio.StreamWriter] = set()

    def __len__(self) -> int:
        return len(self._writers)

    def add(self, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)

    def close_matching(self, drop_reason: Callable[[ssl.SSLObject], str | None]) -> int:
        """Close every transport for which ``drop_reason`` returns a reason; return how many."""
        closed = 0
        for writer in list(self._writers):
            if writer.is_closing():
                continue
            ssl_object = writer.get_extra_info("ssl_object")
            if ssl_object is None:
                continue
            reason = drop_reason(ssl_object)
            if reason is None:
                continue
            logger.info("[mqtt-tls] Closing connection: reason=%s", reason)
            writer.close()
            closed += 1
        return closed

    def discard(self, writer: asyncio.StreamWriter) -> None:
        self._writers.discard(writer)


class _CappedTLSListener(ReloadableExternalTLSListener):
    """Reloadable TLS listener that refuses connections beyond ``max_connections``.

    amqtt applies ``max_connections`` only to listeners it opens itself, so the cap that the
    old in-broker TLS listener had is enforced here for the external one, across every listener
    generation through the shared ``registry``.
    """

    def __init__(self, *, max_connections: int, registry: _TLSConnectionRegistry, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.max_connections = max_connections
        self.registry = registry

    async def _client_connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if len(self.registry) >= self.max_connections:
            logger.warning(
                "[mqtt-tls] Connection refused: limit reached (active=%d, max=%d)",
                len(self.registry),
                self.max_connections,
            )
            writer.close()
            return
        self.registry.add(writer)
        try:
            await super()._client_connected(reader, writer)
        finally:
            self.registry.discard(writer)


class _ListenerShutdownTimeoutFilter(logging.Filter):
    """Downgrade asyncio's "SSL shutdown timed out" in amqtt's TLS listener to one tagged WARNING.

    ``ReloadableExternalTLSListener`` catches every exception from a connection and logs it with
    ``logger.exception``, so a peer that never completes the TLS close would show up as an ERROR
    with a traceback. It is routine for a client that drops off the network. Any other
    exception, including a different ``TimeoutError``, keeps its level and traceback.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, TimeoutError) and _SSL_SHUTDOWN_TIMEOUT_TEXT in str(exc):
            listener_name = record.args[0] if isinstance(record.args, tuple) and record.args else _TLS_LISTENER_NAME
            record.levelno = logging.WARNING
            record.levelname = logging.getLevelName(logging.WARNING)
            record.msg = "[mqtt-tls] Client connection closed during shutdown on listener '%s': %s"
            record.args = (listener_name, exc)
            record.exc_info = None
            record.exc_text = None
        return True


def _demote_listener_shutdown_timeouts() -> None:
    """Install :class:`_ListenerShutdownTimeoutFilter` on amqtt's listener logger once."""
    listener_logger = logging.getLogger(ReloadableExternalTLSListener.__module__)
    if not any(isinstance(existing, _ListenerShutdownTimeoutFilter) for existing in listener_logger.filters):
        listener_logger.addFilter(_ListenerShutdownTimeoutFilter())


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
        self._tls_connections = _TLSConnectionRegistry()
        # Why connected TLS clients must still be dropped when a reload's drop step failed part-way.
        self._pending_trust_drop: str | None = None

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
        _demote_listener_shutdown_timeouts()
        listener = _CappedTLSListener(
            max_connections=_TLS_MAX_CONNECTIONS,
            registry=self._tls_connections,
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

        # Held until the TLS listener is up, so a reload triggered by a certificate change
        # during startup waits for the listener to exist instead of racing to bind its own.
        async with self._reload_lock:
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

    async def _disconnect_tls_sessions(self, drop_reason: Callable[[ssl.SSLObject], str | None]) -> int:
        """Disconnect connected TLS sessions for which ``drop_reason`` returns a reason.

        A reload only affects new handshakes, so a client authenticated under the old
        configuration would otherwise stay connected until it reconnects on its own.

        Returns:
            Number of sessions asked to disconnect.
        """
        if self._broker is None:
            return 0
        dropped = 0
        for client_id, (session, handler) in list(self._broker.sessions.items()):
            ssl_object = session.ssl_object
            if ssl_object is None or session.transitions.state != "connected":
                continue
            reason = drop_reason(ssl_object)
            if reason is None:
                continue
            logger.info("[mqtt-tls] Dropping session: client=%s reason=%s", client_id, reason)
            await handler.handle_disconnect(None)
            dropped += 1
        return dropped

    @property
    def trust_drop_pending(self) -> bool:
        """True when a reload changed trust but did not finish dropping the connections that relied on it."""
        return self._pending_trust_drop is not None

    async def finish_pending_trust_drop(self) -> None:
        """Finish an interrupted trust drop without touching the listener or its configuration."""
        async with self._reload_lock:
            cause = self._pending_trust_drop
            if cause is None or not self._running or self._broker is None:
                return
            await self._drop_connections(lambda _ssl_object: cause)
            self._pending_trust_drop = None
            self.tls_reload_failed = False
            logger.info("[mqtt-tls] Finished dropping connections after: %s", cause)

    async def _drop_connections(self, drop_reason: Callable[[ssl.SSLObject], str | None]) -> int:
        """Drop TLS sessions and the TLS transports that have no session yet (waiting for CONNECT).

        Returns:
            Number of sessions asked to disconnect.
        """
        dropped = await self._disconnect_tls_sessions(drop_reason)
        self._tls_connections.close_matching(drop_reason)
        return dropped

    async def _disconnect_revoked_sessions(self, crl_pem: bytes) -> int:
        """Drop TLS connections whose peer certificate is listed in the CRL."""
        revoked_serials = _revoked_serial_numbers(crl_pem)
        if not revoked_serials:
            return 0

        def revoked_reason(ssl_object: ssl.SSLObject) -> str | None:
            der = ssl_object.getpeercert(binary_form=True)
            if der is None:
                return None
            serial = x509.load_der_x509_certificate(der).serial_number
            return f"certificate revoked (serial {serial:x})" if serial in revoked_serials else None

        return await self._drop_connections(revoked_reason)

    async def reload_tls(
        self,
        tls_config: TLSConfig | None,
        mqtt_tls_port: int = -1,
        reason: str = "configuration changed",
    ) -> None:
        """Hot-reload TLS configuration without restarting the amqtt broker.

        The TLS accept socket is rebuilt with the new certificate material (or
        started / closed when TLS is being enabled / disabled, or moved to a new
        port).  Existing MQTT connections are kept, so only new handshakes see the
        new certificates, with these exceptions: disabling TLS or replacing the CA
        drops every connected TLS session, and a new CRL drops the sessions whose
        certificate it revokes.

        Args:
            tls_config: New TLS certificates, or None to disable TLS.
            mqtt_tls_port: Port for the TLS listener (-1 = disabled).
            reason: Human-readable reason for the reload (included in logs).
        """
        async with self._reload_lock:
            if not self._running or self._broker is None:
                raise RuntimeError("MQTT broker is not running")
            logger.info("TLS hot-reload triggered — reason: %s", reason)

            # Cleared only when the new listener is up, so a reload that dies half-way
            # stays visible to the CRL refresh check.
            self.tls_reload_failed = True

            enabled = tls_config is not None and mqtt_tls_port >= 0
            previous_config = self.tls_config
            old_listener = self._tls_listener
            if tls_config is not None and enabled:
                if old_listener is not None and old_listener.port == mqtt_tls_port:
                    # Same port: amqtt rebinds in place and tries to restore the previous socket on failure;
                    # if that rebind fails too, no listener stays bound and the error propagates.
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
            cause: str | None = None
            if previous_config is not None and (
                tls_config is None or not enabled or tls_config.ca_cert_pem != previous_config.ca_cert_pem
            ):
                # Their certificates were issued under a CA the broker no longer trusts, or TLS is off.
                cause = "TLS disabled" if tls_config is None or not enabled else "CA certificate replaced"
            # A retry after a failed drop sees an unchanged configuration, so it must finish the earlier drop.
            cause = cause or self._pending_trust_drop
            if cause is not None:
                self._pending_trust_drop = cause
                drop_cause = cause
                await self._drop_connections(lambda _ssl_object: drop_cause)
                self._pending_trust_drop = None
            elif tls_config is not None and enabled and tls_config.crl_pem:
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
        # Serialized with reload_tls so a reload that is replacing the listener cannot assign it after shutdown.
        async with self._reload_lock:
            if not self._running or self._broker is None:
                raise RuntimeError("MQTT broker is not running")

            logger.info("Stopping MQTT broker...")

            listener = self._tls_listener
            if listener is not None:
                await listener.close()
                self._tls_listener = None
            # Streams that finished the handshake but never sent CONNECT have no session, so the amqtt
            # shutdown would leave them (and their registry entries) behind; replaced listeners' too.
            self._tls_connections.close_matching(lambda _ssl_object: "broker stopping")
            if listener is not None:
                try:
                    await listener.wait_connections_closed(timeout=_TLS_SHUTDOWN_DRAIN_SECONDS)
                except TimeoutError:
                    logger.warning(
                        "[mqtt-tls] Connection handlers still running %.0fs after shutdown closed their transports",
                        _TLS_SHUTDOWN_DRAIN_SECONDS,
                    )
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
