"""
MQTT Authentication plugin for Django integration.

This module provides authentication and authorization for the MQTT broker
using Django's user authentication system.

Features:
- Mutual TLS (mTLS) authentication: client cert CN maps to Django user
- Username/password fallback for non-TLS connections
- Topic-based access control (users can only access their own topics)
- Support for OwnTracks topic format: owntracks/{user}/{device}
"""

import asyncio
import logging
import re
import ssl
from typing import Any

from amqtt.plugins.authentication import BaseAuthPlugin
from asgiref.sync import sync_to_async
from cryptography import x509
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

# OwnTracks topic pattern: owntracks/{user}/{device}[/{subtopic}]
OWNTRACKS_TOPIC_PATTERN = re.compile(r"^owntracks/([^/]+)/([^/]+)(/.*)?$")


def _extract_cert_cn(ssl_object: ssl.SSLObject) -> str | None:
    """Extract the Common Name from a TLS peer certificate.

    Returns None if no peer cert is present or the CN cannot be read.
    """
    try:
        der_cert = ssl_object.getpeercert(binary_form=True)
    except ValueError:
        # Python raises ValueError("handshake not done yet") if we query the
        # peer cert before the TLS handshake has completed.
        return None
    if der_cert is None:
        return None
    try:
        cert = x509.load_der_x509_certificate(der_cert)
        cn_attrs = cert.subject.get_attributes_for_oid(
            x509.oid.NameOID.COMMON_NAME,
        )
        return str(cn_attrs[0].value) if cn_attrs else None
    except Exception:
        return None


async def _close_session_transport(session: Any) -> None:
    """Best-effort close of an unauthenticated client connection.

    amqtt will typically close connections on auth failure, but if the session
    transport remains open (e.g. handshake edge cases), explicitly closing it
    avoids accumulating idle sockets.
    """
    writer = getattr(session, "writer", None)
    if writer is None:
        return

    try:
        close = getattr(writer, "close", None)
        if callable(close):
            close()
        wait_closed = getattr(writer, "wait_closed", None)
        if callable(wait_closed):
            result = wait_closed()
            if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                await result
    except Exception:
        logger.exception("[mqtt-tls] Failed to close unauthenticated session transport")


def get_django_user(username: str) -> Any:
    """
    Get a Django user by username.

    This is a separate function to allow lazy import of Django models
    and easier testing/mocking.

    Args:
        username: The username to look up

    Returns:
        Django User object or None if not found
    """
    User = get_user_model()
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None


def authenticate_user(username: str, password: str) -> bool:
    """
    Authenticate a user against Django's authentication system.

    Args:
        username: The username
        password: The password (plaintext)

    Returns:
        True if authentication succeeds, False otherwise
    """
    user = get_django_user(username)
    if user is None:
        logger.warning("[mqtt] Auth failed: user '%s' not found", username)
        return False

    if not user.is_active:
        logger.warning("[mqtt] Auth failed: user '%s' is inactive", username)
        return False

    if not user.check_password(password):
        logger.warning("[mqtt] Auth failed: invalid password for user '%s'", username)
        return False

    logger.info("[mqtt] Auth successful for user '%s'", username)
    return True


def authenticate_by_cert(cert_cn: str, mqtt_username: str | None) -> bool:
    """Authenticate a TLS client by matching the certificate CN to a Django user.

    If the MQTT CONNECT packet includes a username, it must match the cert CN.
    If no username was sent, the CN is used as the identity.

    Returns True if the CN corresponds to an active Django user.
    """
    if mqtt_username and mqtt_username != cert_cn:
        logger.warning(
            "[mqtt-tls] Auth failed: username '%s' does not match cert CN '%s'",
            mqtt_username, cert_cn,
        )
        return False

    user = get_django_user(cert_cn)
    if user is None:
        logger.warning(
            "[mqtt-tls] Auth failed: cert CN '%s' has no matching Django user",
            cert_cn,
        )
        return False

    if not user.is_active:
        logger.warning(
            "[mqtt-tls] Auth failed: user '%s' (from cert CN) is inactive",
            cert_cn,
        )
        return False

    logger.info("[mqtt-tls] Auth successful for user '%s' (cert CN)", cert_cn)
    return True


def check_topic_access(username: str, topic: str, action: str) -> bool:
    """
    Check if a user has access to a specific topic.

    OwnTracks topic format: owntracks/{user}/{device}[/{subtopic}]

    Access rules:
    - Users can only access topics under their own username
    - Superusers can access all topics
    - $SYS topics are readable by all authenticated users

    Args:
        username: The authenticated username
        topic: The MQTT topic
        action: 'publish' or 'subscribe'

    Returns:
        True if access is allowed, False otherwise
    """
    # $SYS topics are readable by all authenticated users
    if topic.startswith("$SYS/"):
        if action == "subscribe":
            return True
        # Only broker can publish to $SYS
        return False

    # Check if it's an OwnTracks topic
    match = OWNTRACKS_TOPIC_PATTERN.match(topic)
    if not match:
        # Non-OwnTracks topics - deny by default
        logger.debug(
            "MQTT access denied: topic '%s' is not an OwnTracks topic",
            topic,
        )
        return False

    topic_user = match.group(1)
    subtopic = match.group(3) or ""

    # Users can only access their own topics
    if topic_user == username:
        return True

    # Any authenticated user may publish to another user's /cmd subtopic.
    # This allows OwnTracks Android to send reportLocation directly to a
    # friend's device (owntracks/{friend}/{device}/cmd).
    # TODO: Once a Friend data model exists, restrict this to actual friends
    # rather than all authenticated users.
    if action == "publish" and subtopic == "/cmd":
        return True

    # Check if user is a superuser (can access all topics)
    user = get_django_user(username)
    if user and user.is_superuser:
        logger.debug(
            "MQTT access granted: superuser '%s' accessing '%s'",
            username,
            topic,
        )
        return True

    logger.debug(
        "MQTT access denied: user '%s' cannot access topic for user '%s'",
        username,
        topic_user,
    )
    return False


