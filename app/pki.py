"""
My Tracks adapter over the shared ``tiny_pki`` library.

Certificate crypto lives in `tiny-pki <https://github.com/the-hcma/tiny-pki>`_.
This module keeps only what is specific to My Tracks:

- issuance defaults (organization name, key size, 1-5 year validity presets);
- Fernet encryption of private keys at rest, keyed from Django's SECRET_KEY;
- logging tiny-pki warnings instead of emitting them as Python warnings.

Rejected requests raise :class:`tiny_pki.TinyPkiError`, whose message is safe to
show to users.

Pure helpers (inspection, CRL, PKCS#12) are imported from ``tiny_pki`` directly
by callers.
"""

import logging
import warnings
from collections.abc import Iterator
from contextlib import contextmanager

import tiny_pki
from django.conf import settings
from tiny_pki import ALLOWED_KEY_SIZES, TinyPkiWarning
from tiny_pki import secrets as tiny_pki_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_KEY_SIZES",
    "DEFAULT_CA_VALIDITY_DAYS",
    "DEFAULT_CERT_VALIDITY_DAYS",
    "VALIDITY_PRESETS",
    "decrypt_private_key",
    "encrypt_private_key",
    "generate_ca_certificate",
    "generate_client_certificate",
    "generate_server_certificate",
    "reencrypt_private_key",
]

DEFAULT_CA_VALIDITY_DAYS = 3650

DEFAULT_CERT_VALIDITY_DAYS = 1825

DEFAULT_KEY_SIZE = 4096

ORGANIZATION_NAME = "My Tracks"


VALIDITY_PRESETS: list[tuple[int, str]] = [
    (365, "1 year"),
    (730, "2 years"),
    (1095, "3 years"),
    (1460, "4 years"),
    (1825, "5 years"),
]


def decrypt_private_key(encrypted_data: bytes) -> bytes:
    """Decrypt a PEM-encoded private key from storage."""
    return tiny_pki_secrets.decrypt_private_key(encrypted_data, settings.SECRET_KEY)


def encrypt_private_key(pem_data: bytes) -> bytes:
    """Encrypt a PEM-encoded private key for storage at rest."""
    return tiny_pki_secrets.encrypt_private_key(pem_data, settings.SECRET_KEY)


def generate_ca_certificate(
    common_name: str = "My Tracks CA",
    validity_days: int = DEFAULT_CA_VALIDITY_DAYS,
    key_size: int = DEFAULT_KEY_SIZE,
) -> tuple[bytes, bytes]:
    """
    Generate a self-signed CA certificate and private key.

    Returns:
        Tuple of (certificate_pem, private_key_pem) as bytes.

    Raises:
        TinyPkiError: If tiny-pki rejects the request (e.g. key size, name).
    """
    with _tiny_pki_warnings_logged():
        return tiny_pki.generate_ca_certificate(
            common_name,
            organization_name=ORGANIZATION_NAME,
            validity_days=validity_days,
            key_size=key_size,
        )


def generate_client_certificate(
    ca_cert_pem: bytes,
    ca_key_pem: bytes,
    username: str,
    validity_days: int = DEFAULT_CERT_VALIDITY_DAYS,
    key_size: int = DEFAULT_KEY_SIZE,
) -> tuple[bytes, bytes]:
    """
    Generate a client certificate signed by the given CA.

    The username is the certificate's Common Name so the MQTT broker can map
    client certificates back to users. The organization is inherited from the CA.

    Returns:
        Tuple of (certificate_pem, private_key_pem) as bytes.

    Raises:
        TinyPkiError: If tiny-pki rejects the request (e.g. empty username,
            validity past the CA's expiry).
    """
    with _tiny_pki_warnings_logged():
        return tiny_pki.generate_client_certificate(
            ca_cert_pem,
            ca_key_pem,
            username,
            validity_days=validity_days,
            key_size=key_size,
            allow_long_validity=True,
        )


def generate_server_certificate(
    ca_cert_pem: bytes,
    ca_key_pem: bytes,
    common_name: str,
    san_entries: list[str],
    validity_days: int = DEFAULT_CERT_VALIDITY_DAYS,
    key_size: int = DEFAULT_KEY_SIZE,
) -> tuple[bytes, bytes]:
    """
    Generate a server certificate signed by the given CA.

    SAN entries are normalized by tiny-pki, and a host-like Common Name missing
    from them is added (TLS clients ignore the CN).

    Returns:
        Tuple of (certificate_pem, private_key_pem) as bytes.

    Raises:
        TinyPkiError: If tiny-pki rejects the request (e.g. no or malformed
            SANs, validity past the CA's expiry).
    """
    with _tiny_pki_warnings_logged():
        return tiny_pki.generate_server_certificate(
            ca_cert_pem,
            ca_key_pem,
            common_name,
            san_entries,
            validity_days=validity_days,
            key_size=key_size,
            allow_long_validity=True,
        )


def reencrypt_private_key(encrypted_data: bytes, old_secret_key: str) -> bytes:
    """Decrypt with old_secret_key and re-encrypt with the current SECRET_KEY."""
    return tiny_pki_secrets.reencrypt_private_key(encrypted_data, old_secret_key, settings.SECRET_KEY)


@contextmanager
def _tiny_pki_warnings_logged() -> Iterator[None]:
    """Log TinyPkiWarning as one record per issuance; pass other warnings through."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", TinyPkiWarning)
        yield
    pki_messages: list[str] = []
    for warning in caught:
        if issubclass(warning.category, TinyPkiWarning):
            pki_messages.append(str(warning.message))
        else:
            warnings.warn_explicit(warning.message, warning.category, warning.filename, warning.lineno)
    if pki_messages:
        logger.warning("Certificate issued with warnings: %s", "; ".join(pki_messages))
