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
from datetime import datetime
from datetime import timezone as _utc
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend

from app.pki import decrypt_private_key

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from app.models import FriendRequest, GlobalAutomationRule, SmtpConfig, Transition, TransitionAction

logger = logging.getLogger(__name__)


def _default_reply_to() -> str | None:
    """Return the default Reply-To address for outgoing email.

    If PUBLIC_DOMAIN is configured, we use a stable no-reply address on that
    domain so recipients can reply (if they choose) without exposing the SMTP
    server hostname.
    """
    public_domain = str(getattr(settings, "PUBLIC_DOMAIN", "") or "").strip()
    if not public_domain:
        return None
    return f"mytracks-no-reply@{public_domain}"


def _build_email(
    *,
    subject: str,
    body: str,
    to: list[str],
    from_email: str,
    connection: EmailBackend,
    reply_to: str | None = None,
) -> EmailMessage:
    """Create an EmailMessage with required headers enforced.

    Requirements:
    - Always set From:
    - Always set Reply-To: (defaults to mytracks-no-reply@<PUBLIC_DOMAIN> when configured)
    - Best-effort envelope sender: use from_email when supported
    """
    reply_to_addr = reply_to or _default_reply_to()
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to,
        connection=connection,
        reply_to=[reply_to_addr] if reply_to_addr else None,
    )

    # Best-effort envelope sender: Django uses from_email as the SMTP MAIL FROM,
    # but some backends / message implementations support explicitly setting it.
    if hasattr(msg, "envelope_sender"):
        try:
            setattr(msg, "envelope_sender", from_email)
        except Exception:
            # Never let envelope-sender support break delivery.
            pass

    return msg


def _format_footer_courier(*, sent_at: str | None, sent_by: str | None) -> str:
    parts: list[str] = []
    if sent_at:
        parts.append(f"Sent at: {sent_at}")
    if sent_by:
        parts.append(f"Sent by: {sent_by}")
    if not parts:
        return ""
    # Best-effort "Courier" formatting: many email clients render indented /
    # fenced blocks in a monospace font.
    return "\n".join(["```", *parts, "```"])


def _append_footer(body: str, *, sent_at: str | None = None, sent_by: str | None = None) -> str:
    footer = _format_footer_courier(sent_at=sent_at, sent_by=sent_by)
    if not footer:
        return body
    if body.endswith("\n"):
        return body + "\n" + footer + "\n"
    return body + "\n\n" + footer + "\n"


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
    public_domain = getattr(settings, "PUBLIC_DOMAIN", "")
    if public_domain:
        lines.append("")
        lines.append("Public domain: " + public_domain)
    if server_names:
        lines.append("")
        lines.append("Server: " + ", ".join(server_names))
    now = datetime.now(tz=_utc.utc)
    local_ts = now.astimezone(settings.SYSTEM_TIMEZONE)
    ts_str = f"{local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')} ({now.strftime('%Y-%m-%d %H:%M:%S UTC')})"
    public_domain = getattr(settings, "PUBLIC_DOMAIN", "")
    sent_by = public_domain or "my-tracks"
    _build_email(
        subject="my-tracks SMTP test",
        body=_append_footer("\n".join(lines), sent_at=ts_str, sent_by=sent_by),
        from_email=from_email,
        to=[to],
        connection=backend,
    ).send()


def send_test_email(to: str, config: "SmtpConfig", server_names: list[str] | None = None) -> None:
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


def send_friend_request_email(friend_request: "FriendRequest") -> None:
    """
    Notify a user that they received a friend request. Raises on failure.

    Skips silently (debug log) when SMTP is not configured or the recipient
    has no email address.
    """
    from app.models import SmtpConfig

    config = SmtpConfig.get()
    if config is None:
        logger.debug("send_friend_request_email: no SMTP config, skipping")
        return

    recipient = friend_request.to_user
    if not recipient.email:
        logger.debug("send_friend_request_email: recipient %s has no email, skipping", recipient.username)
        return

    sender = friend_request.from_user
    sender_label = sender.get_full_name().strip() or sender.username
    now = datetime.now(tz=_utc.utc)
    local_ts = now.astimezone(settings.SYSTEM_TIMEZONE)
    ts_str = f"{local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')} ({now.strftime('%Y-%m-%d %H:%M:%S UTC')})"
    public_domain = getattr(settings, "PUBLIC_DOMAIN", "")
    sent_by = public_domain or str(config.host)

    profile_path = "/profile/#friends"
    if public_domain:
        profile_url = f"https://{public_domain}{profile_path}"
    else:
        profile_url = profile_path

    subject = f"[my-tracks] Friend request from {sender.username}"
    lines = [
        f"{sender_label} ({sender.username}) sent you a friend request on my-tracks.",
        "",
        "Sign in and open Profile → Friends to accept or decline:",
        f"  {profile_url}",
        "",
    ]
    body = _append_footer("\n".join(lines), sent_at=ts_str, sent_by=sent_by)

    backend = get_smtp_backend(config)
    _build_email(
        subject=subject,
        body=body,
        from_email=str(config.from_address),
        to=[str(recipient.email)],
        connection=backend,
    ).send()
    logger.info(
        "Friend request email sent to %s (from=%s, request_id=%s)",
        recipient.email,
        sender.username,
        friend_request.pk,
    )


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
    display_name = owner.get_full_name() or owner.username if owner else device_name
    device_display = f"{owner.username}/{device_name}" if owner else device_name

    verb = "entered" if transition.event == "enter" else "left"
    local_ts = transition.timestamp.astimezone(settings.SYSTEM_TIMEZONE)
    utc_ts = transition.timestamp.astimezone(_utc.utc)
    ts_str = f"{local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')} ({utc_ts.strftime('%Y-%m-%d %H:%M:%S UTC')})"

    distance_line = ""
    if transition.latitude is not None and transition.longitude is not None and transition.waypoint is not None:
        dist_m = _haversine_m(
            float(str(transition.latitude)),
            float(str(transition.longitude)),
            float(str(transition.waypoint.latitude)),
            float(str(transition.waypoint.longitude)),
        )
        if dist_m >= 1000:
            distance_line = f"Distance from geofence center: {dist_m / 1000:.2f} km"
        else:
            distance_line = f"Distance from geofence center: {dist_m:.0f} m"

    public_domain = getattr(settings, "PUBLIC_DOMAIN", "")
    sent_by = public_domain or str(config.host)

    subject = f"[my-tracks] {display_name} {verb} {waypoint_label}"
    lines = [
        f"{display_name} {verb} {waypoint_label}.",
        "",
        f"  Event:    {transition.event}",
        f"  When:     {ts_str}",
        f"  User:     {display_name}",
        f"  Device:   {device_display}",
    ]
    if distance_line:
        lines.append(f"  {distance_line}")
    body = _append_footer("\n".join(lines), sent_at=ts_str, sent_by=sent_by)

    backend = get_smtp_backend(config)
    _build_email(
        subject=subject,
        body=body,
        from_email=str(config.from_address),
        to=[str(action.email_address)],
        connection=backend,
    ).send()
    logger.info(
        "Transition email sent to %s: %s %s %s",
        action.email_address,
        display_name,
        verb,
        waypoint_label,
    )


