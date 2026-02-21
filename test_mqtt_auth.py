"""Tests for MQTT authentication with Django integration."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from hamcrest import assert_that, equal_to, is_

from my_tracks.mqtt.auth import (DjangoAuthPlugin, authenticate_user,
                                 check_topic_access, get_auth_config)
from my_tracks.mqtt.broker import get_default_config

User = get_user_model()


@pytest.fixture
def test_user(db: Any) -> Any:
    """Create a test user."""
    user = User.objects.create_user(
        username="testuser",
        password="testpass123",
    )
    return user


@pytest.fixture
def superuser(db: Any) -> Any:
    """Create a test superuser."""
    user = User.objects.create_superuser(
        username="admin",
        password="adminpass123",
    )
    return user


@pytest.fixture
def inactive_user(db: Any) -> Any:
    """Create an inactive test user."""
    user = User.objects.create_user(
        username="inactive",
        password="pass123",
        is_active=False,
    )
    return user


@pytest.fixture
def mock_plugin_context() -> MagicMock:
    """Create a mock context for the auth plugin."""
    context = MagicMock()
    context.config = {}
    return context


class TestAuthenticateUser:
    """Tests for authenticate_user function."""

    def test_valid_credentials(self, test_user: Any) -> None:
        """Should authenticate with valid credentials."""
        result = authenticate_user("testuser", "testpass123")
        assert_that(result, is_(True))

    def test_invalid_password(self, test_user: Any) -> None:
        """Should reject invalid password."""
        result = authenticate_user("testuser", "wrongpass")
        assert_that(result, is_(False))

    def test_nonexistent_user(self, db: Any) -> None:
        """Should reject nonexistent user."""
        result = authenticate_user("nonexistent", "anypass")
        assert_that(result, is_(False))

    def test_inactive_user(self, inactive_user: Any) -> None:
        """Should reject inactive user."""
        result = authenticate_user("inactive", "pass123")
        assert_that(result, is_(False))

    def test_superuser_can_authenticate(self, superuser: Any) -> None:
        """Superuser should be able to authenticate."""
        result = authenticate_user("admin", "adminpass123")
        assert_that(result, is_(True))


class TestCheckTopicAccess:
    """Tests for check_topic_access function."""

    def test_user_can_access_own_topic(self, test_user: Any) -> None:
        """User should access their own OwnTracks topic."""
        result = check_topic_access("testuser", "owntracks/testuser/phone", "publish")
        assert_that(result, is_(True))

    def test_user_can_subscribe_own_topic(self, test_user: Any) -> None:
        """User should subscribe to their own OwnTracks topic."""
        result = check_topic_access("testuser", "owntracks/testuser/phone", "subscribe")
        assert_that(result, is_(True))

    def test_user_cannot_access_other_user_topic(self, test_user: Any) -> None:
        """User should not access another user's topic."""
        result = check_topic_access("testuser", "owntracks/otheruser/phone", "publish")
        assert_that(result, is_(False))

    def test_superuser_can_access_any_topic(self, superuser: Any) -> None:
        """Superuser should access any OwnTracks topic."""
        result = check_topic_access("admin", "owntracks/anyuser/device", "subscribe")
        assert_that(result, is_(True))

    def test_user_can_subscribe_sys_topic(self, test_user: Any) -> None:
        """User should subscribe to $SYS topics."""
        result = check_topic_access("testuser", "$SYS/broker/clients", "subscribe")
        assert_that(result, is_(True))

    def test_user_cannot_publish_sys_topic(self, test_user: Any) -> None:
        """User should not publish to $SYS topics."""
        result = check_topic_access("testuser", "$SYS/broker/clients", "publish")
        assert_that(result, is_(False))

    def test_non_owntracks_topic_denied(self, test_user: Any) -> None:
        """Non-OwnTracks topics should be denied."""
        result = check_topic_access("testuser", "home/sensors/temp", "subscribe")
        assert_that(result, is_(False))

    def test_user_can_access_subtopic(self, test_user: Any) -> None:
        """User should access subtopics under their username."""
        result = check_topic_access("testuser", "owntracks/testuser/phone/cmd", "subscribe")
        assert_that(result, is_(True))

    def test_user_can_access_event_subtopic(self, test_user: Any) -> None:
        """User should access event subtopics."""
        result = check_topic_access("testuser", "owntracks/testuser/phone/event", "publish")
        assert_that(result, is_(True))