class DjangoAuthPlugin(BaseAuthPlugin):
    """MQTT authentication plugin using Django's user system.

    Supports two authentication modes depending on the transport:

    **TLS connections** (mTLS): The client certificate CN is the identity.
    No password is required.  If the MQTT CONNECT packet includes a
    username it must match the cert CN; otherwise the CN is used directly.
    The CN must correspond to an active Django user.

    **Plain TCP connections**: Standard username/password authentication
    against Django's auth backend.

    Topic ACLs are enforced identically for both modes based on the
    resolved username.
    """

    def __init__(self, context: Any) -> None:
        """Initialize the plugin with broker context."""
        super().__init__(context)
        logger.info("DjangoAuthPlugin initialized")

    async def authenticate(self, *, session: Any, **kwargs: Any) -> bool:
        """Authenticate a client connection.

        amqtt calls this via ``map_plugin_auth(session=session)`` so the
        session is the only argument.  Username, password, and TLS info
        are read from session attributes.
        """
        ssl_object = getattr(session, "ssl_object", None)

        if ssl_object is not None:
            return await self._authenticate_tls(session, ssl_object)
        return await self._authenticate_password(session)

    async def _authenticate_tls(
        self, session: Any, ssl_object: ssl.SSLObject,
    ) -> bool:
        """Authenticate via client certificate CN."""
        cert_cn: str | None = None
        # On some TLS transports the handshake may not be complete when amqtt
        # invokes auth plugins. Retry with a small bounded backoff to avoid
        # crashing the broker and to allow valid mTLS clients to connect
        # reliably.
        #
        # We keep the total wait time small to avoid tying up broker resources
        # on unauthenticated connections.
        max_wait_s = 2.0
        sleep_s = 0.05
        elapsed_s = 0.0
        while elapsed_s <= max_wait_s:
            cert_cn = _extract_cert_cn(ssl_object)
            if cert_cn is not None:
                break
            await asyncio.sleep(sleep_s)
            elapsed_s += sleep_s
            sleep_s = min(sleep_s * 2, 0.5)
        if cert_cn is None:
            logger.warning("[mqtt-tls] Auth failed: no peer certificate CN")
            await _close_session_transport(session)
            return False

        mqtt_username: str | None = getattr(session, "username", None)
        # amqtt runs in its own asyncio loop (often in a dedicated thread) and is
        # not under Django/ASGI's request lifecycle. Using thread_sensitive=True
        # can bind work to asgiref's CurrentThreadExecutor, which may already be
        # shut down in this context and crash the broker.
        result = await sync_to_async(authenticate_by_cert, thread_sensitive=False)(
            cert_cn, mqtt_username
        )

        if result and not mqtt_username:
            session.username = cert_cn

        if not result:
            await _close_session_transport(session)

        return result

    async def _authenticate_password(self, session: Any) -> bool:
        """Authenticate via username/password (non-TLS fallback)."""
        username: str | None = getattr(session, "username", None)
        password: str | None = getattr(session, "password", None)

        if username is None or password is None:
            logger.warning("[mqtt] Auth failed: missing username or password")
            return False

        return await sync_to_async(authenticate_user, thread_sensitive=False)(
            username, password
        )

    async def on_broker_client_subscribed(
        self,
        client_id: str,
        topic: str,
        qos: int,
        **kwargs: Any,
    ) -> bool:
        """Check if a client can subscribe to a topic."""
        session = kwargs.get("session")
        if session is None:
            return True

        username = getattr(session, "username", None)
        if username is None:
            return True

        return await sync_to_async(check_topic_access, thread_sensitive=False)(
            username, topic, "subscribe"
        )

    async def on_broker_message_received(
        self,
        client_id: str,
        message: Any,
        **kwargs: Any,
    ) -> bool:
        """Check if a client can publish to a topic."""
        session = kwargs.get("session")
        if session is None:
            return True

        username = getattr(session, "username", None)
        if username is None:
            return True

        topic = message.topic if hasattr(message, "topic") else str(message)
        return await sync_to_async(check_topic_access, thread_sensitive=False)(
            username, topic, "publish"
        )


def get_auth_config(allow_anonymous: bool = False) -> dict[str, Any]:
    """
    Get authentication configuration for the MQTT broker.

    Args:
        allow_anonymous: Whether to allow anonymous connections
                        (should be False for production)

    Returns:
        Auth configuration dict for broker config
    """
    return {
        "allow-anonymous": allow_anonymous,
        "plugins": ["app.mqtt.auth.DjangoAuthPlugin"],
    }