def send_global_automation_email(
    rule: "GlobalAutomationRule",
    triggered_by: "User",
    states: dict[str, str],
) -> None:
    """
    Send a notification email when a GlobalAutomationRule fires. Raises on failure.

    Args:
        rule: The GlobalAutomationRule that fired.
        triggered_by: The User whose new location triggered evaluation.
        states: Mapping of username → 'inside' | 'outside' | 'unknown'.
    """
    from app.models import GlobalAutomationRule, SmtpConfig

    config = SmtpConfig.get()
    if config is None:
        logger.debug("send_global_automation_email: no SMTP config, skipping")
        return

    condition_label = "inside" if rule.condition == GlobalAutomationRule.CONDITION_ALL_INSIDE else "outside"
    now = datetime.now(tz=_utc.utc)
    local_ts = now.astimezone(settings.SYSTEM_TIMEZONE)
    ts_str = f"{local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')} ({now.strftime('%Y-%m-%d %H:%M:%S UTC')})"
    public_domain = getattr(settings, "PUBLIC_DOMAIN", "")
    sent_by = public_domain or str(config.host)

    user_lines = "\n".join(f"      {uname}: {state}" for uname, state in sorted(states.items()))
    subject = f"[my-tracks] {rule.name} — all {condition_label} {rule.waypoint.label}"
    body = _append_footer(
        f'Global automation rule "{rule.name}" fired.\n'
        f"\n"
        f"  Condition:    All users {condition_label} {rule.waypoint.label}\n"
        f"  Triggered by: {triggered_by.username}\n"
        f"\n"
        f"  User states:\n"
        f"{user_lines}\n"
        f"\n",
        sent_at=ts_str,
        sent_by=sent_by,
    )

    backend = get_smtp_backend(config)
    _build_email(
        subject=subject,
        body=body,
        from_email=str(config.from_address),
        to=[str(rule.email_address)],
        connection=backend,
    ).send()
    logger.info(
        "Global automation email sent to %s (rule=%r, condition=%s)",
        rule.email_address,
        rule.name,
        rule.condition,
    )


def fire_global_automation_webhook(
    rule: "GlobalAutomationRule",
    triggered_by: "User",
    states: dict[str, str],
) -> None:
    """
    Fire an HTTP POST webhook when a GlobalAutomationRule fires.

    Uses stdlib urllib — no additional dependencies. Raises on failure.

    Args:
        rule: The GlobalAutomationRule that fired.
        triggered_by: The User whose new location triggered evaluation.
        states: Mapping of username → 'inside' | 'outside' | 'unknown'.
    """
    import json
    import urllib.request

    payload = {
        "rule_name": rule.name,
        "condition": rule.condition,
        "waypoint": {
            "label": rule.waypoint.label,
            "lat": float(str(rule.waypoint.latitude)),
            "lon": float(str(rule.waypoint.longitude)),
            "radius": rule.waypoint.radius,
        },
        "users_state": states,
        "triggered_by": triggered_by.username,
        "timestamp": datetime.now(tz=_utc.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        str(rule.webhook_url),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        status = resp.status
    logger.info(
        "Global automation webhook fired: url=%s status=%s (rule=%r)",
        rule.webhook_url,
        status,
        rule.name,
    )


def smtp_friendly_error(exc: Exception, host: str = "") -> str:
    """Translate low-level socket/SMTP exceptions into readable messages."""
    msg = str(exc)
    host_str = f" '{host}'" if host else ""
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
