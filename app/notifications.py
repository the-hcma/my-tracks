"""
Email notification helpers.

Provides functions for sending emails via the admin-configured SMTP server.
All functions that send email raise on failure — callers are responsible for
catching and logging.
"""
import logging
import math
import smtplib
import socket
from datetime import timezone as _utc
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend

from app.pki import decrypt_private_key

if TYPE_CHECKING:
    from app.models import SmtpConfig, Transition, TransitionAction

logger = logging.getLogger(__name__)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two WGS-84 points."""
    r = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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


def send_test_email_via_backend(
    to: str, backend: EmailBackend, from_email: str, server_names: list[str] | None = None
) -> None:
    """
    Send a test email using an already-constructed EmailBackend. Raises on failure.

    Args:
        to: Recipient email address
        backend: Configured EmailBackend (not yet connected)
        from_email: From address for the test message
        server_names: DNS names / IPs from the active server certificate SANs,
            included in the body so the recipient can identify the sender.
    """
    lines = ["SMTP is configured correctly. This is a test message from my-tracks."]
    public_domain = getattr(settings, 'PUBLIC_DOMAIN', '')
    if public_domain:
        lines.append("")
        lines.append("Public domain: " + public_domain)
    if server_names:
        lines.append("")
        lines.append("Server: " + ", ".join(server_names))
    EmailMessage(
        subject="my-tracks SMTP test",
        body="\n".join(lines),
        from_email=from_email,
        to=[to],
        connection=backend,
    ).send()


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
    send_test_email_via_backend(to, backend, str(config.from_address), server_names)
    logger.info("Test email sent to %s via %s:%s", to, config.host, config.port)


def send_transition_email(transition: "Transition", action: "TransitionAction") -> None:
    """
    Send a notification email for a geofence transition event. Raises on failure.

    Args:
        transition: The Transition instance that fired.
        action: The TransitionAction rule that matched.
    """
    from app.models import SmtpConfig
    config = SmtpConfig.get()
    if config is None:
        logger.debug("send_transition_email: no SMTP config, skipping")
        return

    device_name = transition.device.name or transition.device.device_id
    waypoint_label = (
        transition.waypoint.label if transition.waypoint else transition.description
    ) or "unknown geofence"
    owner = transition.device.owner
    display_name = (
        owner.get_full_name() or owner.username if owner else device_name
    )
    device_display = (
        f"{owner.username}/{device_name}" if owner else device_name
    )

    verb = "entered" if transition.event == "enter" else "left"
    local_ts = transition.timestamp.astimezone(settings.SYSTEM_TIMEZONE)
    utc_ts = transition.timestamp.astimezone(_utc.utc)
    ts_str = (
        f"{local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        f" ({utc_ts.strftime('%Y-%m-%d %H:%M:%S UTC')})"
    )

    distance_line = ""
    if (
        transition.latitude is not None
        and transition.longitude is not None
        and transition.waypoint is not None
    ):
        dist_m = _haversine_m(
            float(str(transition.latitude)), float(str(transition.longitude)),
            float(str(transition.waypoint.latitude)), float(str(transition.waypoint.longitude)),
        )
        if dist_m >= 1000:
            distance_line = f"Distance from geofence center: {dist_m / 1000:.2f} km"
        else:
            distance_line = f"Distance from geofence center: {dist_m:.0f} m"

    public_domain = getattr(settings, "PUBLIC_DOMAIN", "")
    sent_by = public_domain or config.host

    subject = f"[my-tracks] {display_name} {verb} {waypoint_label}"
    lines = [
        f"{display_name} {verb} {waypoint_label}.",
        "",
        f"  Event:    {transition.event}",
        f"  When:     {ts_str}",
        f"  User:     {display_name}",
        f"  Device:   {device_display}",
        f"  Sent by:  {sent_by}",
    ]
    if distance_line:
        lines.append(f"  {distance_line}")
    body = "\n".join(lines)

    backend = get_smtp_backend(config)
    EmailMessage(
        subject=subject,
        body=body,
        from_email=config.from_address,
        to=[action.email_address],
        connection=backend,
    ).send()
    logger.info(
        "Transition email sent to %s: %s %s %s",
        action.email_address, display_name, verb, waypoint_label,
    )


def smtp_friendly_error(exc: Exception, host: str = '') -> str:
    """Translate low-level socket/SMTP exceptions into readable messages."""
    msg = str(exc)
    host_str = f" '{host}'" if host else ''
    if isinstance(exc, socket.gaierror):
        return f"Could not resolve hostname{host_str} — check that the SMTP host is correct."
    if isinstance(exc, ConnectionRefusedError):
        return (
            f"Connection to{host_str} was refused — verify the host and port are correct"
            f" and that no firewall is blocking the connection."
        )
    if isinstance(exc, TimeoutError):
        return (
            f"Connection to{host_str} timed out — verify the host and port are correct"
            f" and that no firewall is blocking the connection."
        )
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return f"Authentication failed — check the username and password. ({msg})"
    if isinstance(exc, smtplib.SMTPNotSupportedError) and "AUTH" in msg:
        return (
            "The server does not support SMTP authentication. "
            "If this is an unauthenticated relay (e.g. a local or internal mail server), "
            "leave Username and Password blank."
        )
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return f"The server does not support a required feature — check your TLS/SSL settings. ({msg})"
    if isinstance(exc, smtplib.SMTPConnectError):
        return (
            f"Could not connect to the server{host_str} — verify the host and port are correct"
            f" and the server is reachable. ({msg})"
        )
    if isinstance(exc, smtplib.SMTPException):
        return f"SMTP error: {msg}"
    return msg
