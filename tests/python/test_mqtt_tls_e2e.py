"""End-to-end TLS tests for the MQTT broker.

These integration tests start a real MQTTBroker with TLS, generate
actual PKI material (CA, server cert, client certs), and verify that:

- A valid client certificate can connect and exchange MQTT messages.
- An expired client certificate is rejected at the TLS layer.
- A revoked client certificate is rejected when CRL checking is active.
- A certificate signed by an untrusted CA is rejected.
"""

import asyncio
import os
import ssl
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from hamcrest import assert_that, equal_to, is_, not_none

from my_tracks.mqtt.broker import MQTTBroker, TLSConfig
from my_tracks.pki import (generate_ca_certificate,
                           generate_client_certificate, generate_crl,
                           generate_server_certificate,
                           get_certificate_serial_number)

_TEST_KEY_SIZE = 2048


def _generate_expired_client_cert(
    ca_cert_pem: bytes,
    ca_key_pem: bytes,
    username: str,
) -> tuple[bytes, bytes]:
    """Generate a client certificate that expired yesterday."""
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
    ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    if not isinstance(ca_key, RSAPrivateKey):
        raise ValueError("Expected RSA private key for CA")
    client_key = rsa.generate_private_key(
        public_exponent=65537, key_size=_TEST_KEY_SIZE,
    )

    now = datetime.now(UTC)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, username),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "My Tracks"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=365))
        .not_valid_after(now - timedelta(days=1))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = client_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


