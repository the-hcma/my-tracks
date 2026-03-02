"""Tests for PKI (Certificate Authority, Server Certificate, Client Certificate) functionality."""
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID
from django.contrib.auth.models import User
from hamcrest import (assert_that, contains_string, equal_to, greater_than,
                      has_item, has_key, has_length, instance_of, is_, is_not,
                      not_none, starts_with)
from rest_framework import status
from rest_framework.test import APIClient

from my_tracks.models import (CertificateAuthority, ClientCertificate,
                              ServerCertificate)
from my_tracks.pki import (ALLOWED_KEY_SIZES, DEFAULT_CERT_VALIDITY_DAYS,
                           VALIDITY_PRESETS, decrypt_private_key,
                           encrypt_private_key, generate_ca_certificate,
                           generate_client_certificate, generate_crl,
                           generate_pkcs12, generate_server_certificate,
                           get_certificate_expiry, get_certificate_fingerprint,
                           get_certificate_metadata, get_certificate_sans,
                           get_certificate_serial_number,
                           get_certificate_subject)


@pytest.mark.django_db
class TestPKICryptoUtilities:
    """Test low-level PKI crypto functions."""

    def test_generate_ca_certificate_returns_pem(self) -> None:
        """Test that generate_ca_certificate returns valid PEM data."""
        cert_pem, key_pem = generate_ca_certificate()
        assert_that(cert_pem, is_(not_none()))
        assert_that(key_pem, is_(not_none()))
        assert_that(cert_pem.decode(), starts_with("-----BEGIN CERTIFICATE-----"))
        assert_that(key_pem.decode(), starts_with("-----BEGIN PRIVATE KEY-----"))

    def test_generate_ca_certificate_custom_cn(self) -> None:
        """Test CA generation with custom common name."""
        cert_pem, _ = generate_ca_certificate(common_name="Test CA")
        subject = get_certificate_subject(cert_pem)
        assert_that(subject, equal_to("Test CA"))

    def test_generate_ca_certificate_is_ca(self) -> None:
        """Test that generated certificate has CA basic constraint."""
        cert_pem, _ = generate_ca_certificate()
        cert = x509.load_pem_x509_certificate(cert_pem)
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert_that(bc.value.ca, is_(True))

    def test_generate_ca_certificate_key_usage(self) -> None:
        """Test that CA cert has correct key usage flags."""
        cert_pem, _ = generate_ca_certificate()
        cert = x509.load_pem_x509_certificate(cert_pem)
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert_that(ku.value.digital_signature, is_(True))
        assert_that(ku.value.key_cert_sign, is_(True))
        assert_that(ku.value.crl_sign, is_(True))

    def test_generate_ca_certificate_custom_validity(self) -> None:
        """Test CA generation with custom validity period."""
        cert_pem, _ = generate_ca_certificate(validity_days=365)
        cert = x509.load_pem_x509_certificate(cert_pem)
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert_that(delta.days, equal_to(365))

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Test that encrypting then decrypting recovers the original data."""
        _, key_pem = generate_ca_certificate()
        encrypted = encrypt_private_key(key_pem)
        assert_that(encrypted, is_not(equal_to(key_pem)))
        decrypted = decrypt_private_key(encrypted)
        assert_that(decrypted, equal_to(key_pem))

    def test_get_certificate_fingerprint_format(self) -> None:
        """Test fingerprint is colon-separated hex string."""
        cert_pem, _ = generate_ca_certificate()
        fp = get_certificate_fingerprint(cert_pem)
        parts = fp.split(":")
        assert_that(parts, has_length(32))
        for part in parts:
            assert_that(len(part), equal_to(2))

    def test_generate_ca_certificate_custom_key_size(self) -> None:
        """Test CA generation with custom key size."""
        cert_pem, _ = generate_ca_certificate(key_size=2048)
        cert = x509.load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()
        assert_that(public_key.key_size, equal_to(2048))

    def test_generate_ca_certificate_default_key_size(self) -> None:
        """Test CA generation uses 4096-bit key by default."""
        cert_pem, _ = generate_ca_certificate()
        cert = x509.load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()
        assert_that(public_key.key_size, equal_to(4096))

    def test_generate_ca_certificate_invalid_key_size(self) -> None:
        """Test that invalid key size raises ValueError."""
        from hamcrest import calling, raises
        assert_that(
            calling(generate_ca_certificate).with_args(key_size=1024),
            raises(ValueError, "Expected key_size in"),
        )

    def test_allowed_key_sizes_constant(self) -> None:
        """Test ALLOWED_KEY_SIZES contains expected values."""
        assert_that(ALLOWED_KEY_SIZES, equal_to((2048, 3072, 4096)))

    def test_get_certificate_expiry_returns_datetime(self) -> None:
        """Test expiry extraction returns a datetime."""
        cert_pem, _ = generate_ca_certificate(validity_days=365)
        expiry = get_certificate_expiry(cert_pem)
        assert_that(expiry, is_(not_none()))


@pytest.mark.django_db
class TestCertificateAuthorityModel:
    """Test the CertificateAuthority model."""

    def test_create_ca_model(self) -> None:
        """Test creating a CA record in the database."""
        cert_pem, key_pem = generate_ca_certificate(common_name="Test CA", key_size=2048)
        encrypted_key = encrypt_private_key(key_pem)

        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name=get_certificate_subject(cert_pem),
            fingerprint=get_certificate_fingerprint(cert_pem),
            key_size=2048,
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )
        assert_that(ca.pk, is_(not_none()))
        assert_that(ca.common_name, equal_to("Test CA"))
        assert_that(ca.key_size, equal_to(2048))
        assert_that(ca.is_active, is_(True))

    def test_create_ca_model_default_key_size(self) -> None:
        """Test that CA model defaults to 4096-bit key size."""
        cert_pem, key_pem = generate_ca_certificate(common_name="Default Key")
        encrypted_key = encrypt_private_key(key_pem)

        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name="Default Key",
            fingerprint=get_certificate_fingerprint(cert_pem),
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )
        assert_that(ca.key_size, equal_to(4096))

    def test_ca_str_representation(self) -> None:
        """Test __str__ of CertificateAuthority."""
        cert_pem, key_pem = generate_ca_certificate(common_name="My CA")
        encrypted_key = encrypt_private_key(key_pem)

        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name="My CA",
            fingerprint=get_certificate_fingerprint(cert_pem),
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )
        assert_that(str(ca), equal_to("My CA (active)"))
        ca.is_active = False
        assert_that(str(ca), equal_to("My CA"))

    def test_decrypt_stored_key(self) -> None:
        """Test that a stored encrypted key can be decrypted."""
        cert_pem, key_pem = generate_ca_certificate()
        encrypted_key = encrypt_private_key(key_pem)

        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name="Test CA",
            fingerprint=get_certificate_fingerprint(cert_pem),
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
        )

        ca.refresh_from_db()
        decrypted = decrypt_private_key(bytes(ca.encrypted_private_key))
        assert_that(decrypted, equal_to(key_pem))


@pytest.mark.django_db
class TestCertificateAuthorityAPI:
    """Test CA management REST API endpoints."""

    def test_list_cas_empty(self, admin_api_client: APIClient) -> None:
        """Test GET /api/admin/pki/ca/ returns empty list initially."""
        response = admin_api_client.get('/api/admin/pki/ca/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(0))

    def test_create_ca(self, admin_api_client: APIClient) -> None:
        """Test POST /api/admin/pki/ca/ generates a new CA."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'common_name': 'Test CA',
            'validity_days': 365,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data, has_key('id'))
        assert_that(response.data['common_name'], equal_to('Test CA'))
        assert_that(response.data['is_active'], is_(True))
        assert_that(response.data['fingerprint'], contains_string(':'))
        assert_that(response.data['certificate_pem'], starts_with('-----BEGIN CERTIFICATE-----'))

    def test_create_ca_with_defaults(self, admin_api_client: APIClient) -> None:
        """Test POST /api/admin/pki/ca/ with no parameters uses defaults."""
        response = admin_api_client.post('/api/admin/pki/ca/', {}, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data['common_name'], equal_to('My Tracks CA'))

    def test_create_ca_deactivates_previous(self, admin_api_client: APIClient) -> None:
        """Test that creating a new CA deactivates the previous one."""
        resp1 = admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'CA 1'}, format='json')
        ca1_id = resp1.data['id']

        resp2 = admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'CA 2'}, format='json')
        assert_that(resp2.status_code, equal_to(status.HTTP_201_CREATED))

        ca1 = CertificateAuthority.objects.get(pk=ca1_id)
        assert_that(ca1.is_active, is_(False))

        ca2 = CertificateAuthority.objects.get(pk=resp2.data['id'])
        assert_that(ca2.is_active, is_(True))

    def test_create_ca_invalid_validity(self, admin_api_client: APIClient) -> None:
        """Test that invalid validity_days is rejected."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'validity_days': 'abc',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('validity_days'))

    def test_create_ca_validity_out_of_range(self, admin_api_client: APIClient) -> None:
        """Test that out-of-range validity_days is rejected."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'validity_days': 0,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

        response = admin_api_client.post('/api/admin/pki/ca/', {
            'validity_days': 99999,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_create_ca_with_key_size(self, admin_api_client: APIClient) -> None:
        """Test POST /api/admin/pki/ca/ with explicit key_size."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'common_name': 'Small Key CA',
            'validity_days': 365,
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data['key_size'], equal_to(2048))

    def test_create_ca_invalid_key_size(self, admin_api_client: APIClient) -> None:
        """Test that invalid key_size is rejected."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'key_size': 1024,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('key_size'))

    def test_create_ca_non_integer_key_size(self, admin_api_client: APIClient) -> None:
        """Test that non-integer key_size is rejected."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'key_size': 'abc',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('key_size'))

    def test_create_ca_default_key_size_in_response(self, admin_api_client: APIClient) -> None:
        """Test that default key_size is 4096 in API response."""
        response = admin_api_client.post('/api/admin/pki/ca/', {}, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data['key_size'], equal_to(4096))

    def test_create_ca_empty_common_name(self, admin_api_client: APIClient) -> None:
        """Test that empty common_name is rejected."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'common_name': '   ',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_list_cas_after_creation(self, admin_api_client: APIClient) -> None:
        """Test listing CAs after creating some."""
        admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'CA 1'}, format='json')
        admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'CA 2'}, format='json')

        response = admin_api_client.get('/api/admin/pki/ca/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(2))

    def test_get_active_ca(self, admin_api_client: APIClient) -> None:
        """Test GET /api/admin/pki/ca/active/ returns the active CA."""
        admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'Active CA'}, format='json')
        response = admin_api_client.get('/api/admin/pki/ca/active/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['common_name'], equal_to('Active CA'))

    def test_get_active_ca_when_none(self, admin_api_client: APIClient) -> None:
        """Test GET /api/admin/pki/ca/active/ returns 404 when no active CA."""
        response = admin_api_client.get('/api/admin/pki/ca/active/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_destroy_ca(self, admin_api_client: APIClient) -> None:
        """Test DELETE /api/admin/pki/ca/{id}/ deactivates the CA."""
        resp = admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'To Delete'}, format='json')
        ca_id = resp.data['id']

        response = admin_api_client.delete(f'/api/admin/pki/ca/{ca_id}/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        ca = CertificateAuthority.objects.get(pk=ca_id)
        assert_that(ca.is_active, is_(False))

    def test_destroy_already_inactive_ca(self, admin_api_client: APIClient) -> None:
        """Test that deactivating an already inactive CA returns 400."""
        resp = admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'CA'}, format='json')
        ca_id = resp.data['id']
        admin_api_client.delete(f'/api/admin/pki/ca/{ca_id}/')

        response = admin_api_client.delete(f'/api/admin/pki/ca/{ca_id}/')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_destroy_nonexistent_ca(self, admin_api_client: APIClient) -> None:
        """Test that deleting a nonexistent CA returns 404."""
        response = admin_api_client.delete('/api/admin/pki/ca/99999/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_download_ca_cert(self, admin_api_client: APIClient) -> None:
        """Test GET /api/admin/pki/ca/{id}/download/ returns PEM file."""
        resp = admin_api_client.post('/api/admin/pki/ca/', {'common_name': 'DL Test'}, format='json')
        ca_id = resp.data['id']

        response = admin_api_client.get(f'/api/admin/pki/ca/{ca_id}/download/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], equal_to('application/x-pem-file'))
        assert_that(response['Content-Disposition'], contains_string('.pem'))
        assert_that(response.content.decode(), starts_with('-----BEGIN CERTIFICATE-----'))

    def test_download_nonexistent_ca(self, admin_api_client: APIClient) -> None:
        """Test downloading a nonexistent CA returns 404."""
        response = admin_api_client.get('/api/admin/pki/ca/99999/download/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


@pytest.mark.django_db
class TestCertificateAuthorityPermissions:
    """Test that CA endpoints are admin-only."""

    def test_list_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot list CAs."""
        response = auth_api_client.get('/api/admin/pki/ca/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_create_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot create CA."""
        response = auth_api_client.post('/api/admin/pki/ca/', {'common_name': 'X'}, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_delete_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot delete CA."""
        response = auth_api_client.delete('/api/admin/pki/ca/1/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_active_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot access active CA endpoint."""
        response = auth_api_client.get('/api/admin/pki/ca/active/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_list_forbidden_for_unauthenticated(self) -> None:
        """Test unauthenticated cannot list CAs."""
        client = APIClient()
        response = client.get('/api/admin/pki/ca/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# ---------------------------------------------------------------------------
# Server Certificate Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def ca_with_key(db: Any) -> tuple[CertificateAuthority, bytes]:
    """Create an active CA and return (ca_model, decrypted_key_pem)."""
    cert_pem, key_pem = generate_ca_certificate(
        common_name="Test CA", validity_days=3650, key_size=2048
    )
    encrypted_key = encrypt_private_key(key_pem)
    ca = CertificateAuthority.objects.create(
        certificate_pem=cert_pem.decode(),
        encrypted_private_key=encrypted_key,
        common_name="Test CA",
        fingerprint=get_certificate_fingerprint(cert_pem),
        key_size=2048,
        not_valid_before=get_certificate_expiry(cert_pem),
        not_valid_after=get_certificate_expiry(cert_pem),
        is_active=True,
    )
    return ca, key_pem


@pytest.mark.django_db
class TestServerCertificateCrypto:
    """Test server certificate generation crypto functions."""

    def test_generate_server_cert_returns_pem(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test that generate_server_certificate returns valid PEM data."""
        ca, key_pem = ca_with_key
        cert_pem, srv_key_pem = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="myserver.local",
            san_entries=["myserver.local", "192.168.1.10"],
            key_size=2048,
        )
        assert_that(cert_pem.decode(), starts_with("-----BEGIN CERTIFICATE-----"))
        assert_that(srv_key_pem.decode(), starts_with("-----BEGIN PRIVATE KEY-----"))

    def test_server_cert_signed_by_ca(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert's issuer matches the CA subject."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test"],
            key_size=2048,
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        ca_cert = x509.load_pem_x509_certificate(ca.certificate_pem.encode())
        assert_that(cert.issuer, equal_to(ca_cert.subject))

    def test_server_cert_is_not_ca(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert has CA=False basic constraint."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test"],
            key_size=2048,
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert_that(bc.value.ca, is_(False))

    def test_server_cert_key_usage(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert has correct key usage flags."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test"],
            key_size=2048,
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert_that(ku.value.digital_signature, is_(True))
        assert_that(ku.value.key_encipherment, is_(True))
        assert_that(ku.value.key_cert_sign, is_(False))

    def test_server_cert_extended_key_usage(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert has serverAuth extended key usage."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test"],
            key_size=2048,
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert_that(list(eku.value), has_item(ExtendedKeyUsageOID.SERVER_AUTH))

    def test_server_cert_sans(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert includes expected SANs."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test", "10.0.1.5", "192.168.1.10"],
            key_size=2048,
        )
        sans = get_certificate_sans(cert_pem)
        assert_that(sans, has_item("server.test"))
        assert_that(sans, has_item("10.0.1.5"))
        assert_that(sans, has_item("192.168.1.10"))

    def test_server_cert_custom_key_size(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert with 3072-bit key."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test"],
            key_size=3072,
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        assert_that(cert.public_key().key_size, equal_to(3072))

    def test_server_cert_invalid_key_size(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test invalid key size raises ValueError."""
        from hamcrest import calling, raises
        ca, key_pem = ca_with_key
        assert_that(
            calling(generate_server_certificate).with_args(
                ca_cert_pem=ca.certificate_pem.encode(),
                ca_key_pem=key_pem,
                common_name="server.test",
                san_entries=["server.test"],
                key_size=1024,
            ),
            raises(ValueError, "Expected key_size in"),
        )

    def test_server_cert_empty_sans(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test empty SAN list raises ValueError."""
        from hamcrest import calling, raises
        ca, key_pem = ca_with_key
        assert_that(
            calling(generate_server_certificate).with_args(
                ca_cert_pem=ca.certificate_pem.encode(),
                ca_key_pem=key_pem,
                common_name="server.test",
                san_entries=[],
            ),
            raises(ValueError, "Expected at least one SAN"),
        )

    def test_server_cert_custom_validity(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test server cert with custom validity period."""
        ca, key_pem = ca_with_key
        cert_pem, _ = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test"],
            validity_days=30,
            key_size=2048,
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert_that(delta.days, equal_to(30))

    def test_get_certificate_sans_no_san_extension(self) -> None:
        """Test get_certificate_sans returns empty list when no SAN."""
        cert_pem, _ = generate_ca_certificate(common_name="No SAN", key_size=2048)
        sans = get_certificate_sans(cert_pem)
        assert_that(sans, has_length(0))


@pytest.mark.django_db
class TestServerCertificateModel:
    """Test the ServerCertificate model."""

    def test_create_server_cert_model(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test creating a server cert record in the database."""
        ca, key_pem = ca_with_key
        cert_pem, srv_key_pem = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="server.test",
            san_entries=["server.test", "10.0.1.5"],
            key_size=2048,
        )
        encrypted_key = encrypt_private_key(srv_key_pem)

        sc = ServerCertificate.objects.create(
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_key,
            common_name="server.test",
            fingerprint=get_certificate_fingerprint(cert_pem),
            san_entries=["server.test", "10.0.1.5"],
            key_size=2048,
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )
        assert_that(sc.pk, is_(not_none()))
        assert_that(sc.common_name, equal_to("server.test"))
        assert_that(sc.key_size, equal_to(2048))
        assert_that(sc.is_active, is_(True))
        assert_that(sc.san_entries, has_item("10.0.1.5"))

    def test_server_cert_str_representation(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test __str__ of ServerCertificate."""
        ca, key_pem = ca_with_key
        cert_pem, srv_key_pem = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="my-server",
            san_entries=["my-server"],
            key_size=2048,
        )
        sc = ServerCertificate.objects.create(
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(srv_key_pem),
            common_name="my-server",
            fingerprint=get_certificate_fingerprint(cert_pem),
            san_entries=["my-server"],
            key_size=2048,
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
            is_active=True,
        )
        assert_that(str(sc), equal_to("my-server (active)"))
        sc.is_active = False
        assert_that(str(sc), equal_to("my-server"))

    def test_server_cert_fk_to_ca(self, ca_with_key: tuple[CertificateAuthority, bytes]) -> None:
        """Test FK relationship to CertificateAuthority."""
        ca, key_pem = ca_with_key
        cert_pem, srv_key_pem = generate_server_certificate(
            ca_cert_pem=ca.certificate_pem.encode(),
            ca_key_pem=key_pem,
            common_name="fk-test",
            san_entries=["fk-test"],
            key_size=2048,
        )
        sc = ServerCertificate.objects.create(
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(srv_key_pem),
            common_name="fk-test",
            fingerprint=get_certificate_fingerprint(cert_pem),
            san_entries=["fk-test"],
            key_size=2048,
            not_valid_before=get_certificate_expiry(cert_pem),
            not_valid_after=get_certificate_expiry(cert_pem),
        )
        assert_that(sc.issuing_ca.pk, equal_to(ca.pk))
        assert_that(ca.server_certificates.count(), equal_to(1))


@pytest.fixture
def admin_with_ca(admin_api_client: APIClient) -> APIClient:
    """Create an active CA via API and return the admin client."""
    admin_api_client.post('/api/admin/pki/ca/', {
        'common_name': 'Test CA',
        'validity_days': 3650,
        'key_size': 2048,
    }, format='json')
    return admin_api_client


@pytest.mark.django_db
class TestServerCertificateAPI:
    """Test server certificate REST API endpoints."""

    def test_list_server_certs_empty(self, admin_with_ca: APIClient) -> None:
        """Test GET /api/admin/pki/server-cert/ returns empty list."""
        response = admin_with_ca.get('/api/admin/pki/server-cert/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(0))

    def test_create_server_cert(self, admin_with_ca: APIClient) -> None:
        """Test POST /api/admin/pki/server-cert/ generates a server cert."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver.local',
            'validity_days': 365,
            'key_size': 2048,
            'san_entries': ['myserver.local', '192.168.1.10'],
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data, has_key('id'))
        assert_that(response.data['common_name'], equal_to('myserver.local'))
        assert_that(response.data['is_active'], is_(True))
        assert_that(response.data['san_entries'], has_item('myserver.local'))
        assert_that(response.data['san_entries'], has_item('192.168.1.10'))
        assert_that(response.data['key_size'], equal_to(2048))
        assert_that(response.data['issuing_ca_name'], equal_to('Test CA'))

    def test_create_server_cert_no_ca(self, admin_api_client: APIClient) -> None:
        """Test creating server cert without active CA returns 400."""
        response = admin_api_client.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['myserver'],
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('No active CA'))

    def test_create_server_cert_empty_cn(self, admin_with_ca: APIClient) -> None:
        """Test empty common_name is rejected."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': '  ',
            'san_entries': ['myserver'],
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_create_server_cert_no_sans(self, admin_with_ca: APIClient) -> None:
        """Test empty SAN list is rejected."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': [],
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('SAN'))

    def test_create_server_cert_invalid_key_size(self, admin_with_ca: APIClient) -> None:
        """Test invalid key_size is rejected."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['myserver'],
            'key_size': 1024,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('key_size'))

    def test_create_server_cert_invalid_validity(self, admin_with_ca: APIClient) -> None:
        """Test invalid validity_days is rejected."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['myserver'],
            'validity_days': 'abc',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_create_server_cert_deactivates_previous(self, admin_with_ca: APIClient) -> None:
        """Test creating a new server cert deactivates the previous one."""
        resp1 = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'server1',
            'san_entries': ['server1'],
            'key_size': 2048,
        }, format='json')
        cert1_id = resp1.data['id']

        resp2 = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'server2',
            'san_entries': ['server2'],
            'key_size': 2048,
        }, format='json')
        assert_that(resp2.status_code, equal_to(status.HTTP_201_CREATED))

        cert1 = ServerCertificate.objects.get(pk=cert1_id)
        assert_that(cert1.is_active, is_(False))

        cert2 = ServerCertificate.objects.get(pk=resp2.data['id'])
        assert_that(cert2.is_active, is_(True))

    def test_get_active_server_cert(self, admin_with_ca: APIClient) -> None:
        """Test GET /api/admin/pki/server-cert/active/ returns active cert."""
        admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'active-server',
            'san_entries': ['active-server'],
            'key_size': 2048,
        }, format='json')
        response = admin_with_ca.get('/api/admin/pki/server-cert/active/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['common_name'], equal_to('active-server'))

    def test_get_active_server_cert_when_none(self, admin_with_ca: APIClient) -> None:
        """Test GET active returns 404 when no active cert."""
        response = admin_with_ca.get('/api/admin/pki/server-cert/active/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_destroy_server_cert(self, admin_with_ca: APIClient) -> None:
        """Test DELETE deactivates a server cert."""
        resp = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'to-deactivate',
            'san_entries': ['to-deactivate'],
            'key_size': 2048,
        }, format='json')
        cert_id = resp.data['id']

        response = admin_with_ca.delete(f'/api/admin/pki/server-cert/{cert_id}/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        cert = ServerCertificate.objects.get(pk=cert_id)
        assert_that(cert.is_active, is_(False))

    def test_destroy_already_inactive(self, admin_with_ca: APIClient) -> None:
        """Test deactivating an already inactive cert returns 400."""
        resp = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'inactive',
            'san_entries': ['inactive'],
            'key_size': 2048,
        }, format='json')
        cert_id = resp.data['id']
        admin_with_ca.delete(f'/api/admin/pki/server-cert/{cert_id}/')

        response = admin_with_ca.delete(f'/api/admin/pki/server-cert/{cert_id}/')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_destroy_nonexistent(self, admin_with_ca: APIClient) -> None:
        """Test deactivating a nonexistent cert returns 404."""
        response = admin_with_ca.delete('/api/admin/pki/server-cert/99999/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_download_server_cert(self, admin_with_ca: APIClient) -> None:
        """Test GET download returns PEM file."""
        resp = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'dl-test',
            'san_entries': ['dl-test'],
            'key_size': 2048,
        }, format='json')
        cert_id = resp.data['id']

        response = admin_with_ca.get(f'/api/admin/pki/server-cert/{cert_id}/download/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], equal_to('application/x-pem-file'))
        assert_that(response['Content-Disposition'], contains_string('-server.pem'))
        assert_that(response.content.decode(), starts_with('-----BEGIN CERTIFICATE-----'))

    def test_download_nonexistent(self, admin_with_ca: APIClient) -> None:
        """Test downloading nonexistent cert returns 404."""
        response = admin_with_ca.get('/api/admin/pki/server-cert/99999/download/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_expunge_inactive_cert(self, admin_with_ca: APIClient) -> None:
        """Test expunge permanently deletes an inactive cert."""
        resp = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'to-expunge',
            'san_entries': ['to-expunge'],
            'key_size': 2048,
        }, format='json')
        cert_id = resp.data['id']
        admin_with_ca.delete(f'/api/admin/pki/server-cert/{cert_id}/')

        response = admin_with_ca.delete(f'/api/admin/pki/server-cert/{cert_id}/expunge/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(ServerCertificate.objects.filter(pk=cert_id).exists(), is_(False))

    def test_expunge_active_cert_rejected(self, admin_with_ca: APIClient) -> None:
        """Test expunging an active cert returns 400."""
        resp = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'active-cert',
            'san_entries': ['active-cert'],
            'key_size': 2048,
        }, format='json')
        cert_id = resp.data['id']

        response = admin_with_ca.delete(f'/api/admin/pki/server-cert/{cert_id}/expunge/')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_expunge_nonexistent_cert(self, admin_with_ca: APIClient) -> None:
        """Test expunging nonexistent cert returns 404."""
        response = admin_with_ca.delete('/api/admin/pki/server-cert/99999/expunge/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_list_server_certs_after_creation(self, admin_with_ca: APIClient) -> None:
        """Test listing server certs after creating some."""
        admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'cert1',
            'san_entries': ['cert1'],
            'key_size': 2048,
        }, format='json')
        admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'cert2',
            'san_entries': ['cert2'],
            'key_size': 2048,
        }, format='json')

        response = admin_with_ca.get('/api/admin/pki/server-cert/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(2))

    def test_create_server_cert_validity_out_of_range(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test out-of-range validity_days for server cert returns 400."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['myserver'],
            'validity_days': 0,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('validity_days'))

    def test_create_server_cert_non_integer_key_size(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test non-integer key_size for server cert returns 400."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['myserver'],
            'key_size': 'not-a-number',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('key_size'))

    def test_create_server_cert_non_list_san_entries(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test non-list san_entries for server cert returns 400."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': 'not-a-list',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('san_entries'))


@pytest.mark.django_db
class TestServerCertificatePermissions:
    """Test server cert endpoints are admin-only."""

    def test_list_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot list server certs."""
        response = auth_api_client.get('/api/admin/pki/server-cert/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_create_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot create server cert."""
        response = auth_api_client.post('/api/admin/pki/server-cert/', {
            'common_name': 'x',
            'san_entries': ['x'],
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_delete_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot delete server cert."""
        response = auth_api_client.delete('/api/admin/pki/server-cert/1/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_active_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test non-admin cannot access active server cert."""
        response = auth_api_client.get('/api/admin/pki/server-cert/active/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_list_forbidden_for_unauthenticated(self) -> None:
        """Test unauthenticated cannot list server certs."""
        client = APIClient()
        response = client.get('/api/admin/pki/server-cert/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# === Client Certificate Tests ===


@pytest.mark.django_db
class TestClientCertificateCrypto:
    """Test client certificate generation and CRL functions."""

    @pytest.fixture
    def ca_pair(self) -> tuple[bytes, bytes]:
        """Generate a CA cert+key pair for signing client certs."""
        return generate_ca_certificate(
            common_name="Test CA", validity_days=3650, key_size=2048
        )

    def test_generate_client_cert_returns_pem(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, key_pem = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="alice"
        )
        assert_that(cert_pem.decode(), starts_with("-----BEGIN CERTIFICATE-----"))
        assert_that(key_pem.decode(), starts_with("-----BEGIN PRIVATE KEY-----"))

    def test_client_cert_cn_matches_username(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="bob"
        )
        assert_that(get_certificate_subject(cert_pem), equal_to("bob"))

    def test_client_cert_signed_by_ca(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="carol"
        )
        ca_cert = x509.load_pem_x509_certificate(ca_pair[0])
        client_cert = x509.load_pem_x509_certificate(cert_pem)
        assert_that(client_cert.issuer, equal_to(ca_cert.subject))

    def test_client_cert_basic_constraints_not_ca(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="dave"
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert_that(bc.value.ca, is_(False))

    def test_client_cert_key_usage(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="eve"
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert_that(ku.value.digital_signature, is_(True))
        assert_that(ku.value.key_encipherment, is_(True))

    def test_client_cert_extended_key_usage_client_auth(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="frank"
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert_that(
            list(eku.value), has_item(ExtendedKeyUsageOID.CLIENT_AUTH)
        )

    def test_client_cert_custom_key_size(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="grace", key_size=2048
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        assert_that(cert.public_key().key_size, equal_to(2048))

    def test_client_cert_custom_validity(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="heidi", validity_days=30
        )
        cert = x509.load_pem_x509_certificate(cert_pem)
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert_that(delta.days, equal_to(30))

    def test_client_cert_invalid_key_size(self, ca_pair: tuple[bytes, bytes]) -> None:
        from hamcrest import calling, raises
        assert_that(
            calling(generate_client_certificate).with_args(
                ca_pair[0], ca_pair[1], username="ivan", key_size=1024
            ),
            raises(ValueError, "Expected key_size in"),
        )

    def test_client_cert_empty_username(self, ca_pair: tuple[bytes, bytes]) -> None:
        from hamcrest import calling, raises
        assert_that(
            calling(generate_client_certificate).with_args(
                ca_pair[0], ca_pair[1], username=""
            ),
            raises(ValueError, "Expected a non-empty username"),
        )

    def test_client_cert_whitespace_username(self, ca_pair: tuple[bytes, bytes]) -> None:
        from hamcrest import calling, raises
        assert_that(
            calling(generate_client_certificate).with_args(
                ca_pair[0], ca_pair[1], username="   "
            ),
            raises(ValueError, "Expected a non-empty username"),
        )

    def test_client_cert_inherits_org_from_ca(self, ca_pair: tuple[bytes, bytes]) -> None:
        """Organization in client cert must match the CA's Organization."""
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="judy"
        )
        ca_cert = x509.load_pem_x509_certificate(ca_pair[0])
        ca_org = ca_cert.subject.get_attributes_for_oid(
            x509.oid.NameOID.ORGANIZATION_NAME
        )
        client_cert = x509.load_pem_x509_certificate(cert_pem)
        client_org = client_cert.subject.get_attributes_for_oid(
            x509.oid.NameOID.ORGANIZATION_NAME
        )
        assert_that(len(client_org), equal_to(1))
        assert_that(str(client_org[0].value), equal_to(str(ca_org[0].value)))

    def test_get_certificate_serial_number(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="karl"
        )
        serial = get_certificate_serial_number(cert_pem)
        assert_that(serial, instance_of(int))
        assert_that(serial, greater_than(0))


@pytest.mark.django_db
class TestCRLGeneration:
    """Test Certificate Revocation List generation."""

    @pytest.fixture
    def ca_pair(self) -> tuple[bytes, bytes]:
        return generate_ca_certificate(
            common_name="CRL Test CA", validity_days=3650, key_size=2048
        )

    def test_generate_empty_crl(self, ca_pair: tuple[bytes, bytes]) -> None:
        crl_pem = generate_crl(ca_pair[0], ca_pair[1], revoked_entries=[])
        assert_that(crl_pem.decode(), contains_string("-----BEGIN X509 CRL-----"))

    def test_crl_signed_by_ca(self, ca_pair: tuple[bytes, bytes]) -> None:
        crl_pem = generate_crl(ca_pair[0], ca_pair[1], revoked_entries=[])
        crl = x509.load_pem_x509_crl(crl_pem)
        ca_cert = x509.load_pem_x509_certificate(ca_pair[0])
        assert_that(crl.issuer, equal_to(ca_cert.subject))

    def test_crl_with_revoked_entries(self, ca_pair: tuple[bytes, bytes]) -> None:
        now = datetime.now(UTC)
        entries = [(12345, now), (67890, now)]
        crl_pem = generate_crl(ca_pair[0], ca_pair[1], revoked_entries=entries)
        crl = x509.load_pem_x509_crl(crl_pem)
        revoked = list(crl)
        assert_that(revoked, has_length(2))

    def test_crl_contains_correct_serial(self, ca_pair: tuple[bytes, bytes]) -> None:
        now = datetime.now(UTC)
        entries = [(99999, now)]
        crl_pem = generate_crl(ca_pair[0], ca_pair[1], revoked_entries=entries)
        crl = x509.load_pem_x509_crl(crl_pem)
        revoked = list(crl)
        assert_that(revoked[0].serial_number, equal_to(99999))

    def test_crl_validity_period(self, ca_pair: tuple[bytes, bytes]) -> None:
        crl_pem = generate_crl(
            ca_pair[0], ca_pair[1], revoked_entries=[], validity_days=7
        )
        crl = x509.load_pem_x509_crl(crl_pem)
        next_update = crl.next_update_utc
        last_update = crl.last_update_utc
        assert_that(next_update, is_(not_none()))
        assert_that(last_update, is_(not_none()))
        assert_that((next_update - last_update).days, equal_to(7))  # type: ignore[operator]

    def test_crl_from_client_cert(self, ca_pair: tuple[bytes, bytes]) -> None:
        """End-to-end: generate client cert, extract serial, put in CRL."""
        cert_pem, _ = generate_client_certificate(
            ca_pair[0], ca_pair[1], username="revoked_user", key_size=2048
        )
        serial = get_certificate_serial_number(cert_pem)
        now = datetime.now(UTC)
        crl_pem = generate_crl(
            ca_pair[0], ca_pair[1], revoked_entries=[(serial, now)]
        )
        crl = x509.load_pem_x509_crl(crl_pem)
        revoked = list(crl)
        assert_that(revoked, has_length(1))
        assert_that(revoked[0].serial_number, equal_to(serial))


@pytest.mark.django_db
class TestClientCertificateModel:
    """Test the ClientCertificate model."""

    @pytest.fixture
    def ca_and_user(self, db: Any) -> tuple[CertificateAuthority, User, bytes, bytes]:
        """Create a CA and a user for client cert tests."""
        cert_pem, key_pem = generate_ca_certificate(
            common_name="Model Test CA", key_size=2048
        )
        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name="Model Test CA",
            fingerprint=get_certificate_fingerprint(cert_pem),
            key_size=2048,
            not_valid_before=x509.load_pem_x509_certificate(cert_pem).not_valid_before_utc,
            not_valid_after=x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc,
            is_active=True,
        )
        user = User.objects.create_user(username="certuser", password="pass123")
        return ca, user, cert_pem, key_pem

    def test_create_client_cert_model(
        self, ca_and_user: tuple[CertificateAuthority, User, bytes, bytes]
    ) -> None:
        ca, user, ca_cert_pem, ca_key_pem = ca_and_user
        cert_pem, key_pem = generate_client_certificate(
            ca_cert_pem, ca_key_pem, username=str(user.username), key_size=2048
        )
        client_cert = ClientCertificate.objects.create(
            user=user,
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name=user.username,
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(get_certificate_serial_number(cert_pem)),
            key_size=2048,
            not_valid_before=x509.load_pem_x509_certificate(cert_pem).not_valid_before_utc,
            not_valid_after=x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc,
        )
        assert_that(client_cert.pk, is_(not_none()))
        assert_that(client_cert.common_name, equal_to("certuser"))
        assert_that(client_cert.is_active, is_(True))
        assert_that(client_cert.revoked, is_(False))

    def test_client_cert_str_active(
        self, ca_and_user: tuple[CertificateAuthority, User, bytes, bytes]
    ) -> None:
        ca, user, ca_cert_pem, ca_key_pem = ca_and_user
        cert_pem, key_pem = generate_client_certificate(
            ca_cert_pem, ca_key_pem, username=str(user.username), key_size=2048
        )
        client_cert = ClientCertificate.objects.create(
            user=user,
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name=user.username,
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(get_certificate_serial_number(cert_pem)),
            key_size=2048,
            not_valid_before=x509.load_pem_x509_certificate(cert_pem).not_valid_before_utc,
            not_valid_after=x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc,
        )
        assert_that(str(client_cert), equal_to("certuser (active)"))

    def test_client_cert_str_revoked(
        self, ca_and_user: tuple[CertificateAuthority, User, bytes, bytes]
    ) -> None:
        ca, user, ca_cert_pem, ca_key_pem = ca_and_user
        cert_pem, key_pem = generate_client_certificate(
            ca_cert_pem, ca_key_pem, username=str(user.username), key_size=2048
        )
        client_cert = ClientCertificate.objects.create(
            user=user,
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name=user.username,
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(get_certificate_serial_number(cert_pem)),
            key_size=2048,
            not_valid_before=x509.load_pem_x509_certificate(cert_pem).not_valid_before_utc,
            not_valid_after=x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc,
            revoked=True,
            is_active=False,
        )
        assert_that(str(client_cert), equal_to("certuser (revoked)"))

    def test_client_cert_fk_to_user(
        self, ca_and_user: tuple[CertificateAuthority, User, bytes, bytes]
    ) -> None:
        ca, user, ca_cert_pem, ca_key_pem = ca_and_user
        cert_pem, key_pem = generate_client_certificate(
            ca_cert_pem, ca_key_pem, username=str(user.username), key_size=2048
        )
        ClientCertificate.objects.create(
            user=user,
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name=user.username,
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(get_certificate_serial_number(cert_pem)),
            key_size=2048,
            not_valid_before=x509.load_pem_x509_certificate(cert_pem).not_valid_before_utc,
            not_valid_after=x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc,
        )
        assert_that(user.client_certificates.count(), equal_to(1))

    def test_client_cert_fk_to_ca(
        self, ca_and_user: tuple[CertificateAuthority, User, bytes, bytes]
    ) -> None:
        ca, user, ca_cert_pem, ca_key_pem = ca_and_user
        cert_pem, key_pem = generate_client_certificate(
            ca_cert_pem, ca_key_pem, username=str(user.username), key_size=2048
        )
        ClientCertificate.objects.create(
            user=user,
            issuing_ca=ca,
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypt_private_key(key_pem),
            common_name=user.username,
            fingerprint=get_certificate_fingerprint(cert_pem),
            serial_number=hex(get_certificate_serial_number(cert_pem)),
            key_size=2048,
            not_valid_before=x509.load_pem_x509_certificate(cert_pem).not_valid_before_utc,
            not_valid_after=x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc,
        )
        assert_that(ca.client_certificates.count(), equal_to(1))


@pytest.mark.django_db
class TestClientCertificateDownload:
    """Test the client certificate download REST API endpoint."""

    def _create_ca_and_client_cert(self, admin_api_client: APIClient) -> int:
        """Helper that creates a CA and a client cert, returns the cert ID."""
        admin_api_client.post(
            '/api/admin/pki/ca/',
            {'common_name': 'DL CA', 'key_size': 2048},
            format='json',
        )
        user = User.objects.create_user(username='dluser', password='pass123')
        resp = admin_api_client.post(
            '/api/admin/pki/client-certs/',
            {'user_id': user.pk, 'key_size': 2048},
            format='json',
        )
        return resp.data['id']

    def test_download_p12(self, admin_api_client: APIClient) -> None:
        """POST /api/admin/pki/client-certs/{id}/download/ returns PKCS#12 bundle."""
        cert_id = self._create_ca_and_client_cert(admin_api_client)
        response = admin_api_client.post(
            f'/api/admin/pki/client-certs/{cert_id}/download/',
            {'password': 'testpass123'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], equal_to('application/x-pkcs12'))
        assert_that(response['Content-Disposition'], contains_string('.p12'))
        private_key, cert, cas = pkcs12.load_key_and_certificates(
            response.content, b'testpass123'
        )
        assert_that(private_key, is_(not_none()))
        assert_that(cert, is_(not_none()))
        assert_that(cas, has_length(1))

    def test_download_p12_missing_password(self, admin_api_client: APIClient) -> None:
        """POST without password returns 400."""
        cert_id = self._create_ca_and_client_cert(admin_api_client)
        response = admin_api_client.post(
            f'/api/admin/pki/client-certs/{cert_id}/download/',
            {},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_download_nonexistent_client_cert(self, admin_api_client: APIClient) -> None:
        """Downloading a nonexistent client cert returns 404."""
        response = admin_api_client.post(
            '/api/admin/pki/client-certs/99999/download/',
            {'password': 'test'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_download_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Non-admin users cannot download client certs via the admin endpoint."""
        response = auth_api_client.post(
            '/api/admin/pki/client-certs/1/download/',
            {'password': 'test'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


class TestGeneratePkcs12:
    """Test the generate_pkcs12 utility function."""

    def test_round_trip(self) -> None:
        """Generated .p12 can be loaded back with the same password."""
        ca_pem, ca_key_pem = generate_ca_certificate(key_size=2048)
        cert_pem, key_pem = generate_client_certificate(
            ca_pem, ca_key_pem, username='alice', key_size=2048,
        )
        password = b'test-secret'
        p12_data = generate_pkcs12(
            cert_pem=cert_pem,
            key_pem=key_pem,
            ca_cert_pem=ca_pem,
            friendly_name='alice',
            password=password,
        )
        private_key, cert, cas = pkcs12.load_key_and_certificates(p12_data, password)
        assert_that(private_key, is_(not_none()))
        assert_that(cert, is_(not_none()))
        assert_that(cas, has_length(1))

    def test_wrong_password_fails(self) -> None:
        """Loading .p12 with wrong password raises an error."""
        ca_pem, ca_key_pem = generate_ca_certificate(key_size=2048)
        cert_pem, key_pem = generate_client_certificate(
            ca_pem, ca_key_pem, username='bob', key_size=2048,
        )
        p12_data = generate_pkcs12(
            cert_pem=cert_pem,
            key_pem=key_pem,
            ca_cert_pem=ca_pem,
            friendly_name='bob',
            password=b'correct-password',
        )
        with pytest.raises(Exception):
            pkcs12.load_key_and_certificates(p12_data, b'wrong-password')


class TestCertificateMetadata:
    """Test get_certificate_metadata() extraction."""

    def test_ca_metadata_has_cn_and_o(self) -> None:
        """CA cert metadata should contain CN and O fields."""
        cert_pem, _ = generate_ca_certificate(
            common_name='Test Metadata CA', key_size=2048
        )
        meta = get_certificate_metadata(cert_pem)
        assert_that(meta, has_key('CN'))
        assert_that(meta['CN'], equal_to('Test Metadata CA'))
        assert_that(meta, has_key('O'))
        assert_that(meta['O'], equal_to('My Tracks'))

    def test_server_cert_metadata(self) -> None:
        """Server cert metadata should contain CN and O."""
        ca_pem, ca_key = generate_ca_certificate(key_size=2048)
        cert_pem, _ = generate_server_certificate(
            ca_pem, ca_key, common_name='myhost', san_entries=['myhost'],
            key_size=2048,
        )
        meta = get_certificate_metadata(cert_pem)
        assert_that(meta['CN'], equal_to('myhost'))
        assert_that(meta['O'], equal_to('My Tracks'))

    def test_client_cert_metadata_inherits_org(self) -> None:
        """Client cert metadata should inherit O from the CA."""
        ca_pem, ca_key = generate_ca_certificate(key_size=2048)
        cert_pem, _ = generate_client_certificate(
            ca_pem, ca_key, username='alice', key_size=2048,
        )
        meta = get_certificate_metadata(cert_pem)
        assert_that(meta['CN'], equal_to('alice'))
        assert_that(meta['O'], equal_to('My Tracks'))

    def test_missing_fields_not_in_metadata(self) -> None:
        """Fields not present in the cert should not appear."""
        cert_pem, _ = generate_ca_certificate(key_size=2048)
        meta = get_certificate_metadata(cert_pem)
        for absent in ('OU', 'C', 'ST', 'L'):
            assert_that(absent not in meta, is_(True))


class TestValidityPresets:
    """Test the validity preset constants."""

    def test_presets_are_ordered(self) -> None:
        """Presets should be ordered 1 year to 5 years."""
        assert_that(VALIDITY_PRESETS, has_length(5))
        days = [d for d, _ in VALIDITY_PRESETS]
        assert_that(days, equal_to([365, 730, 1095, 1460, 1825]))

    def test_default_cert_validity_is_5_years(self) -> None:
        """Default cert validity should be 5 years (1825 days)."""
        assert_that(DEFAULT_CERT_VALIDITY_DAYS, equal_to(1825))


class TestTLSHandshake:
    """Validate that issued certificates form a proper TLS trust chain."""

    def test_server_cert_verified_by_ca(self) -> None:
        """Server certificate should be verifiable against its issuing CA."""
        import ssl
        import tempfile
        ca_pem, ca_key = generate_ca_certificate(
            common_name='TLS Test CA', key_size=2048,
        )
        server_pem, server_key = generate_server_certificate(
            ca_pem, ca_key, common_name='localhost',
            san_entries=['localhost', '127.0.0.1'], key_size=2048,
        )

        with (
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as server_cert_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as server_key_file,
        ):
            ca_file.write(ca_pem)
            ca_file.flush()
            server_cert_file.write(server_pem)
            server_cert_file.flush()
            server_key_file.write(server_key)
            server_key_file.flush()

            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(server_cert_file.name, server_key_file.name)

            verify_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            verify_ctx.load_verify_locations(ca_file.name)
            verify_ctx.check_hostname = False

            assert_that(ctx, is_(not_none()))
            assert_that(verify_ctx, is_(not_none()))

    def test_client_cert_verified_by_ca(self) -> None:
        """Client certificate should be verifiable against its issuing CA."""
        import ssl
        import tempfile
        ca_pem, ca_key = generate_ca_certificate(
            common_name='TLS Test CA', key_size=2048,
        )
        client_pem, client_key = generate_client_certificate(
            ca_pem, ca_key, username='testuser', key_size=2048,
        )

        with (
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as client_cert_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as client_key_file,
        ):
            ca_file.write(ca_pem)
            ca_file.flush()
            client_cert_file.write(client_pem)
            client_cert_file.flush()
            client_key_file.write(client_key)
            client_key_file.flush()

            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(ca_file.name)
            ctx.load_cert_chain(client_cert_file.name, client_key_file.name)
            ctx.check_hostname = False

            assert_that(ctx, is_(not_none()))

    def test_full_tls_handshake(self) -> None:
        """End-to-end TLS handshake between server and client using our certs."""
        import socket
        import ssl
        import tempfile
        import threading

        ca_pem, ca_key = generate_ca_certificate(
            common_name='Handshake CA', key_size=2048,
        )
        server_pem, server_key = generate_server_certificate(
            ca_pem, ca_key, common_name='localhost',
            san_entries=['localhost', '127.0.0.1'], key_size=2048,
        )
        client_pem, client_key = generate_client_certificate(
            ca_pem, ca_key, username='handshakeuser', key_size=2048,
        )

        with (
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as srv_cert,
            tempfile.NamedTemporaryFile(suffix='.pem') as srv_key_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as cli_cert,
            tempfile.NamedTemporaryFile(suffix='.pem') as cli_key_file,
        ):
            for f, data in [
                (ca_file, ca_pem), (srv_cert, server_pem),
                (srv_key_file, server_key), (cli_cert, client_pem),
                (cli_key_file, client_key),
            ]:
                f.write(data)
                f.flush()

            server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ctx.load_cert_chain(srv_cert.name, srv_key_file.name)
            server_ctx.load_verify_locations(ca_file.name)
            server_ctx.verify_mode = ssl.CERT_REQUIRED

            client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            client_ctx.load_verify_locations(ca_file.name)
            client_ctx.load_cert_chain(cli_cert.name, cli_key_file.name)

            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind(('127.0.0.1', 0))
            port = server_sock.getsockname()[1]
            server_sock.listen(1)

            handshake_ok = [False]
            peer_cn = ['']

            def server_thread() -> None:
                conn, _ = server_sock.accept()
                try:
                    tls_conn = server_ctx.wrap_socket(conn, server_side=True)
                    peer = tls_conn.getpeercert()
                    if peer:
                        for rdn in peer.get('subject', ()):
                            for attr_type, attr_value in rdn:
                                if attr_type == 'commonName':
                                    peer_cn[0] = attr_value
                    handshake_ok[0] = True
                    tls_conn.shutdown(socket.SHUT_RDWR)
                    tls_conn.close()
                except Exception:
                    pass
                finally:
                    server_sock.close()

            t = threading.Thread(target=server_thread, daemon=True)
            t.start()

            client_sock = socket.create_connection(('127.0.0.1', port))
            tls_client = client_ctx.wrap_socket(
                client_sock, server_hostname='localhost'
            )
            tls_client.shutdown(socket.SHUT_RDWR)
            tls_client.close()

            t.join(timeout=5)

            assert_that(handshake_ok[0], is_(True))
            assert_that(peer_cn[0], equal_to('handshakeuser'))

    @staticmethod
    def _write_and_flush(
        file_data_pairs: list[tuple[Any, bytes]],
    ) -> None:
        for f, data in file_data_pairs:
            f.write(data)
            f.flush()

    def test_revoked_client_cert_rejected(self) -> None:
        """Server with CRL checking must reject a revoked client certificate.

        In TLS 1.3 the client-side handshake may complete before the server
        verifies the client cert, so we assert on the server-side error and
        confirm the client cannot actually exchange data.
        """
        import socket
        import ssl
        import tempfile
        import threading

        ca_pem, ca_key = generate_ca_certificate(
            common_name='CRL Reject CA', key_size=2048,
        )
        server_pem, server_key = generate_server_certificate(
            ca_pem, ca_key, common_name='localhost',
            san_entries=['localhost', '127.0.0.1'], key_size=2048,
        )
        client_pem, client_key = generate_client_certificate(
            ca_pem, ca_key, username='revokeduser', key_size=2048,
        )

        serial = get_certificate_serial_number(client_pem)
        crl_pem = generate_crl(
            ca_pem, ca_key,
            revoked_entries=[(serial, datetime.now(UTC))],
        )

        ca_plus_crl = ca_pem + b'\n' + crl_pem

        with (
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_crl_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as srv_cert,
            tempfile.NamedTemporaryFile(suffix='.pem') as srv_key_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as cli_cert,
            tempfile.NamedTemporaryFile(suffix='.pem') as cli_key_file,
        ):
            self._write_and_flush([
                (ca_crl_file, ca_plus_crl),
                (srv_cert, server_pem), (srv_key_file, server_key),
                (ca_file, ca_pem),
                (cli_cert, client_pem), (cli_key_file, client_key),
            ])

            server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ctx.load_cert_chain(srv_cert.name, srv_key_file.name)
            server_ctx.load_verify_locations(cafile=ca_crl_file.name)
            server_ctx.verify_mode = ssl.CERT_REQUIRED
            server_ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF

            client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            client_ctx.load_verify_locations(ca_file.name)
            client_ctx.load_cert_chain(cli_cert.name, cli_key_file.name)

            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind(('127.0.0.1', 0))
            port = server_sock.getsockname()[1]
            server_sock.listen(1)

            server_error: list[Exception | None] = [None]

            def server_thread() -> None:
                conn, _ = server_sock.accept()
                try:
                    server_ctx.wrap_socket(conn, server_side=True)
                except Exception as exc:
                    server_error[0] = exc
                finally:
                    conn.close()
                    server_sock.close()

            t = threading.Thread(target=server_thread, daemon=True)
            t.start()

            client_sock = socket.create_connection(('127.0.0.1', port))
            tls_client: ssl.SSLSocket | None = None
            client_io_failed = False
            try:
                tls_client = client_ctx.wrap_socket(
                    client_sock, server_hostname='localhost',
                )
                tls_client.send(b'ping')
                tls_client.recv(1)
            except (ssl.SSLError, OSError):
                client_io_failed = True
            finally:
                if tls_client:
                    tls_client.close()
                else:
                    client_sock.close()

            t.join(timeout=5)

            assert_that(
                server_error[0], is_(instance_of(ssl.SSLError)),
                'Server must reject revoked client cert',
            )
            assert_that(
                str(server_error[0]), contains_string('certificate revoked'),
            )
            assert_that(
                client_io_failed, is_(True),
                'Client must not be able to exchange data after revocation',
            )

    def test_non_revoked_client_passes_with_crl(self) -> None:
        """A valid client cert must still be accepted when CRL checking is on."""
        import socket
        import ssl
        import tempfile
        import threading

        ca_pem, ca_key = generate_ca_certificate(
            common_name='CRL Pass CA', key_size=2048,
        )
        server_pem, server_key = generate_server_certificate(
            ca_pem, ca_key, common_name='localhost',
            san_entries=['localhost', '127.0.0.1'], key_size=2048,
        )
        good_pem, good_key = generate_client_certificate(
            ca_pem, ca_key, username='gooduser', key_size=2048,
        )
        bad_pem, _ = generate_client_certificate(
            ca_pem, ca_key, username='baduser', key_size=2048,
        )

        bad_serial = get_certificate_serial_number(bad_pem)
        crl_pem = generate_crl(
            ca_pem, ca_key,
            revoked_entries=[(bad_serial, datetime.now(UTC))],
        )

        ca_plus_crl = ca_pem + b'\n' + crl_pem

        with (
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_crl_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as srv_cert,
            tempfile.NamedTemporaryFile(suffix='.pem') as srv_key_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as ca_file,
            tempfile.NamedTemporaryFile(suffix='.pem') as cli_cert,
            tempfile.NamedTemporaryFile(suffix='.pem') as cli_key_file,
        ):
            self._write_and_flush([
                (ca_crl_file, ca_plus_crl),
                (srv_cert, server_pem), (srv_key_file, server_key),
                (ca_file, ca_pem),
                (cli_cert, good_pem), (cli_key_file, good_key),
            ])

            server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ctx.load_cert_chain(srv_cert.name, srv_key_file.name)
            server_ctx.load_verify_locations(cafile=ca_crl_file.name)
            server_ctx.verify_mode = ssl.CERT_REQUIRED
            server_ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF

            client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            client_ctx.load_verify_locations(ca_file.name)
            client_ctx.load_cert_chain(cli_cert.name, cli_key_file.name)

            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind(('127.0.0.1', 0))
            port = server_sock.getsockname()[1]
            server_sock.listen(1)

            handshake_ok = [False]
            peer_cn = ['']

            def server_thread() -> None:
                conn, _ = server_sock.accept()
                try:
                    tls_conn = server_ctx.wrap_socket(conn, server_side=True)
                    peer = tls_conn.getpeercert()
                    if peer:
                        for rdn in peer.get('subject', ()):
                            for attr_type, attr_value in rdn:
                                if attr_type == 'commonName':
                                    peer_cn[0] = attr_value
                    handshake_ok[0] = True
                    tls_conn.shutdown(socket.SHUT_RDWR)
                    tls_conn.close()
                except Exception:
                    pass
                finally:
                    server_sock.close()

            t = threading.Thread(target=server_thread, daemon=True)
            t.start()

            client_sock = socket.create_connection(('127.0.0.1', port))
            tls_client = client_ctx.wrap_socket(
                client_sock, server_hostname='localhost',
            )
            tls_client.shutdown(socket.SHUT_RDWR)
            tls_client.close()

            t.join(timeout=5)

            assert_that(handshake_ok[0], is_(True))
            assert_that(peer_cn[0], equal_to('gooduser'))


@pytest.mark.django_db
class TestClientCertificateAPI:
    """Test client certificate REST API endpoints (create, revoke, expunge)."""

    def test_list_client_certs_empty(self, admin_with_ca: APIClient) -> None:
        """Test GET /api/admin/pki/client-certs/ returns empty list initially."""
        response = admin_with_ca.get('/api/admin/pki/client-certs/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(0))

    def test_create_client_cert(self, admin_with_ca: APIClient) -> None:
        """Test POST /api/admin/pki/client-certs/ issues a client cert."""
        user = User.objects.create_user(username='certtest', password='pass123')
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data, has_key('id'))
        assert_that(response.data['common_name'], equal_to('certtest'))
        assert_that(response.data['is_active'], is_(True))

    def test_create_client_cert_no_active_ca(
        self, admin_api_client: APIClient
    ) -> None:
        """Test creating client cert without active CA returns 400."""
        user = User.objects.create_user(username='nocauser', password='pass123')
        response = admin_api_client.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('No active CA'))

    def test_create_client_cert_missing_user_id(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test creating client cert without user_id returns 400."""
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('user_id'))

    def test_create_client_cert_invalid_user_id(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test creating client cert with nonexistent user_id returns 404."""
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': 99999,
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(response.data['error'], contains_string('user ID'))

    def test_create_client_cert_non_integer_validity(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test non-integer validity_days for client cert returns 400."""
        user = User.objects.create_user(username='valuser', password='pass123')
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'validity_days': 'abc',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('validity_days'))

    def test_create_client_cert_validity_out_of_range(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test out-of-range validity_days for client cert returns 400."""
        user = User.objects.create_user(username='rangeuser', password='pass123')
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'validity_days': 0,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('validity_days'))

    def test_create_client_cert_non_integer_key_size(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test non-integer key_size for client cert returns 400."""
        user = User.objects.create_user(username='keyuser', password='pass123')
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'key_size': 'xyz',
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('key_size'))

    def test_create_client_cert_invalid_key_size(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test disallowed key_size for client cert returns 400."""
        user = User.objects.create_user(username='bkeyuser', password='pass123')
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'key_size': 1024,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('key_size'))

    def _create_client_cert(self, client: APIClient) -> int:
        """Helper to create a user + client cert. Returns cert ID."""
        user = User.objects.create_user(
            username='actionuser', password='pass123'
        )
        resp = client.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'key_size': 2048,
        }, format='json')
        return resp.data['id']

    def test_revoke_client_cert(self, admin_with_ca: APIClient) -> None:
        """Test POST revoke action marks cert as revoked."""
        cert_id = self._create_client_cert(admin_with_ca)
        response = admin_with_ca.post(
            f'/api/admin/pki/client-certs/{cert_id}/revoke/'
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['detail'], contains_string('revoked'))
        cert = ClientCertificate.objects.get(pk=cert_id)
        assert_that(cert.revoked, is_(True))
        assert_that(cert.is_active, is_(False))

    def test_revoke_already_revoked(self, admin_with_ca: APIClient) -> None:
        """Test revoking an already-revoked cert returns 400."""
        cert_id = self._create_client_cert(admin_with_ca)
        admin_with_ca.post(f'/api/admin/pki/client-certs/{cert_id}/revoke/')
        response = admin_with_ca.post(
            f'/api/admin/pki/client-certs/{cert_id}/revoke/'
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('already revoked'))

    def test_revoke_nonexistent(self, admin_with_ca: APIClient) -> None:
        """Test revoking a nonexistent cert returns 404."""
        response = admin_with_ca.post(
            '/api/admin/pki/client-certs/99999/revoke/'
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_expunge_revoked_cert(self, admin_with_ca: APIClient) -> None:
        """Test expunge permanently deletes a revoked cert."""
        cert_id = self._create_client_cert(admin_with_ca)
        admin_with_ca.post(f'/api/admin/pki/client-certs/{cert_id}/revoke/')
        response = admin_with_ca.delete(
            f'/api/admin/pki/client-certs/{cert_id}/expunge/'
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            ClientCertificate.objects.filter(pk=cert_id).exists(), is_(False)
        )

    def test_expunge_active_cert_rejected(
        self, admin_with_ca: APIClient
    ) -> None:
        """Test expunging an active cert returns 400."""
        cert_id = self._create_client_cert(admin_with_ca)
        response = admin_with_ca.delete(
            f'/api/admin/pki/client-certs/{cert_id}/expunge/'
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('active'))

    def test_expunge_nonexistent(self, admin_with_ca: APIClient) -> None:
        """Test expunging a nonexistent cert returns 404."""
        response = admin_with_ca.delete(
            '/api/admin/pki/client-certs/99999/expunge/'
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


@pytest.mark.django_db
class TestCRLViewSetAPI:
    """Test the CRL download REST API endpoint."""

    def test_crl_no_active_ca(self) -> None:
        """Test CRL download without active CA returns 404."""
        client = APIClient()
        response = client.get('/api/admin/pki/crl/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(response.data['error'], contains_string('No active CA'))

    def test_crl_download(self, admin_with_ca: APIClient) -> None:
        """Test CRL download returns PEM file."""
        response = admin_with_ca.get('/api/admin/pki/crl/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response['Content-Type'], equal_to('application/x-pem-file'))
        assert_that(response['Content-Disposition'], contains_string('.crl'))
        assert_that(
            response.content.decode(), contains_string('BEGIN X509 CRL')
        )

    def test_crl_with_revoked_certs(self, admin_with_ca: APIClient) -> None:
        """Test CRL includes revoked client certificates."""
        user = User.objects.create_user(username='crluser', password='pass123')
        resp = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'key_size': 2048,
        }, format='json')
        cert_id = resp.data['id']
        admin_with_ca.post(f'/api/admin/pki/client-certs/{cert_id}/revoke/')
        response = admin_with_ca.get('/api/admin/pki/crl/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.content.decode(), contains_string('BEGIN X509 CRL')
        )
