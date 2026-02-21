"""
MQTT Authentication plugin for Django integration.

This module provides authentication and authorization for the MQTT broker
using Django's user authentication system.

Features:
- Username/password authentication against Django users
- Topic-based access control (users can only access their own topics)
- Support for OwnTracks topic format: owntracks/{user}/{device}
"""

import logging
import re
from typing import Any

from amqtt.plugins.authentication import BaseAuthPlugin
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

# OwnTracks topic pattern: owntracks/{user}/{device}[/{subtopic}]
OWNTRACKS_TOPIC_PATTERN = re.compile(r"^owntracks/([^/]+)/([^/]+)(/.*)?$")


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
        logger.debug("MQTT auth failed: user '%s' not found", username)
        return False

    if not user.is_active:
        logger.debug("MQTT auth failed: user '%s' is inactive", username)
        return False

    if not user.check_password(password):
        logger.debug("MQTT auth failed: invalid password for user '%s'", username)
        return False

    logger.info("MQTT auth successful for user '%s'", username)
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

    # Users can only access their own topics
    if topic_user == username:
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
    """
    MQTT authentication plugin using Django's user system.

    This plugin integrates with Django's authentication to:
    - Validate username/password credentials
    - Enforce topic-based access control
    - Allow superusers to access all topics

    Configuration in broker config:
        {
            "auth": {
                "allow-anonymous": False,
                "plugins": ["my_tracks.mqtt.auth.DjangoAuthPlugin"],
            }
        }
    """

    def __init__(self, context: Any) -> None:
        """Initialize the plugin with broker context."""
        super().__init__(context)
        logger.info("DjangoAuthPlugin initialized")

    async def authenticate(
        self,
        session: Any = None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """
        Authenticate a client connection.

        Args:
            session: The MQTT session (unused but required by interface)
            username: The username from CONNECT packet
            password: The password from CONNECT packet
            **kwargs: Additional arguments (unused)

        Returns:
            True if authentication succeeds, False otherwise
        """
        if username is None or password is None:
            logger.debug("MQTT auth failed: missing username or password")
            return False

        # Use sync_to_async for Django ORM operations
        return await sync_to_async(authenticate_user)(username, password)

    async def on_broker_client_subscribed(
        self,
        client_id: str,
        topic: str,
        qos: int,
        **kwargs: Any,
    ) -> bool:
        """
        Check if a client can subscribe to a topic.

        Note: This is called after subscribe. For pre-subscribe checks,
        we'd need to use topic_filtering hook.
        """
        # Get the session to find the username
        session = kwargs.get("session")
        if session is None:
            return True  # Can't check without session

        username = getattr(session, "username", None)
        if username is None:
            return True  # Anonymous - let allow-anonymous setting handle it

        # Use sync_to_async for Django ORM operations in check_topic_access
        return await sync_to_async(check_topic_access)(username, topic, "subscribe")

    async def on_broker_message_received(
        self,
        client_id: str,
        message: Any,
        **kwargs: Any,
    ) -> bool:
        """
        Check if a client can publish to a topic.

        Args:
            client_id: The client identifier
            message: The MQTT message with topic
            **kwargs: Additional arguments including session

        Returns:
            True if publish is allowed, False otherwise
        """
        session = kwargs.get("session")
        if session is None:
            return True

        username = getattr(session, "username", None)
        if username is None:
            return True  # Anonymous

        topic = message.topic if hasattr(message, "topic") else str(message)
        # Use sync_to_async for Django ORM operations in check_topic_access
        return await sync_to_async(check_topic_access)(username, topic, "publish")


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
        "plugins": ["my_tracks.mqtt.auth.DjangoAuthPlugin"],
    }