class TestGetAuthConfig:
    """Tests for get_auth_config function."""

    def test_anonymous_disabled(self) -> None:
        """Should have anonymous disabled by default."""
        config = get_auth_config()
        assert_that(config["allow-anonymous"], is_(False))

    def test_anonymous_enabled(self) -> None:
        """Should allow enabling anonymous."""
        config = get_auth_config(allow_anonymous=True)
        assert_that(config["allow-anonymous"], is_(True))

    def test_has_plugin_reference(self) -> None:
        """Should include the Django auth plugin."""
        config = get_auth_config()
        assert_that(config["plugins"], equal_to(["my_tracks.mqtt.auth.DjangoAuthPlugin"]))


class TestGetDefaultConfigWithAuth:
    """Tests for get_default_config with Django auth."""

    def test_default_no_django_auth(self) -> None:
        """Should not include Django auth by default."""
        config = get_default_config()
        assert_that("my_tracks.mqtt.auth.DjangoAuthPlugin" in config["plugins"], is_(False))

    def test_with_django_auth(self) -> None:
        """Should include Django auth plugin when enabled."""
        config = get_default_config(use_django_auth=True)
        assert_that("my_tracks.mqtt.auth.DjangoAuthPlugin" in config["plugins"], is_(True))

    def test_django_auth_with_anonymous_disabled(self) -> None:
        """Should configure auth plugins when anonymous disabled with Django auth."""
        config = get_default_config(use_django_auth=True, allow_anonymous=False)
        assert_that(config["auth"]["allow-anonymous"], is_(False))
        assert_that("plugins" in config["auth"], is_(True))


class TestDjangoAuthPlugin:
    """Tests for DjangoAuthPlugin class."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_authenticate_valid_user(
        self, test_user: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should authenticate valid user."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        result = await plugin.authenticate(
            session=None,
            username="testuser",
            password="testpass123",
        )
        assert_that(result, is_(True))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_authenticate_invalid_user(
        self, db: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should reject invalid user."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        result = await plugin.authenticate(
            session=None,
            username="nonexistent",
            password="anypass",
        )
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_authenticate_missing_username(
        self, db: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should reject missing username."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        result = await plugin.authenticate(
            session=None,
            username=None,
            password="somepass",
        )
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_authenticate_missing_password(
        self, test_user: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should reject missing password."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        result = await plugin.authenticate(
            session=None,
            username="testuser",
            password=None,
        )
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_on_broker_client_subscribed_allowed(
        self, test_user: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should allow subscription to own topic."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)

        # Create a mock session with username
        session = MagicMock()
        session.username = "testuser"

        result = await plugin.on_broker_client_subscribed(
            client_id="client1",
            topic="owntracks/testuser/phone",
            qos=0,
            session=session,
        )
        assert_that(result, is_(True))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_on_broker_client_subscribed_denied(
        self, test_user: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should deny subscription to other user's topic."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)

        session = MagicMock()
        session.username = "testuser"

        result = await plugin.on_broker_client_subscribed(
            client_id="client1",
            topic="owntracks/otheruser/phone",
            qos=0,
            session=session,
        )
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_on_broker_message_received_allowed(
        self, test_user: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should allow publish to own topic."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)

        session = MagicMock()
        session.username = "testuser"

        message = MagicMock()
        message.topic = "owntracks/testuser/phone"

        result = await plugin.on_broker_message_received(
            client_id="client1",
            message=message,
            session=session,
        )
        assert_that(result, is_(True))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_on_broker_message_received_denied(
        self, test_user: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should deny publish to other user's topic."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)

        session = MagicMock()
        session.username = "testuser"

        message = MagicMock()
        message.topic = "owntracks/otheruser/phone"

        result = await plugin.on_broker_message_received(
            client_id="client1",
            message=message,
            session=session,
        )
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_no_session_allows_access(
        self, db: Any, mock_plugin_context: MagicMock
    ) -> None:
        """Should allow access when no session provided (let broker config handle)."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)

        result = await plugin.on_broker_client_subscribed(
            client_id="client1",
            topic="owntracks/anyuser/phone",
            qos=0,
            # No session kwarg
        )
        assert_that(result, is_(True))
