"""Tests for MQTT authentication with Django integration."""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from hamcrest import assert_that, contains_string, equal_to, has_length, is_

from my_tracks.mqtt import auth as auth_module
from my_tracks.mqtt.auth import (DjangoAuthPlugin, authenticate_by_cert,
                                 authenticate_user, check_topic_access,
                                 get_auth_config)
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


def _make_session(
    *,
    username: str | None = None,
    password: str | None = None,
    ssl_object: Any = None,
) -> MagicMock:
    """Build a mock amqtt Session with the given attributes."""
    session = MagicMock()
    session.username = username
    session.password = password
    session.ssl_object = ssl_object
    return session


def _make_ssl_object(cn: str) -> MagicMock:
    """Build a mock ssl.SSLObject whose peer cert has the given CN."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import UTC, datetime, timedelta

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, cn)]))
        .issuer_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "TestCA")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    der_bytes = cert.public_bytes(serialization.Encoding.DER)

    ssl_obj = MagicMock()
    ssl_obj.getpeercert.return_value = der_bytes
    return ssl_obj


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


class TestAuthenticateByCert:
    """Tests for authenticate_by_cert function."""

    def test_cn_matches_username_active_user(self, test_user: Any) -> None:
        """Active user with matching CN and username should pass."""
        assert_that(authenticate_by_cert("testuser", "testuser"), is_(True))

    def test_cn_without_username_none(self, test_user: Any) -> None:
        """Valid CN with None username should pass."""
        assert_that(authenticate_by_cert("testuser", None), is_(True))

    def test_cn_without_username_empty(self, test_user: Any) -> None:
        """Valid CN with empty-string username should pass (OwnTracks sends '')."""
        assert_that(authenticate_by_cert("testuser", ""), is_(True))

    def test_cn_username_mismatch_rejected(self, test_user: Any) -> None:
        """Username that doesn't match cert CN should be rejected."""
        assert_that(authenticate_by_cert("testuser", "otheruser"), is_(False))

    def test_cn_no_django_user(self, db: Any) -> None:
        """CN with no corresponding Django user should be rejected."""
        assert_that(authenticate_by_cert("unknown", None), is_(False))

    def test_cn_inactive_user(self, inactive_user: Any) -> None:
        """CN mapping to an inactive Django user should be rejected."""
        assert_that(authenticate_by_cert("inactive", None), is_(False))


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


