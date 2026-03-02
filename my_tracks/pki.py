"""
PKI utilities for certificate generation and key encryption.

Provides functions for generating CA, server, and client certificates,
generating Certificate Revocation Lists (CRLs), and encrypting/decrypting
private keys at rest using Fernet symmetric encryption derived from
Django's SECRET_KEY.
"""
import base64
import hashlib
import ipaddress
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from django.conf import settings


def _derive_fernet_key() -> bytes:
    """Derive a Fernet-compatible key from Django's SECRET_KEY."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_private_key(pem_data: bytes) -> bytes:
    """Encrypt a PEM-encoded private key for storage at rest."""
    fernet = Fernet(_derive_fernet_key())
    return fernet.encrypt(pem_data)


def decrypt_private_key(encrypted_data: bytes) -> bytes:
    """Decrypt a PEM-encoded private key from storage."""
    fernet = Fernet(_derive_fernet_key())
    return fernet.decrypt(encrypted_data)


ALLOWED_KEY_SIZES = (2048, 3072, 4096)

VALIDITY_PRESETS: list[tuple[int, str]] = [
    (365, '1 year'),
    (730, '2 years'),
    (1095, '3 years'),
    (1460, '4 years'),
    (1825, '5 years'),
]

DEFAULT_CERT_VALIDITY_DAYS = 1825
DEFAULT_CA_VALIDITY_DAYS = 3650


def generate_ca_certificate(
    common_name: str = "My Tracks CA",
    validity_days: int = 3650,
    key_size: int = 4096,
) -> tuple[bytes, bytes]:
    """
    Generate a self-signed CA certificate and private key.

    Args:
        common_name: Subject Common Name for the CA certificate.
        validity_days: Number of days the certificate is valid.
        key_size: RSA key size in bits (2048, 3072, or 4096).

    Returns:
        Tuple of (certificate_pem, private_key_pem) as bytes.

    Raises:
        ValueError: If key_size is not one of the allowed values.
    """
    if key_size not in ALLOWED_KEY_SIZES:
        raise ValueError(
            f"Expected key_size in {ALLOWED_KEY_SIZES}, got {key_size}"
        )
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "My Tracks"),
    ])

    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    return cert_pem, key_pem


def get_certificate_fingerprint(cert_pem: bytes) -> str:
    """Get the SHA-256 fingerprint of a PEM-encoded certificate."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    digest = cert.fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in digest)


def get_certificate_subject(cert_pem: bytes) -> str:
    """Get the subject common name of a PEM-encoded certificate."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if cn_attrs:
        return str(cn_attrs[0].value)
    return str(cert.subject)


def get_certificate_expiry(cert_pem: bytes) -> datetime:
    """Get the expiry datetime of a PEM-encoded certificate."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.not_valid_after_utc


