"""Tests for PKI (Certificate Authority, Server Certificate, Client Certificate) functionality."""
# pyright: reportIndexIssue=none
import base64
import hashlib
import logging
import warnings
from datetime import UTC, datetime
from io import StringIO
from typing import Any, cast
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from django.contrib.auth.models import User
from django.core.management import call_command
from hamcrest import (assert_that, calling, contains_string, equal_to,
                      has_item, has_key, has_length, is_, is_not, not_none,
                      raises, starts_with)
from rest_framework import status
from rest_framework.test import APIClient
from tiny_pki import (TinyPkiError, TinyPkiWarning, get_certificate_expiry,
                      get_certificate_fingerprint, get_certificate_metadata,
                      get_certificate_serial_number, get_certificate_subject)
from tiny_pki.secrets import derive_fernet_key

from app.models import (CertificateAuthority, ClientCertificate,
                        ServerCertificate)
from app.pki import (DEFAULT_CA_VALIDITY_DAYS, DEFAULT_CERT_VALIDITY_DAYS,
                     VALIDITY_PRESETS,
                     decrypt_private_key, encrypt_private_key,
                     generate_ca_certificate, generate_client_certificate,
                     generate_server_certificate, reencrypt_private_key)


def _legacy_fernet_key(secret: str) -> bytes:
    """Fernet key for a pre-tiny-pki secret shorter than tiny-pki's encryption minimum."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


class TestPrivateKeyEncryption:
    """Test Fernet encryption of private keys bound to Django's SECRET_KEY."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypting then decrypting recovers the original data."""
        _, key_pem = generate_ca_certificate(key_size=2048)
        encrypted = encrypt_private_key(key_pem)
        assert_that(encrypted, is_not(equal_to(key_pem)))
        decrypted = decrypt_private_key(encrypted)
        assert_that(decrypted, equal_to(key_pem))

    def test_reencrypt_private_key_roundtrip(self) -> None:
        """A key stored under a short pre-tiny-pki secret moves to the current SECRET_KEY."""
        _, key_pem = generate_ca_certificate(key_size=2048)
        old_secret = "old-dev-secret-key"
        new_secret = "new-prod-secret-key-at-least-32-chars"

        old_fernet = Fernet(_legacy_fernet_key(old_secret))
        encrypted_with_old = old_fernet.encrypt(key_pem)

        with patch("app.pki.settings") as mock_settings:
            mock_settings.SECRET_KEY = new_secret
            re_encrypted = reencrypt_private_key(encrypted_with_old, old_secret)

        new_fernet = Fernet(derive_fernet_key(new_secret))
        decrypted = new_fernet.decrypt(re_encrypted)
        assert_that(decrypted, equal_to(key_pem))

    def test_reencrypt_with_wrong_old_key_fails(self) -> None:
        """Re-encryption fails if the old key is wrong."""
        _, key_pem = generate_ca_certificate(key_size=2048)
        encrypted = encrypt_private_key(key_pem)

        with pytest.raises(InvalidToken):
            reencrypt_private_key(encrypted, "wrong-key")


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

    def test_create_ca_invisible_character_in_name(self, admin_api_client: APIClient) -> None:
        """A CA name tiny-pki rejects (zero-width space) returns 400, not 500."""
        response = admin_api_client.post('/api/admin/pki/ca/', {
            'common_name': 'My\u200bCA',
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('common_name'))

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

    def test_create_server_cert_malformed_san(self, admin_with_ca: APIClient) -> None:
        """A SAN tiny-pki rejects (host:port) returns 400 with its message, not 500."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['tracks.lan:8883'],
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('without a port'))

    def test_create_server_cert_outliving_ca(self, admin_with_ca: APIClient) -> None:
        """A server cert that would expire after its CA returns 400."""
        response = admin_with_ca.post('/api/admin/pki/server-cert/', {
            'common_name': 'myserver',
            'san_entries': ['myserver'],
            'validity_days': 36500,
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('renew the CA'))

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

    def test_download_p12_short_password(self, admin_api_client: APIClient) -> None:
        """A .p12 password under tiny-pki's minimum returns 400, not 500."""
        cert_id = self._create_ca_and_client_cert(admin_api_client)
        response = admin_api_client.post(
            f'/api/admin/pki/client-certs/{cert_id}/download/',
            {'password': 'short'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('at least 8 bytes, got 5'))

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

    def test_create_client_cert_outliving_ca(self, admin_with_ca: APIClient) -> None:
        """A client cert that would expire after its CA returns 400."""
        user = User.objects.create_user(username='longuser', password='pass123')
        response = admin_with_ca.post('/api/admin/pki/client-certs/', {
            'user_id': user.pk,
            'validity_days': 36500,
            'key_size': 2048,
        }, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('renew the CA'))

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


@pytest.mark.django_db
class TestReencryptPkiCommand:
    """Test the reencrypt_pki management command."""

    def test_reencrypt_ca_key(self) -> None:
        """Test that the command re-encrypts CA private keys."""
        old_secret = "old-dev-key-for-test"
        new_secret = "new-prod-key-for-test-at-least-32-chars"

        # Generate CA cert and encrypt the key with the old secret.
        cert_pem, key_pem = generate_ca_certificate()
        old_fernet = Fernet(_legacy_fernet_key(old_secret))
        encrypted_with_old = old_fernet.encrypt(key_pem)

        ca = CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted_with_old,
            common_name="Test CA",
            fingerprint="AA:BB",
            not_valid_before=datetime.now(UTC),
            not_valid_after=datetime(2030, 1, 1, tzinfo=UTC),
            is_active=True,
        )

        with patch("app.pki.settings") as mock_settings:
            mock_settings.SECRET_KEY = new_secret
            call_command("reencrypt_pki", old_secret_key=old_secret)

        ca.refresh_from_db()
        new_fernet = Fernet(derive_fernet_key(new_secret))
        decrypted = new_fernet.decrypt(bytes(ca.encrypted_private_key))
        assert_that(decrypted, equal_to(key_pem))

    def test_reencrypt_no_keys(self) -> None:
        """Test graceful handling when no PKI objects exist."""
        out = StringIO()
        call_command("reencrypt_pki", old_secret_key="unused", stdout=out)
        assert_that(out.getvalue(), contains_string("No PKI private keys found"))

    def test_reencrypt_wrong_old_key_fails(self) -> None:
        """Test that wrong old key raises an error."""
        cert_pem, key_pem = generate_ca_certificate()
        encrypted = encrypt_private_key(key_pem)

        CertificateAuthority.objects.create(
            certificate_pem=cert_pem.decode(),
            encrypted_private_key=encrypted,
            common_name="Test CA",
            fingerprint="CC:DD",
            not_valid_before=datetime.now(UTC),
            not_valid_after=datetime(2030, 1, 1, tzinfo=UTC),
            is_active=True,
        )

        with pytest.raises(Exception):
            call_command("reencrypt_pki", old_secret_key="wrong-key")


class TestTinyPkiAdapter:
    """Test how app.pki wraps tiny-pki errors and warnings."""

    @pytest.fixture
    def ca_pair(self) -> tuple[bytes, bytes]:
        return generate_ca_certificate(common_name="Adapter CA", key_size=2048)

    def test_ca_uses_my_tracks_organization(self, ca_pair: tuple[bytes, bytes]) -> None:
        assert_that(get_certificate_metadata(ca_pair[0])["O"], equal_to("My Tracks"))

    def test_ca_default_validity(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert = x509.load_pem_x509_certificate(ca_pair[0])
        assert_that((cert.not_valid_after_utc - cert.not_valid_before_utc).days, equal_to(DEFAULT_CA_VALIDITY_DAYS))

    def test_client_inherits_ca_organization(self, ca_pair: tuple[bytes, bytes]) -> None:
        cert_pem, _ = generate_client_certificate(ca_pair[0], ca_pair[1], username="alice", key_size=2048)
        assert_that(get_certificate_metadata(cert_pem)["O"], equal_to("My Tracks"))

    def test_leaf_defaults_override_tiny_pki(self, ca_pair: tuple[bytes, bytes]) -> None:
        """Leaves default to 4096-bit keys and 5 years, not tiny-pki's 3072 bits / 397 days."""
        cert_pem, _ = generate_client_certificate(ca_pair[0], ca_pair[1], username="alice")
        cert = x509.load_pem_x509_certificate(cert_pem)
        assert_that(cast(rsa.RSAPublicKey, cert.public_key()).key_size, equal_to(4096))
        assert_that((cert.not_valid_after_utc - cert.not_valid_before_utc).days, equal_to(DEFAULT_CERT_VALIDITY_DAYS))

    def test_tiny_pki_warnings_are_logged_not_emitted(
        self, ca_pair: tuple[bytes, bytes], caplog: pytest.LogCaptureFixture
    ) -> None:
        """Default 5-year server certs trigger tiny-pki's Apple warning; it is logged once, not warned."""
        with warnings.catch_warnings(record=True) as caught, caplog.at_level(logging.WARNING, logger="app.pki"):
            warnings.simplefilter("always")
            generate_server_certificate(
                ca_pair[0], ca_pair[1], common_name="mqtt.lan", san_entries=["10.0.0.1"], key_size=2048
            )
        tiny_pki_warnings = [w for w in caught if issubclass(w.category, TinyPkiWarning)]
        assert_that(tiny_pki_warnings, has_length(0))
        records = [r for r in caplog.records if r.name == "app.pki"]
        assert_that(records, has_length(1))
        assert_that(records[0].getMessage(), contains_string("Apple platforms will reject it"))
        assert_that(records[0].getMessage(), contains_string("Added common_name 'mqtt.lan' to the SANs"))

    def test_rejection_raises_tiny_pki_error_without_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        short_ca = generate_ca_certificate(validity_days=365, key_size=2048)
        with caplog.at_level(logging.WARNING, logger="app.pki"):
            assert_that(
                calling(generate_server_certificate).with_args(
                    short_ca[0], short_ca[1], common_name="mqtt.lan", san_entries=["mqtt.lan"], key_size=2048
                ),
                raises(TinyPkiError, "renew the CA"),
            )
        assert_that([r for r in caplog.records if r.name == "app.pki"], has_length(0))

    def test_other_warnings_are_reemitted(self) -> None:
        """Warnings that are not TinyPkiWarning pass through unchanged."""
        def _warn_and_issue(*args: Any, **kwargs: Any) -> tuple[bytes, bytes]:
            warnings.warn("unrelated", DeprecationWarning, stacklevel=1)
            return b"cert", b"key"

        with patch("app.pki.tiny_pki.generate_ca_certificate", side_effect=_warn_and_issue):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = generate_ca_certificate(key_size=2048)
        assert_that(result, equal_to((b"cert", b"key")))
        assert_that([str(w.message) for w in caught if w.category is DeprecationWarning], equal_to(["unrelated"]))