class TestAuthFailureLogging:
    """Auth failures must be logged at WARNING for security monitoring."""

    def test_nonexistent_user_logs_warning(self, db: Any) -> None:
        """Failed auth for unknown user should log at WARNING."""
        with patch.object(auth_module.logger, "warning") as mock_warn:
            authenticate_user("ghost", "pass")
        mock_warn.assert_called_once()
        assert_that(mock_warn.call_args[0][1], equal_to("ghost"))

    def test_invalid_password_logs_warning(self, test_user: Any) -> None:
        """Failed auth for wrong password should log at WARNING."""
        with patch.object(auth_module.logger, "warning") as mock_warn:
            authenticate_user("testuser", "wrong")
        mock_warn.assert_called_once()
        assert_that(mock_warn.call_args[0][1], equal_to("testuser"))

    def test_inactive_user_logs_warning(self, inactive_user: Any) -> None:
        """Failed auth for inactive user should log at WARNING."""
        with patch.object(auth_module.logger, "warning") as mock_warn:
            authenticate_user("inactive", "pass123")
        mock_warn.assert_called_once()
        assert_that(mock_warn.call_args[0][1], equal_to("inactive"))

    @pytest.mark.asyncio
    async def test_missing_credentials_logs_warning(
        self, db: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Missing username/password on non-TLS should log at WARNING."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        session = _make_session()
        with patch.object(auth_module.logger, "warning") as mock_warn:
            await plugin.authenticate(session=session)
        mock_warn.assert_called_once()
        msg = mock_warn.call_args[0][0]
        assert_that(msg, contains_string("missing"))

    def test_cert_cn_mismatch_logs_warning(self, test_user: Any) -> None:
        """Username != cert CN should log at WARNING with [mqtt-tls] tag."""
        with patch.object(auth_module.logger, "warning") as mock_warn:
            authenticate_by_cert("testuser", "impersonator")
        mock_warn.assert_called_once()
        fmt = mock_warn.call_args[0][0] % mock_warn.call_args[0][1:]
        assert_that(fmt, contains_string("[mqtt-tls]"))
        assert_that(fmt, contains_string("impersonator"))
        assert_that(fmt, contains_string("testuser"))

    def test_cert_cn_no_user_logs_warning(self, db: Any) -> None:
        """Cert CN with no Django user should log at WARNING."""
        with patch.object(auth_module.logger, "warning") as mock_warn:
            authenticate_by_cert("nobody", None)
        mock_warn.assert_called_once()
        fmt = mock_warn.call_args[0][0] % mock_warn.call_args[0][1:]
        assert_that(fmt, contains_string("[mqtt-tls]"))
        assert_that(fmt, contains_string("nobody"))


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

    def test_with_django_auth_anonymous_enabled(self) -> None:
        """With django_auth=True but anonymous allowed, should use AnonymousAuthPlugin."""
        config = get_default_config(use_django_auth=True, allow_anonymous=True)
        assert_that("amqtt.plugins.authentication.AnonymousAuthPlugin" in config["plugins"], is_(True))
        assert_that("my_tracks.mqtt.auth.DjangoAuthPlugin" in config["plugins"], is_(False))

    def test_django_auth_with_anonymous_disabled(self) -> None:
        """Should use DjangoAuthPlugin when anonymous disabled with Django auth."""
        config = get_default_config(use_django_auth=True, allow_anonymous=False)
        assert_that("my_tracks.mqtt.auth.DjangoAuthPlugin" in config["plugins"], is_(True))
        assert_that("amqtt.plugins.authentication.AnonymousAuthPlugin" in config["plugins"], is_(False))


class TestDjangoAuthPluginPasswordAuth:
    """Tests for DjangoAuthPlugin password-based authentication (non-TLS)."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_authenticate_valid_user(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Should authenticate valid user via password on plain TCP."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        session = _make_session(username="testuser", password="testpass123")
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(True))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_authenticate_invalid_user(
        self, db: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Should reject invalid user."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        session = _make_session(username="nonexistent", password="anypass")
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_authenticate_missing_username(
        self, db: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Should reject missing username."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        session = _make_session(password="somepass")
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_authenticate_missing_password(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Should reject missing password."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        session = _make_session(username="testuser")
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))


class TestDjangoAuthPluginCertAuth:
    """Tests for DjangoAuthPlugin cert-based authentication (mTLS)."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_valid_cert_matching_username(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS client with valid cert and matching username should authenticate."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("testuser")
        session = _make_session(username="testuser", ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(True))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_valid_cert_no_username(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS client with valid cert and no username should use CN as identity."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("testuser")
        session = _make_session(ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(True))
        assert_that(session.username, equal_to("testuser"))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_valid_cert_empty_username(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS client with valid cert and empty username should use CN as identity."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("testuser")
        session = _make_session(username="", ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(True))
        assert_that(session.username, equal_to("testuser"))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_cert_cn_username_mismatch(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS client whose username doesn't match cert CN should be rejected."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("testuser")
        session = _make_session(username="impersonator", ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_cert_cn_no_django_user(
        self, db: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS client with cert CN that has no Django user should be rejected."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("unknown_cn")
        session = _make_session(ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_cert_cn_inactive_user(
        self, inactive_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS client with cert CN mapping to inactive user should be rejected."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("inactive")
        session = _make_session(ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))

    @pytest.mark.asyncio
    async def test_tls_no_peer_cert(
        self, db: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS connection with no peer cert should be rejected."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = MagicMock()
        ssl_obj.getpeercert.return_value = None
        session = _make_session(ssl_object=ssl_obj)
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(False))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_tls_no_password_needed(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """TLS auth should succeed even with no password (cert is the credential)."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        ssl_obj = _make_ssl_object("testuser")
        session = _make_session(username="testuser", ssl_object=ssl_obj)
        assert_that(session.password, is_(None))
        result = await plugin.authenticate(session=session)
        assert_that(result, is_(True))


class TestDjangoAuthPluginTopicACLs:
    """Tests for topic ACL enforcement via DjangoAuthPlugin."""

    @pytest.mark.asyncio
    async def test_on_broker_client_subscribed_allowed(
        self, test_user: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Should allow subscription to own topic."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
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
        self, test_user: Any, mock_plugin_context: MagicMock,
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
        self, test_user: Any, mock_plugin_context: MagicMock,
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
        self, test_user: Any, mock_plugin_context: MagicMock,
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
        self, db: Any, mock_plugin_context: MagicMock,
    ) -> None:
        """Should allow access when no session provided (let broker config handle)."""
        plugin = DjangoAuthPlugin(context=mock_plugin_context)
        result = await plugin.on_broker_client_subscribed(
            client_id="client1",
            topic="owntracks/anyuser/phone",
            qos=0,
        )
        assert_that(result, is_(True))
