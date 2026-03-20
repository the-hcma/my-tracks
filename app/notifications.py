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
from typing import TYPE_CHECKING

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

    verb = "entered" if transition.event == "enter" else "left"
    ts_str = transition.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

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

    subject = f"[my-tracks] {display_name} {verb} {waypoint_label}"
    lines = [
        f"{display_name} {verb} {waypoint_label}.",
        "",
        f"  Event:  {transition.event}",
        f"  When:   {ts_str}",
        f"  Device: {device_name}",
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
