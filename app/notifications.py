"""
Email notification helpers.

Provides functions for sending emails via the admin-configured SMTP server.
All functions that send email raise on failure — callers are responsible for
catching and logging.
"""
import logging
import smtplib
import socket
from typing import TYPE_CHECKING

from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend

from app.pki import decrypt_private_key

if TYPE_CHECKING:
    from app.models import SmtpConfig

logger = logging.getLogger(__name__)


def get_smtp_backend(config: "SmtpConfig") -> EmailBackend:
    """
    Build a Django EmailBackend from a SmtpConfig instance.

    Args:
        config: Populated SmtpConfig singleton

    Returns:
        Configured EmailBackend (not yet connected)
    """
    password = ""
    if config.encrypted_password:
        password = decrypt_private_key(bytes(memoryview(config.encrypted_password))).decode()  # type: ignore[arg-type]
    return EmailBackend(
        host=config.host,
        port=config.port,
        username=config.username,
        password=password,
        use_tls=config.use_tls,
        use_ssl=config.use_ssl,
        timeout=10,
        fail_silently=False,
    )


def send_test_email(
    to: str, config: "SmtpConfig", server_names: list[str] | None = None
) -> None:
    """
    Send a test email to verify SMTP connectivity. Raises on failure.

    Args:
        to: Recipient email address
        config: SmtpConfig to use for the connection
        server_names: DNS names / IPs from the active server certificate SANs,
            included in the body so the recipient can identify the sender.
    """
    backend = get_smtp_backend(config)
    lines = ["SMTP is configured correctly. This is a test message from my-tracks."]
    if server_names:
        lines.append("")
        lines.append("Server: " + ", ".join(server_names))
    msg = EmailMessage(
        subject="my-tracks SMTP test",
        body="\n".join(lines),
        from_email=config.from_address,
        to=[to],
        connection=backend,
    )
    msg.send()
    logger.info("Test email sent to %s via %s:%s", to, config.host, config.port)


def smtp_friendly_error(exc: Exception) -> str:
    """Translate low-level socket/SMTP exceptions into readable messages."""
    if isinstance(exc, socket.gaierror):
        return "Could not resolve hostname — check the SMTP host."
    if isinstance(exc, ConnectionRefusedError):
        return "Connection refused — check the host and port."
    if isinstance(exc, TimeoutError):
        return "Connection timed out — check the host and port."
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Authentication failed — check the username and password."
    if isinstance(exc, smtplib.SMTPException):
        return f"SMTP error: {exc}"
    return str(exc)