class _TLSFixture:
    """Holds all PKI material and temporary files for TLS tests."""

    def __init__(self) -> None:
        self._temp_paths: list[str] = []

        self.ca_cert_pem, self.ca_key_pem = generate_ca_certificate(
            common_name="E2E Test CA", key_size=_TEST_KEY_SIZE,
        )
        self.server_cert_pem, self.server_key_pem = generate_server_certificate(
            self.ca_cert_pem, self.ca_key_pem,
            common_name="localhost",
            san_entries=["localhost", "127.0.0.1"],
            key_size=_TEST_KEY_SIZE,
        )
        self.valid_cert_pem, self.valid_key_pem = generate_client_certificate(
            self.ca_cert_pem, self.ca_key_pem,
            username="validuser", key_size=_TEST_KEY_SIZE,
        )
        self.expired_cert_pem, self.expired_key_pem = _generate_expired_client_cert(
            self.ca_cert_pem, self.ca_key_pem, username="expireduser",
        )
        self.revoked_cert_pem, self.revoked_key_pem = generate_client_certificate(
            self.ca_cert_pem, self.ca_key_pem,
            username="revokeduser", key_size=_TEST_KEY_SIZE,
        )

        revoked_serial = get_certificate_serial_number(self.revoked_cert_pem)
        self.crl_pem = generate_crl(
            self.ca_cert_pem, self.ca_key_pem,
            revoked_entries=[(revoked_serial, datetime.now(UTC))],
        )

        other_ca_cert, other_ca_key = generate_ca_certificate(
            common_name="Other CA", key_size=_TEST_KEY_SIZE,
        )
        self.untrusted_cert_pem, self.untrusted_key_pem = generate_client_certificate(
            other_ca_cert, other_ca_key,
            username="untrusteduser", key_size=_TEST_KEY_SIZE,
        )

        self.ca_file = self._write_temp(self.ca_cert_pem)
        self.valid_cert_file = self._write_temp(self.valid_cert_pem)
        self.valid_key_file = self._write_temp(self.valid_key_pem)
        self.expired_cert_file = self._write_temp(self.expired_cert_pem)
        self.expired_key_file = self._write_temp(self.expired_key_pem)
        self.revoked_cert_file = self._write_temp(self.revoked_cert_pem)
        self.revoked_key_file = self._write_temp(self.revoked_key_pem)
        self.untrusted_cert_file = self._write_temp(self.untrusted_cert_pem)
        self.untrusted_key_file = self._write_temp(self.untrusted_key_pem)

    def _write_temp(self, data: bytes) -> str:
        f = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        f.write(data)
        f.flush()
        f.close()
        self._temp_paths.append(f.name)
        return f.name

    def cleanup(self) -> None:
        for path in self._temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def make_tls_config(self, *, with_crl: bool = True) -> TLSConfig:
        return TLSConfig(
            server_cert_pem=self.server_cert_pem,
            server_key_pem=self.server_key_pem,
            ca_cert_pem=self.ca_cert_pem,
            crl_pem=self.crl_pem if with_crl else None,
        )

    def client_ssl_context(
        self,
        certfile: str,
        keyfile: str,
    ) -> ssl.SSLContext:
        """Build a client-side SSL context for raw socket tests."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(self.ca_file)
        ctx.load_cert_chain(certfile, keyfile)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx


@pytest.fixture
def tls_fixture() -> Generator[_TLSFixture]:
    fixture = _TLSFixture()
    yield fixture
    fixture.cleanup()


class TestMQTTBrokerTLSEndToEnd:
    """End-to-end TLS tests through the actual MQTT broker."""

    @pytest.mark.asyncio
    async def test_valid_client_publishes_and_receives_message(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """A valid client cert should allow full MQTT pub/sub over TLS."""
        tls_config = tls_fixture.make_tls_config(with_crl=True)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        sub_client: MQTTClient | None = None
        pub_client: MQTTClient | None = None
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            uri = f"mqtts://localhost:{tls_port}"

            sub_client = MQTTClient(
                client_id="sub-e2e",
                config={
                    "auto_reconnect": False,
                    "check_hostname": False,
                    "connection": {
                        "certfile": tls_fixture.valid_cert_file,
                        "keyfile": tls_fixture.valid_key_file,
                        "cafile": tls_fixture.ca_file,
                    },
                },
            )
            await sub_client.connect(uri, cafile=tls_fixture.ca_file)
            await sub_client.subscribe([
                ("owntracks/testuser/phone", QOS_0),
            ])

            pub_client = MQTTClient(
                client_id="pub-e2e",
                config={
                    "auto_reconnect": False,
                    "check_hostname": False,
                    "connection": {
                        "certfile": tls_fixture.valid_cert_file,
                        "keyfile": tls_fixture.valid_key_file,
                        "cafile": tls_fixture.ca_file,
                    },
                },
            )
            await pub_client.connect(uri, cafile=tls_fixture.ca_file)

            payload = b'{"_type":"location","lat":52.52,"lon":13.405,"tst":1700000000}'
            await pub_client.publish(
                "owntracks/testuser/phone", payload, qos=QOS_0,
            )

            msg = await sub_client.deliver_message(timeout_duration=5)
            assert_that(msg, is_(not_none()))
            assert msg is not None
            assert_that(msg.data, equal_to(payload))
        finally:
            for client in (pub_client, sub_client):
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_valid_client_tls_handshake_succeeds(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """A valid client cert should complete the TLS handshake."""
        tls_config = tls_fixture.make_tls_config(with_crl=True)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            ctx = tls_fixture.client_ssl_context(
                tls_fixture.valid_cert_file,
                tls_fixture.valid_key_file,
            )
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", tls_port, ssl=ctx,
            )
            writer.close()
            await writer.wait_closed()
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_expired_client_cert_rejected(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """An expired client certificate must be rejected by the broker."""
        tls_config = tls_fixture.make_tls_config(with_crl=True)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            ctx = tls_fixture.client_ssl_context(
                tls_fixture.expired_cert_file,
                tls_fixture.expired_key_file,
            )
            connection_failed = False
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", tls_port, ssl=ctx,
                )
                writer.write(b"ping")
                await writer.drain()
                await reader.read(1)
            except (ssl.SSLError, OSError, ConnectionResetError):
                connection_failed = True

            assert_that(
                connection_failed, is_(True),
                "Expired client cert must be rejected",
            )
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_revoked_client_cert_rejected(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """A revoked client certificate must be rejected when CRL is active."""
        tls_config = tls_fixture.make_tls_config(with_crl=True)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            ctx = tls_fixture.client_ssl_context(
                tls_fixture.revoked_cert_file,
                tls_fixture.revoked_key_file,
            )
            connection_failed = False
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", tls_port, ssl=ctx,
                )
                writer.write(b"ping")
                await writer.drain()
                await reader.read(1)
            except (ssl.SSLError, OSError, ConnectionResetError):
                connection_failed = True

            assert_that(
                connection_failed, is_(True),
                "Revoked client cert must be rejected",
            )
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_untrusted_client_cert_rejected(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """A certificate signed by an unknown CA must be rejected."""
        tls_config = tls_fixture.make_tls_config(with_crl=True)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            ctx = tls_fixture.client_ssl_context(
                tls_fixture.untrusted_cert_file,
                tls_fixture.untrusted_key_file,
            )
            connection_failed = False
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", tls_port, ssl=ctx,
                )
                writer.write(b"ping")
                await writer.drain()
                await reader.read(1)
            except (ssl.SSLError, OSError, ConnectionResetError):
                connection_failed = True

            assert_that(
                connection_failed, is_(True),
                "Certificate from untrusted CA must be rejected",
            )
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_no_client_cert_rejected(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """Without a client cert, TLS connection fails (CERT_REQUIRED).

        The MQTT TLS port enforces mutual TLS: a valid client
        certificate is always required.
        """
        tls_config = tls_fixture.make_tls_config(with_crl=True)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(tls_fixture.ca_file)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_REQUIRED

            connection_failed = False
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", tls_port, ssl=ctx,
                )
                writer.write(b"ping")
                await writer.drain()
                await reader.read(1)
            except (ssl.SSLError, OSError, ConnectionResetError):
                connection_failed = True

            assert_that(
                connection_failed, is_(True),
                "Connection without client cert must be rejected",
            )
        finally:
            if broker.is_running:
                await broker.stop()

    @pytest.mark.asyncio
    async def test_revoked_cert_accepted_without_crl(
        self, tls_fixture: _TLSFixture,
    ) -> None:
        """Without a CRL loaded, a revoked cert is accepted (no revocation check).

        This documents the difference: CRL enforcement is opt-in via
        the _CRLBroker subclass.
        """
        tls_config = tls_fixture.make_tls_config(with_crl=False)
        broker = MQTTBroker(
            mqtt_port=0, mqtt_tls_port=0,
            tls_config=tls_config,
            use_owntracks_handler=False,
        )
        try:
            await broker.start()
            tls_port = broker.actual_tls_port
            assert_that(tls_port, is_(not_none()))

            ctx = tls_fixture.client_ssl_context(
                tls_fixture.revoked_cert_file,
                tls_fixture.revoked_key_file,
            )
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", tls_port, ssl=ctx,
            )
            writer.close()
            await writer.wait_closed()
        finally:
            if broker.is_running:
                await broker.stop()
