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
import weakref
from collections import deque
from dataclasses import dataclass
from typing import Any

from amqtt.adapters import ReaderAdapter, WriterAdapter
from amqtt.broker import Broker, BrokerProtocolHandler
from amqtt.errors import AMQTTError, MQTTError, NoDataError
from amqtt.session import Session

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


def _log_background_task_exception(task: asyncio.Task[Any]) -> None:
    """Log exceptions from fire-and-forget MQTT broker tasks (e.g. QoS 1 publish)."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is None:
        return
    if isinstance(exc, TimeoutError):
        logger.warning("[mqtt] Background publish timed out: %s", exc)
        return
    logger.warning(
        "[mqtt] Background publish failed: %s",
        exc,
        exc_info=exc,
    )


def _attach_background_task_logging(task: asyncio.Task[Any]) -> None:
    """Ensure a done callback logs task failures instead of asyncio ERROR noise."""
    if getattr(task, "_mqtt_exception_logged", False):
        return
    task._mqtt_exception_logged = True  # type: ignore[attr-defined]
    task.add_done_callback(_log_background_task_exception)


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
            peername, exception,
        )
        return

    if "Task exception was never retrieved" in message:
        if isinstance(exception, TimeoutError):
            logger.warning("[mqtt] %s", exception)
        elif exception is not None:
            logger.warning(
                "[mqtt] Unhandled background task failed: %s",
                exception,
                exc_info=exception,
            )
        else:
            logger.warning("[mqtt] %s", message)
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


class _CRLBroker(Broker):
    """Broker subclass that enforces mutual TLS with optional CRL checking.

    amqtt's ``_create_ssl_context`` hardcodes ``CERT_OPTIONAL``, which
    silently accepts connections without a client certificate.  This
    override switches to ``CERT_REQUIRED`` so that missing, invalid,
    expired, or untrusted client certs cause an immediate handshake
    failure.

    TLS 1.3 is intentionally excluded: it defers client certificate
    verification to a post-handshake exchange that ``asyncio.start_server``
    does not propagate reliably, allowing invalid/expired/revoked certs
    through (cpython#83375, open since 2020).  TLS 1.2 remains the
    ceiling until Python/asyncio fixes this.

    When ``_crl_pem`` is set, the override also enables leaf-level CRL
    revocation checking so that revoked certs are rejected.
    """

    _crl_pem: bytes | None = None
    _server_cert_sans: list[str] = []
    _original_exception_handler: Any = None
    # Maps ssl.SSLObject → SNI hostname sent by client in ClientHello.
    # Populated by the servername callback during the TLS handshake.
    # WeakKeyDictionary so entries are cleaned up automatically when the
    # ssl object is garbage-collected (e.g. for connections that fail
    # before reaching _initialize_client_session).
    _sni_map: weakref.WeakKeyDictionary[ssl.SSLObject, str] = weakref.WeakKeyDictionary()

    @staticmethod
    def _create_ssl_context(listener: Any) -> ssl.SSLContext:
        ctx = Broker._create_ssl_context(listener)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        if _CRLBroker._crl_pem is not None:
            ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
            logger.info("CRL enforcement enabled for revocation checking")
        # Capture the SNI hostname the client advertised in ClientHello.
        # ssl.SSLObject.server_hostname is None on the server side (it
        # reflects the client-side constructor parameter, not inbound SNI),
        # so the only reliable way to read SNI server-side is this callback.

        def _sni_callback(
            ssl_obj: ssl.SSLSocket | ssl.SSLObject,
            server_name: str | None,
            ssl_context: ssl.SSLContext | ssl.SSLSocket,
        ) -> None:
            if server_name is not None and isinstance(ssl_obj, ssl.SSLObject):
                _CRLBroker._sni_map[ssl_obj] = server_name
        ctx.set_servername_callback(_sni_callback)
        return ctx

    async def start(self) -> None:
        """Start the broker and install the TLS exception handler."""
        await super().start()
        loop = asyncio.get_running_loop()
        _CRLBroker._original_exception_handler = loop.get_exception_handler()
        loop.set_exception_handler(
            lambda loop, ctx: _mqtt_asyncio_exception_handler(
                loop, ctx, _CRLBroker._original_exception_handler,
            )
        )

    async def shutdown(self) -> None:
        """Shutdown the broker and restore the original exception handler."""
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_CRLBroker._original_exception_handler)
        _CRLBroker._original_exception_handler = None
        await super().shutdown()

    async def _initialize_client_session(
        self,
        reader: ReaderAdapter,
        writer: WriterAdapter,
        remote_address: str,
        remote_port: int,
    ) -> tuple[BrokerProtocolHandler, Session]:
        """Wrap parent to refresh TLS identity on reconnect and detect early disconnects.

        amqtt reuses persistent sessions (``clean_session=False``) but does not copy
        the new connection's ``ssl_object`` onto the cached session. mTLS auth then
        reads a stale certificate and rejects valid clients until broker restart.

        When a TLS handshake succeeds server-side but the client immediately closes
        the connection (no MQTT data), it almost always means the client rejected
        the server certificate (hostname not in SANs, untrusted CA, etc.).
        """
        try:
            handler, client_session = await super()._initialize_client_session(
                reader, writer, remote_address, remote_port,
            )
        except (AMQTTError, MQTTError, NoDataError):
            ssl_obj = writer.get_ssl_info()
            if ssl_obj is not None:
                sans = ", ".join(_CRLBroker._server_cert_sans) or "none"
                sni = _CRLBroker._sni_map.pop(ssl_obj, None) or "not sent"
                logger.warning(
                    "[mqtt-tls] Client %s:%s completed TLS handshake but "
                    "disconnected before sending MQTT data. The client "
                    "likely rejected the server certificate (hostname not "
                    "in SANs, untrusted CA, or expired cert). "
                    "Client expected hostname (SNI): %s — "
                    "Server cert SANs: [%s]",
                    remote_address, remote_port, sni, sans,
                )
            raise

        fresh_ssl = writer.get_ssl_info()
        if fresh_ssl is not None:
            client_session.ssl_object = fresh_ssl
        client_session.remote_address = remote_address
        client_session.remote_port = remote_port
        return handler, client_session

    async def _client_connected(
        self,
        listener_name: str,
        reader: ReaderAdapter,
        writer: WriterAdapter,
    ) -> None:
        """Log connection-handler failures amqtt does not catch (e.g. SSL shutdown timeout)."""
        try:
            await super()._client_connected(listener_name, reader, writer)
        except TimeoutError as exc:
            tag = "[mqtt-tls]" if writer.get_ssl_info() is not None else "[mqtt]"
            logger.warning(
                "%s Client connection closed during shutdown on listener '%s': %s",
                tag,
                listener_name,
                exc,
            )

    async def _run_broadcast(
        self,
        running_tasks: deque[asyncio.Task[Any]],
    ) -> None:
        """Attach logging to fire-and-forget publish tasks (QoS 1 PUBACK timeouts)."""
        tasks_before = len(running_tasks)
        await super()._run_broadcast(running_tasks)
        for task in list(running_tasks)[tasks_before:]:
            _attach_background_task_logging(task)


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
        "app.mqtt.sys_plugin.BrokerSysPluginQos0": {"sys_interval": 30},
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
        self._reload_lock = asyncio.Lock()

    def _setup_tls_files(self, tls_config: TLSConfig) -> None:
        """Write TLS certificates to temporary files for amqtt.

        amqtt requires file paths, not in-memory PEM data.
        Files are cleaned up when the broker stops.
        Also extracts server cert SANs for diagnostic logging.
        """
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        try:
            cert = x509.load_pem_x509_certificate(tls_config.server_cert_pem)
            san_ext = cert.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME,
            )
            san_names = san_ext.value.get_values_for_type(x509.DNSName)
            san_ips = [
                str(ip)
                for ip in san_ext.value.get_values_for_type(x509.IPAddress)
            ]
            _CRLBroker._server_cert_sans = san_names + san_ips
        except Exception:
            _CRLBroker._server_cert_sans = []

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
        """Check if the broker wrapper is running.

        Note: during TLS hot-reload the inner amqtt Broker instance may be
        temporarily unavailable even while the wrapper remains running.
        Callers that need internal publish should also check ``amqtt_broker``.
        """
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

    async def reload_tls(
        self,
        tls_config: TLSConfig | None,
        mqtt_tls_port: int = -1,
        reason: str = "configuration changed",
    ) -> None:
        """Hot-reload TLS configuration by restarting the internal amqtt broker.

        The MQTTBroker wrapper stays alive (``_running`` remains True)
        so the polling loop in ``apps._start_and_run`` is not interrupted.
        Only the inner amqtt ``Broker`` instance is stopped and recreated
        with the new certificate material.

        Args:
            tls_config: New TLS certificates, or None to disable TLS.
            mqtt_tls_port: Port for the TLS listener (-1 = disabled).
            reason: Human-readable reason for the reload (included in logs).
        """
        async with self._reload_lock:
            logger.info("TLS hot-reload triggered — reason: %s", reason)

            if self._broker is not None:
                logger.info("Stopping current MQTT broker for TLS reload")
                await self._broker.shutdown()
                self._broker = None

            self._cleanup_tls_files()
            _CRLBroker._crl_pem = None

            self.tls_config = tls_config
            self.mqtt_tls_port = mqtt_tls_port
            self._tls_certfile = None
            self._tls_keyfile = None
            self._tls_cafile = None

            if tls_config and mqtt_tls_port >= 0:
                self._setup_tls_files(tls_config)

            self._config = get_default_config(
                mqtt_port=self.mqtt_port,
                mqtt_tls_port=mqtt_tls_port,
                tls_certfile=self._tls_certfile,
                tls_keyfile=self._tls_keyfile,
                tls_cafile=self._tls_cafile,
                allow_anonymous=self.allow_anonymous,
                use_django_auth=self.use_django_auth,
                use_owntracks_handler=self.use_owntracks_handler,
            )

            if tls_config:
                _CRLBroker._crl_pem = tls_config.crl_pem
                self._broker = _CRLBroker(self._config)
            else:
                self._broker = Broker(self._config)

            await self._broker.start()
            self._actual_mqtt_port = None
            self._actual_tls_port = None

            tls_status = f"TLS on port {mqtt_tls_port}" if mqtt_tls_port >= 0 else "TLS disabled"
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