def get_certificate_sans(cert_pem: bytes) -> list[str]:
    """Get the Subject Alternative Names from a PEM-encoded certificate."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    try:
        san_ext = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
    except x509.ExtensionNotFound:
        return []
    names: list[str] = []
    for name in san_ext.value.get_values_for_type(x509.DNSName):
        names.append(str(name))
    for addr in san_ext.value.get_values_for_type(x509.IPAddress):
        names.append(str(addr))
    return names


def generate_server_certificate(
    ca_cert_pem: bytes,
    ca_key_pem: bytes,
    common_name: str,
    san_entries: list[str],
    validity_days: int = DEFAULT_CERT_VALIDITY_DAYS,
    key_size: int = 4096,
) -> tuple[bytes, bytes]:
    """
    Generate a server certificate signed by the given CA.

    Args:
        ca_cert_pem: CA certificate in PEM format.
        ca_key_pem: CA private key in PEM format (unencrypted).
        common_name: Subject Common Name for the server certificate.
        san_entries: List of SAN entries (IP addresses and DNS names).
        validity_days: Number of days the certificate is valid.
        key_size: RSA key size in bits (2048, 3072, or 4096).

    Returns:
        Tuple of (certificate_pem, private_key_pem) as bytes.

    Raises:
        ValueError: If key_size is not allowed or san_entries is empty.
    """
    if key_size not in ALLOWED_KEY_SIZES:
        raise ValueError(
            f"Expected key_size in {ALLOWED_KEY_SIZES}, got {key_size}"
        )
    if not san_entries:
        raise ValueError("Expected at least one SAN entry, got empty list")

    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
    ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    if not isinstance(ca_key, RSAPrivateKey):
        raise ValueError("Expected RSA private key for CA")

    server_key = rsa.generate_private_key(
        public_exponent=65537, key_size=key_size
    )

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "My Tracks"),
    ])

    san_objects: list[x509.GeneralName] = []
    for entry in san_entries:
        try:
            addr = ipaddress.ip_address(entry)
            san_objects.append(x509.IPAddress(addr))
        except ValueError:
            san_objects.append(x509.DNSName(entry))

    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
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
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(san_objects),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                server_key.public_key()
            ),
            critical=False,
        )
    )

    cert = builder.sign(ca_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    return cert_pem, key_pem


def generate_client_certificate(
    ca_cert_pem: bytes,
    ca_key_pem: bytes,
    username: str,
    validity_days: int = DEFAULT_CERT_VALIDITY_DAYS,
    key_size: int = 4096,
) -> tuple[bytes, bytes]:
    """
    Generate a client certificate signed by the given CA.

    The certificate embeds the username in the Common Name (CN) field
    so the MQTT broker can map client certificates back to users.

    Args:
        ca_cert_pem: CA certificate in PEM format.
        ca_key_pem: CA private key in PEM format (unencrypted).
        username: Username to embed in the certificate's CN.
        validity_days: Number of days the certificate is valid.
        key_size: RSA key size in bits (2048, 3072, or 4096).

    Returns:
        Tuple of (certificate_pem, private_key_pem) as bytes.

    Raises:
        ValueError: If key_size is not allowed or username is empty.
    """
    if key_size not in ALLOWED_KEY_SIZES:
        raise ValueError(
            f"Expected key_size in {ALLOWED_KEY_SIZES}, got {key_size}"
        )
    if not username or not username.strip():
        raise ValueError("Expected a non-empty username")

    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
    ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    if not isinstance(ca_key, RSAPrivateKey):
        raise ValueError("Expected RSA private key for CA")

    client_key = rsa.generate_private_key(
        public_exponent=65537, key_size=key_size
    )

    ca_org_attrs = ca_cert.subject.get_attributes_for_oid(
        NameOID.ORGANIZATION_NAME
    )
    org_name = str(ca_org_attrs[0].value) if ca_org_attrs else "My Tracks"

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, username),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_name),
    ])

    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
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
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                client_key.public_key()
            ),
            critical=False,
        )
    )

    cert = builder.sign(ca_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = client_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    return cert_pem, key_pem


def generate_crl(
    ca_cert_pem: bytes,
    ca_key_pem: bytes,
    revoked_entries: list[tuple[int, datetime]],
    validity_days: int = 30,
) -> bytes:
    """
    Generate a Certificate Revocation List (CRL) signed by the CA.

    Args:
        ca_cert_pem: CA certificate in PEM format.
        ca_key_pem: CA private key in PEM format (unencrypted).
        revoked_entries: List of (serial_number, revocation_datetime) tuples.
        validity_days: Days until the CRL expires (next update).

    Returns:
        CRL in PEM format as bytes.
    """
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
    ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    if not isinstance(ca_key, RSAPrivateKey):
        raise ValueError("Expected RSA private key for CA")

    now = datetime.now(UTC)
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca_cert.subject)
        .last_update(now)
        .next_update(now + timedelta(days=validity_days))
    )

    for serial_number, revocation_time in revoked_entries:
        revoked_cert = (
            x509.RevokedCertificateBuilder()
            .serial_number(serial_number)
            .revocation_date(revocation_time)
            .build()
        )
        builder = builder.add_revoked_certificate(revoked_cert)

    crl = builder.sign(ca_key, hashes.SHA256())
    return crl.public_bytes(serialization.Encoding.PEM)


def generate_pkcs12(
    cert_pem: bytes,
    key_pem: bytes,
    ca_cert_pem: bytes,
    friendly_name: str,
    password: bytes,
) -> bytes:
    """
    Bundle a client certificate, its private key, and the CA certificate
    into a PKCS#12 (.p12) archive protected by a password.

    Args:
        cert_pem: Client certificate in PEM format.
        key_pem: Client private key in PEM format (unencrypted).
        ca_cert_pem: CA certificate in PEM format (included as trust chain).
        friendly_name: Display name stored inside the .p12 archive.
        password: Password to encrypt the .p12 file.

    Returns:
        PKCS#12 archive as bytes.
    """
    cert = x509.load_pem_x509_certificate(cert_pem)
    key = serialization.load_pem_private_key(key_pem, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("Expected RSA private key")
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)

    return pkcs12.serialize_key_and_certificates(
        name=friendly_name.encode(),
        key=key,
        cert=cert,
        cas=[ca_cert],
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )


def get_certificate_serial_number(cert_pem: bytes) -> int:
    """Get the serial number of a PEM-encoded certificate."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.serial_number


_OID_TO_LABEL: dict[x509.ObjectIdentifier, str] = {
    NameOID.COMMON_NAME: 'CN',
    NameOID.ORGANIZATION_NAME: 'O',
    NameOID.ORGANIZATIONAL_UNIT_NAME: 'OU',
    NameOID.COUNTRY_NAME: 'C',
    NameOID.STATE_OR_PROVINCE_NAME: 'ST',
    NameOID.LOCALITY_NAME: 'L',
}


def get_certificate_metadata(cert_pem: bytes) -> dict[str, str]:
    """
    Extract human-readable subject metadata from a PEM certificate.

    Returns a dict mapping standard abbreviations (CN, O, OU, C, ST, L)
    to their values, only for fields present in the certificate subject.
    """
    cert = x509.load_pem_x509_certificate(cert_pem)
    metadata: dict[str, str] = {}
    for oid, label in _OID_TO_LABEL.items():
        attrs = cert.subject.get_attributes_for_oid(oid)
        if attrs:
            metadata[label] = str(attrs[0].value)
    return metadata
