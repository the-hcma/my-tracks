"""
MQTT Plugin for processing OwnTracks messages.

This plugin intercepts MQTT messages published to the broker and processes
OwnTracks location messages, saving them to the database and broadcasting
to WebSocket clients.
"""

import logging
import os
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as _tz
from typing import TYPE_CHECKING, Any

from amqtt.broker import BrokerContext
from amqtt.mqtt.connect import ConnectPacket
from amqtt.plugins.base import BasePlugin
from amqtt.session import ApplicationMessage, Session
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone as dj_tz

from app.models import (
    Device,
    GlobalAutomationRule,
    Location,
    LocationQualitySettings,
    OwnTracksMessage,
    Transition,
    Waypoint,
)
from app.mqtt.commands import Command, CommandPublisher
from app.mqtt.handlers import OwnTracksMessageHandler
from app.serializers import LocationSerializer
from app.ws_broadcast import STAFF_WS_GROUP

if TYPE_CHECKING:
    from channels.layers import BaseChannelLayer

logger = logging.getLogger(__name__)


@dataclass
class _ClientTLSInfo:
    """TLS identity for a connected MQTT client."""

    cn: str
    fingerprint: str

    def __str__(self) -> str:
        return f"CN={self.cn} [{self.fingerprint}]"


def _extract_tls_info(ssl_obj: ssl.SSLObject) -> _ClientTLSInfo | None:
    """Extract CN and fingerprint from a peer certificate on an SSL connection."""
    try:
        der_cert = ssl_obj.getpeercert(binary_form=True)
    except TypeError, ValueError:
        return None
    if der_cert is None or not isinstance(der_cert, (bytes, bytearray)):
        return None
    cert = x509.load_der_x509_certificate(der_cert)
    cn_attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    cn = str(cn_attrs[0].value) if cn_attrs else "unknown"
    digest = cert.fingerprint(hashes.SHA256())
    fingerprint = ":".join(f"{b:02X}" for b in digest[:4])
    return _ClientTLSInfo(cn=cn, fingerprint=fingerprint)


def get_channel_layer_lazy() -> "BaseChannelLayer | None":
    """Get channel layer, returning None if unavailable."""
    try:
        return get_channel_layer()
    except Exception:
        return None


def _device_display(data: dict[str, Any]) -> str:
    """Return 'owner/device_id' when mqtt_user is known, else plain device_id."""
    device = data.get("device", "")
    user = data.get("mqtt_user", "")
    return f"{user}/{device}" if user else str(device)


def get_other_devices(requesting_user: str) -> list[tuple[str, str]]:
    """
    Return (mqtt_user, device_id) pairs for all devices NOT owned by requesting_user.

    Used by the reportLocation relay to find which devices to forward the cmd to.
    Only returns devices that have an mqtt_user set (so a topic can be constructed).

    TODO: Once a Friend data model exists, restrict this to actual friends of
    requesting_user rather than all other known devices.
    """
    return list(
        Device.objects.exclude(mqtt_user=requesting_user).exclude(mqtt_user="").values_list("mqtt_user", "device_id")
    )


def save_location_to_db(location_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Save location data to the database.

    This function creates a Location model instance from the parsed
    OwnTracks message data. It also marks the device as online since
    receiving a location implies the device is connected.

    Args:
        location_data: Parsed location data from OwnTracksMessageHandler

    Returns:
        Serialized location data for WebSocket broadcast, or None on failure
    """
    try:
        # Get or create the device
        device_id = location_data["device"]
        device, _created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={"name": device_id},
        )

        # Mark device as online (receiving location = device is connected)
        # Also store mqtt_user from topic for command routing, and resolve owner
        # Explicitly update last_seen and last_location_at (auto_now only fires
        # on .save(), which we never call for existing devices).
        mqtt_user = location_data.get("mqtt_user", "")
        now = dj_tz.now()
        updates: dict[str, object] = {
            "last_seen": now,
            "last_location_at": now,
        }
        if not device.is_online:
            updates["is_online"] = True
        if mqtt_user and device.mqtt_user != mqtt_user:
            updates["mqtt_user"] = mqtt_user
        if device.owner_id is None:
            # Prefer TLS CN (authenticated identity) over mqtt_user (topic string)
            owner_username = location_data.get("tls_cn") or mqtt_user
            if owner_username:
                owner = User.objects.filter(username=owner_username).first()
                if owner is not None:
                    updates["owner"] = owner
        if updates:
            Device.objects.filter(pk=device.pk).update(**updates)
            device.refresh_from_db()

        # Create location from parsed data
        location = Location.objects.create(
            device=device,
            latitude=location_data["latitude"],
            longitude=location_data["longitude"],
            timestamp=location_data["timestamp"],
            tracker_id=location_data.get("tracker_id", ""),
            accuracy=location_data.get("accuracy"),
            altitude=location_data.get("altitude"),
            velocity=location_data.get("velocity"),
            battery_level=location_data.get("battery"),
            connection_type=location_data.get("connection", ""),
            ip_address=location_data.get("client_ip"),
            received_via="mqtt",
        )

        # Serialize for WebSocket broadcast
        serializer = LocationSerializer(location)
        # Cast to dict - serializer.data is ReturnDict which is dict-like
        return dict(serializer.data)

    except Exception:
        logger.exception("Failed to save location from MQTT message")
        return None


def save_lwt_to_db(lwt_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Process LWT data: mark device as offline and store the LWT message.

    Args:
        lwt_data: Parsed LWT data from OwnTracksMessageHandler

    Returns:
        Dictionary with device status info for WebSocket broadcast,
        or None on failure
    """
    try:
        device_id = lwt_data["device"]

        # Find the device
        try:
            device = Device.objects.select_related("owner").get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning("LWT received for unknown device: %s", device_id)
            return None

        # Mark device as offline
        Device.objects.filter(pk=device.pk).update(
            is_online=False,
            last_seen=dj_tz.now(),
        )

        # Store the LWT message for audit
        OwnTracksMessage.objects.create(
            device=device,
            message_type="lwt",
            payload={
                "event": lwt_data["event"],
                "connected_at": (lwt_data["connected_at"].isoformat() if lwt_data.get("connected_at") else None),
                "disconnected_at": lwt_data["disconnected_at"].isoformat(),
            },
        )

        device_display = f"{device.owner.username}/{device_id}" if device.owner else device_id
        return {
            "device_id": device_id,
            "device_display": device_display,
            "is_online": False,
            "event": "device_offline",
            "disconnected_at": lwt_data["disconnected_at"].isoformat(),
        }

    except Exception:
        logger.exception("Failed to process LWT for device")
        return None


def _format_event_ts(ts: datetime) -> str:
    """Format an event timestamp for log output.

    Uses UTC if the LOG_UTC env var is set; otherwise converts to the real
    system timezone (Django overrides TZ to UTC, so bare astimezone() won't work).
    """
    if os.environ.get("LOG_UTC"):
        return ts.astimezone(_tz.utc).strftime("%Y%m%d-%H:%M:%S")
    return ts.astimezone(settings.SYSTEM_TIMEZONE).strftime("%Y%m%d-%H:%M:%S")


def _fire_transition_actions(transition: Transition) -> None:
    """
    Evaluate TransitionAction rules and send emails for any that match.

    Called synchronously after the Transition row is committed.
    Failures are logged and suppressed so they never interrupt message processing.
    """
    from app.models import TransitionAction
    from app.notifications import send_transition_email

    owner = transition.device.owner
    if owner is None:
        return

    actions = TransitionAction.objects.filter(
        user=owner,
        is_active=True,
    ).select_related("waypoint")

    for action in actions:
        if action.waypoint is not None and action.waypoint != transition.waypoint:
            continue
        if action.event != TransitionAction.ANY and action.event != transition.event:
            continue
        try:
            send_transition_email(transition, action)
        except Exception:
            logger.exception(
                "Failed to send transition email (action_id=%s, to=%s)",
                action.pk,
                action.email_address,
            )


def _get_user_geofence_state(user: User, waypoint: Waypoint) -> str:
    """
    Return the server-computed geofence state for a user.

    Uses the most recent Location row for any device owned by the user and
    computes haversine distance to the waypoint center.

    Returns:
        'inside'  — latest location is within the waypoint radius
        'outside' — latest location is beyond the waypoint radius
        'unknown' — no location on record for this user
    """
    from app.notifications import _haversine_m  # avoid circular at import time

    qs = Location.objects.filter(device__owner=user)
    quality = LocationQualitySettings.objects.filter(pk=1).first()
    if quality is not None and quality.filter_accuracy_enabled:
        minimum_accuracy_m = quality.minimum_accuracy_meters
        qs = qs.filter(Q(accuracy__isnull=True) | Q(accuracy__lte=minimum_accuracy_m))
    latest = qs.order_by("-timestamp").select_related("device").first()
    if latest is None:
        return "unknown"

    dist = _haversine_m(
        float(str(latest.latitude)),
        float(str(latest.longitude)),
        float(str(waypoint.latitude)),
        float(str(waypoint.longitude)),
    )
    return "inside" if dist <= waypoint.radius else "outside"


def _evaluate_global_automations_for_user(user: User) -> None:
    """
    Re-evaluate all active GlobalAutomationRule rows that watch the given user.

    Called after every new Location is saved for the user. Fires email/webhook
    actions once when the condition transitions from not-met → met; resets the
    fire-once guard when condition is no longer met.
    Failures per action are logged and suppressed.
    """
    from app.notifications import fire_global_automation_webhook, send_global_automation_email

    rules = (
        GlobalAutomationRule.objects.filter(is_active=True, users=user)
        .prefetch_related("users")
        .select_related("waypoint")
    )

    rule_list = list(rules)
    logger.debug(
        "Location update for '%s' — evaluating %d global automation rule(s)",
        user.username,
        len(rule_list),
    )

    for rule in rule_list:
        watched_users = list(rule.users.all())
        states: dict[str, str] = {u.username: _get_user_geofence_state(u, rule.waypoint) for u in watched_users}
        state_values = list(states.values())

        if rule.condition == GlobalAutomationRule.CONDITION_ALL_INSIDE:
            condition_met = all(s == "inside" for s in state_values)
        else:  # CONDITION_ALL_OUTSIDE
            condition_met = all(s in ("outside", "unknown") for s in state_values)

        logger.debug(
            "Rule '%s' (id=%s): condition=%s states=%s → met=%s",
            rule.name,
            rule.pk,
            rule.condition,
            states,
            condition_met,
        )

        if condition_met and not rule.last_condition_met:
            # Condition newly met — fire
            logger.info(
                "Global automation '%s' fired (condition=%s, triggered_by=%s)",
                rule.name,
                rule.condition,
                user.username,
            )
            if rule.action_type == GlobalAutomationRule.ACTION_EMAIL and rule.email_address:
                try:
                    send_global_automation_email(rule, user, states)
                except Exception:
                    logger.exception("Failed to send global automation email (rule_id=%s)", rule.pk)
            if rule.action_type == GlobalAutomationRule.ACTION_WEBHOOK and rule.webhook_url:
                try:
                    fire_global_automation_webhook(rule, user, states)
                except Exception:
                    logger.exception("Failed to fire global automation webhook (rule_id=%s)", rule.pk)
            GlobalAutomationRule.objects.filter(pk=rule.pk).update(last_condition_met=True)
        elif not condition_met and rule.last_condition_met:
            # Condition reset — allow future firing
            GlobalAutomationRule.objects.filter(pk=rule.pk).update(last_condition_met=False)


def save_transition_to_db(transition_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Save a transition event to the database.

    Matches the incoming rid to an existing Waypoint FK if one exists;
    the FK stays null otherwise so no transition data is lost.

    Args:
        transition_data: Parsed transition data from OwnTracksMessageHandler

    Returns:
        Dictionary with transition info for WebSocket broadcast, or None on failure
    """
    try:
        device_id = transition_data["device"]
        try:
            device = Device.objects.select_related("owner").get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning("Transition received for unknown device: %s", device_id)
            return None

        region_id = transition_data.get("region_id", "")
        waypoint = Waypoint.objects.filter(rid=region_id).first() if region_id else None

        transition = Transition.objects.create(
            device=device,
            waypoint=waypoint,
            event=transition_data["event"],
            region_id=region_id,
            description=transition_data.get("description") or "",
            timestamp=transition_data["timestamp"],
            latitude=transition_data.get("latitude"),
            longitude=transition_data.get("longitude"),
            accuracy=transition_data.get("accuracy"),
        )

        _fire_transition_actions(transition)

        device_display = f"{device.owner.username}/{device_id}" if device.owner else device_id
        return {
            "id": transition.pk,
            "device_id": device_id,
            "device_display": device_display,
            "event": transition_data["event"],
            "region_id": region_id,
            "description": transition_data.get("description") or "",
            "timestamp": transition_data["timestamp"].isoformat(),
            "waypoint_label": waypoint.label if waypoint else None,
        }

    except Exception:
        logger.exception("Failed to save transition from MQTT message")
        return None


def save_waypoints_to_db(waypoint_data: dict[str, Any]) -> int:
    """
    Upsert waypoints received from a device.

    When a device publishes its waypoint list, this keeps the server in sync
    without overwriting label or geometry edits made through the web UI.

    Args:
        waypoint_data: Parsed waypoint data from OwnTracksMessageHandler

    Returns:
        Number of waypoints processed
    """
    try:
        device_id = waypoint_data["device"]
        try:
            device = Device.objects.select_related("owner").get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning("Waypoints received for unknown device: %s", device_id)
            return 0

        if device.owner is None:
            logger.warning("Waypoints received for device with no owner: %s", device_id)
            return 0

        valid_wps = [
            wp for wp in waypoint_data.get("waypoints", []) if wp.get("lat") is not None and wp.get("lon") is not None
        ]
        if not valid_wps:
            return 0

        count = 0
        for wp in valid_wps:
            desc = wp.get("desc") or ""
            lat = float(wp["lat"])
            lon = float(wp["lon"])
            rad = int(wp.get("rad", 100))
            rid = str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{device.owner.pk}:{desc}:{lat:.6f}:{lon:.6f}:{rad}",
                )
            )
            _, created = Waypoint.objects.get_or_create(
                rid=rid,
                defaults={
                    "user": device.owner,
                    "label": desc,
                    "latitude": wp["lat"],
                    "longitude": wp["lon"],
                    "radius": rad,
                },
            )
            if created:
                count += 1
                logger.debug("Waypoint created: desc=%r rid=%s", desc, rid)
            else:
                logger.debug("Waypoint already known (dup), skipping: desc=%r rid=%s", desc, rid)

        return count

    except Exception:
        logger.exception("Failed to save waypoints from MQTT message")
        return 0


class OwnTracksPlugin(BasePlugin[BrokerContext]):
    """
    MQTT Plugin that processes OwnTracks messages.

    This plugin hooks into the broker's message_received event and processes
    OwnTracks-formatted MQTT messages, saving locations to the database
    and broadcasting updates to WebSocket clients.
    """

    def __init__(self, context: BrokerContext) -> None:
        """Initialize the OwnTracks plugin."""
        super().__init__(context)
        self._handler = OwnTracksMessageHandler()
        self._setup_callbacks()
        self._client_tls: dict[str, _ClientTLSInfo | None] = {}
        logger.info("OwnTracksPlugin initialized")

    def _setup_callbacks(self) -> None:
        """Register callbacks for different message types."""
        self._handler.on_location(self._handle_location)
        self._handler.on_lwt(self._handle_lwt)
        self._handler.on_transition(self._handle_transition)
        self._handler.on_waypoint(self._handle_waypoints_from_device)
        self._handler.on_cmd(self._handle_cmd_from_device)

    def _get_handler_writer_ssl(self, client_id: str) -> ssl.SSLObject | None:
        """Try to get the SSL object from a client's handler writer."""
        try:
            broker = self.context._broker_instance  # noqa: SLF001
            entry = broker._sessions.get(client_id)  # noqa: SLF001
            if entry is None:
                return None
            _session, handler = entry
            if handler.writer is None:
                return None
            return handler.writer.get_ssl_info()
        except Exception:
            return None

    def _live_ssl_for_client(
        self,
        client_id: str,
        session: Any | None = None,
    ) -> ssl.SSLObject | None:
        """Return the live TLS peer for a client, if any.

        Prefer the attached writer (current connection). Fall back to
        ``session.ssl_object`` so in-flight publishes after a brief disconnect
        (e.g. session take-over) still log as ``[mqtt-tls]`` when appropriate.
        """
        ssl_obj = self._get_handler_writer_ssl(client_id)
        if ssl_obj is not None:
            return ssl_obj
        if session is None:
            session = self.context.get_session(client_id)
        if session is None:
            return None
        session_ssl = getattr(session, "ssl_object", None)
        if isinstance(session_ssl, ssl.SSLObject):
            return session_ssl
        return None

    def _live_tls_info_for_client(
        self,
        client_id: str,
        session: Any | None = None,
    ) -> _ClientTLSInfo | None:
        """Return TLS identity from the live connection or session binding."""
        cached = self._client_tls.get(client_id)
        if cached is not None:
            return cached
        ssl_obj = self._live_ssl_for_client(client_id, session=session)
        if ssl_obj is None:
            return None
        return _extract_tls_info(ssl_obj)

    def _transport(self, client_id: str, session: Any | None = None) -> str:
        """Return the transport tag for a client: ``mqtt-tls`` or ``mqtt``."""
        if self._live_ssl_for_client(client_id, session=session) is not None:
            return "mqtt-tls"
        if client_id in self._client_tls and self._client_tls[client_id] is not None:
            return "mqtt-tls"
        return "mqtt"

    def _identity(self, client_id: str, session: Any | None = None) -> str:
        """Return TLS identity suffix like ``(CN=hcma [AA:BB:CC:DD])`` or ``""``."""
        tls_info = self._live_tls_info_for_client(client_id, session=session)
        if tls_info is not None:
            return f" ({tls_info})"
        return ""

    async def on_broker_client_connected(
        self,
        *,
        client_id: str,
        client_session: Session,
    ) -> None:
        """Log client connections with TLS identity when available."""
        addr = client_session.remote_address or "unknown"

        ssl_obj = self._get_handler_writer_ssl(client_id)
        if ssl_obj is not None:
            tls_info = _extract_tls_info(ssl_obj)
            self._client_tls[client_id] = tls_info
            if tls_info:
                logger.info(
                    "[mqtt-tls] Client connected: %s from %s (%s)",
                    client_id,
                    addr,
                    tls_info,
                )
            else:
                logger.info(
                    "[mqtt-tls] Client connected: %s from %s (no client cert)",
                    client_id,
                    addr,
                )
        else:
            self._client_tls[client_id] = None
            logger.info(
                "[mqtt] Client connected: %s from %s",
                client_id,
                addr,
            )

    async def on_broker_client_disconnected(
        self,
        *,
        client_id: str,
        client_session: Session,
    ) -> None:
        """Clean up cached TLS info on disconnect."""
        transport = self._transport(client_id)
        identity = self._identity(client_id)
        self._client_tls.pop(client_id, None)
        logger.info("[%s] Client disconnected: %s%s", transport, client_id, identity)

    async def _handle_location(self, location_data: dict[str, Any]) -> None:
        """
        Handle a parsed location message.

        Saves to database and broadcasts via WebSocket.
        """
        transport = location_data.get("transport", "mqtt")
        identity = location_data.get("tls_identity", "")

        logger.debug(
            "[%s] Processing location: device=%s, lat=%s, lon=%s",
            transport,
            _device_display(location_data),
            location_data.get("latitude"),
            location_data.get("longitude"),
        )

        # thread_sensitive=False: the MQTT broker runs in its own asyncio loop,
        # outside Django/ASGI's request lifecycle. The default thread_sensitive=True
        # would try to use asgiref's CurrentThreadExecutor, which is only set up
        # per ASGI request and crashes here with "CurrentThreadExecutor already quit
        # or is broken". thread_sensitive=False routes to the global thread pool.
        serialized = await sync_to_async(save_location_to_db, thread_sensitive=False)(location_data)
        if serialized is None:
            return

        logger.info(
            "[%s] Location saved: id=%s, device=%s%s",
            transport,
            serialized.get("id"),
            serialized.get("device_id_display"),
            identity,
        )

        location = await sync_to_async(
            Location.objects.select_related("device", "device__owner").get,
            thread_sensitive=False,
        )(pk=serialized["id"])
        owner = location.device.owner
        if owner is not None:
            from app.domesti_relay import relay_location_to_domesti_bot

            await sync_to_async(_evaluate_global_automations_for_user, thread_sensitive=False)(owner)
            await sync_to_async(relay_location_to_domesti_bot, thread_sensitive=False)(location)

        logger.info(
            "[%s] Broadcasting location to WebSocket (id=%s, device=%s)",
            transport,
            serialized.get("id"),
            serialized.get("device_id_display"),
        )
        await self._broadcast_location(serialized, transport=transport)

    async def _handle_lwt(self, lwt_data: dict[str, Any]) -> None:
        """
        Handle a parsed LWT (Last Will and Testament) message.

        LWT messages indicate a device has gone offline. This marks the
        device as offline in the database and broadcasts the status change.
        """
        transport = lwt_data.get("transport", "mqtt")

        logger.info(
            "[%s] Device offline via LWT: device=%s",
            transport,
            _device_display(lwt_data),
        )

        # thread_sensitive=False: same reason as in _handle_location.
        status_data = await sync_to_async(save_lwt_to_db, thread_sensitive=False)(lwt_data)
        if status_data is None:
            return

        logger.info(
            "[%s] Device marked offline: device=%s",
            transport,
            status_data.get("device_display"),
        )

        await self._broadcast_device_status(status_data, transport=transport)

    async def _handle_transition(self, transition_data: dict[str, Any]) -> None:
        """
        Handle a parsed transition message.

        Saves to database and broadcasts via WebSocket.
        """
        transport = transition_data.get("transport", "mqtt")
        identity = transition_data.get("tls_identity", "")

        ts = transition_data.get("timestamp")
        ts_str = _format_event_ts(ts) if isinstance(ts, datetime) else "unknown"
        logger.info(
            "[%s] Transition: device=%s, event=%s, region=%s, at=%s%s",
            transport,
            _device_display(transition_data),
            transition_data.get("event"),
            transition_data.get("description"),
            ts_str,
            identity,
        )

        # thread_sensitive=False: same reason as in _handle_location.
        saved = await sync_to_async(save_transition_to_db, thread_sensitive=False)(transition_data)
        if saved is None:
            return

        logger.info(
            "[%s] Transition saved: id=%s, device=%s, event=%s, waypoint=%s",
            transport,
            saved.get("id"),
            saved.get("device_display"),
            saved.get("event"),
            saved.get("waypoint_label") or saved.get("region_id"),
        )

        await self._broadcast_transition(saved, transport=transport)

    async def _handle_cmd_from_device(self, cmd_data: dict[str, Any]) -> None:
        """
        Handle a cmd message received on a device's /cmd topic.

        ## OwnTracks Android version history — why relay is needed

        In OwnTracks Android ≤ v2.5.4, MessageCmd.annotateFromPreferences()
        unconditionally overwrote the outgoing topic with the sender's own
        /cmd topic (preferences.receivedCommandsTopic), regardless of what
        MapViewModel.sendLocationRequestToCurrentContact() had set.  As a
        result, a reportLocation request for *any* friend always arrived on
        the requester's own topic (e.g. owntracks/hcma/pixel7pro/cmd) rather
        than on the friend's topic.  The server must relay the command to all
        other known devices to reach the intended recipient.

        This was fixed in v2.5.5 (owntracks/android#2101): from v2.5.5 onward,
        annotateFromPreferences() is a no-op for MessageCmd, so MapViewModel's
        `topic = it.id + "/cmd"` is preserved and the message is published
        directly to the friend's /cmd topic (e.g. owntracks/kristen/pixel7/cmd).
        The broker delivers it without any server-side relay; our auth fix
        allows cross-user publish to /cmd subtopics.

        TODO: Once a Friend data model exists, restrict the relay (and the
        auth allow-list in auth.py) to actual friends rather than all other
        known devices.
        """
        action = cmd_data.get("action", "")
        transport = cmd_data.get("transport", "mqtt")
        topic = cmd_data.get("topic", "")
        # Prefer TLS CN (authenticated identity) as "who published the cmd".
        # Falling back to mqtt_user (derived from topic) is only safe for non-TLS.
        requesting_user = cmd_data.get("tls_cn") or cmd_data.get("mqtt_user", "")
        topic_user = cmd_data.get("user", "")

        logger.debug(
            "[%s] Observed cmd action=%r on topic=%s",
            transport,
            action,
            topic,
        )

        # Relay reportLocation to all other devices when the cmd arrived on
        # the requester's OWN topic — this is the ≤ v2.5.4 app behaviour
        # described above (fixed in v2.5.5, owntracks/android#2101).
        if action != "reportLocation" or not requesting_user or topic_user != requesting_user:
            return

        other_devices = await sync_to_async(get_other_devices, thread_sensitive=False)(requesting_user)

        if not other_devices:
            logger.debug(
                "[%s] reportLocation relay: no other devices found, nothing to relay",
                transport,
            )
            return

        broker = self.context._broker_instance  # noqa: SLF001
        publisher = CommandPublisher(mqtt_client=broker)
        cmd = Command.report_location()

        for mqtt_user, device_id in other_devices:
            device_topic_id = f"{mqtt_user}/{device_id}"
            logger.info(
                "[%s] reportLocation relay: %s → %s",
                transport,
                requesting_user,
                device_topic_id,
            )
            await publisher.send_command(device_topic_id, cmd)

    async def _handle_waypoints_from_device(self, waypoint_data: dict[str, Any]) -> None:
        """
        Handle an incoming waypoint list published by a device.

        Upserts Waypoint rows by rid to keep the server in sync with the device.
        """
        transport = waypoint_data.get("transport", "mqtt")
        device_display = _device_display(waypoint_data)
        count = len(waypoint_data.get("waypoints", []))

        logger.info(
            "[%s] Waypoints from device: device=%s, count=%d",
            transport,
            device_display,
            count,
        )

        # thread_sensitive=False: same reason as in _handle_location.
        saved = await sync_to_async(save_waypoints_to_db, thread_sensitive=False)(waypoint_data)
        logger.info(
            "[%s] Waypoints upserted: device=%s, new=%d, dup=%d",
            transport,
            device_display,
            saved,
            count - saved,
        )
        if saved > 0:
            await self._broadcast_waypoints(
                {"device_display": device_display, "new_count": saved},
                transport=transport,
            )

    async def _broadcast_location(
        self,
        location_data: dict[str, Any],
        *,
        transport: str = "mqtt",
    ) -> None:
        """Broadcast a location update to the device owner, shared friends, and staff."""
        from app.models import Device
        from app.ws_broadcast import broadcast_device_event

        channel_layer = get_channel_layer_lazy()
        if channel_layer is None:
            logger.warning("[%s] WebSocket broadcast skipped: no channel layer", transport)
            return

        device_pk = location_data.get("device")
        if device_pk is None:
            logger.warning("[%s] WebSocket broadcast skipped: location missing device pk", transport)
            return

        try:
            device = await sync_to_async(Device.objects.select_related("owner").get)(pk=device_pk)
            await broadcast_device_event(
                channel_layer,
                device,
                message_type="location_update",
                data=location_data,
            )
            logger.info(
                "[%s] WebSocket broadcast completed for location %s",
                transport,
                location_data.get("id"),
            )
        except Exception:
            logger.exception("[%s] WebSocket broadcast failed", transport)

    async def _broadcast_device_status(
        self,
        status_data: dict[str, Any],
        *,
        transport: str = "mqtt",
    ) -> None:
        """Broadcast a device status change to the owner, shared friends, and staff."""
        from app.models import Device
        from app.ws_broadcast import broadcast_device_event

        channel_layer = get_channel_layer_lazy()
        if channel_layer is None:
            logger.warning("[%s] WebSocket broadcast skipped: no channel layer", transport)
            return

        device_id = status_data.get("device_id")
        if not device_id:
            logger.warning("[%s] WebSocket broadcast skipped: status missing device_id", transport)
            return

        try:
            device = await sync_to_async(Device.objects.select_related("owner").get)(device_id=device_id)
            await broadcast_device_event(
                channel_layer,
                device,
                message_type="device_status",
                data=status_data,
            )
            logger.info(
                "[%s] WebSocket broadcast completed for device status: device=%s, online=%s",
                transport,
                status_data.get("device_display"),
                status_data.get("is_online"),
            )
        except Exception:
            logger.exception("[%s] WebSocket broadcast failed for device status", transport)

    async def _broadcast_waypoints(
        self,
        waypoint_data: dict[str, Any],
        *,
        transport: str = "mqtt",
    ) -> None:
        """Broadcast a waypoint sync event to WebSocket clients."""
        channel_layer = get_channel_layer_lazy()
        if channel_layer is None:
            logger.warning("[%s] WebSocket broadcast skipped: no channel layer", transport)
            return

        try:
            await channel_layer.group_send(
                STAFF_WS_GROUP,
                {
                    "type": "waypoint_event",
                    "data": waypoint_data,
                },
            )
            logger.info(
                "[%s] WebSocket broadcast completed for waypoints: device=%s, new=%d",
                transport,
                waypoint_data.get("device_display"),
                waypoint_data.get("new_count"),
            )
        except Exception:
            logger.exception("[%s] WebSocket broadcast failed for waypoints", transport)

    async def _broadcast_transition(
        self,
        transition_data: dict[str, Any],
        *,
        transport: str = "mqtt",
    ) -> None:
        """Broadcast a geofence transition event to WebSocket clients."""
        channel_layer = get_channel_layer_lazy()
        if channel_layer is None:
            logger.warning("[%s] WebSocket broadcast skipped: no channel layer", transport)
            return

        try:
            await channel_layer.group_send(
                STAFF_WS_GROUP,
                {
                    "type": "transition_event",
                    "data": transition_data,
                },
            )
            logger.info(
                "[%s] WebSocket broadcast completed for transition: id=%s, device=%s",
                transport,
                transition_data.get("id"),
                transition_data.get("device_display"),
            )
        except Exception:
            logger.exception("[%s] WebSocket broadcast failed for transition", transport)

    # -- Protocol version check ------------------------------------------

    # MQTT v3.1.1 = protocol level 4.  OwnTracks on Android defaults to
    # v3.1 (protocol level 3, proto_name "MQIsdp") which amqtt rejects.
    _MQTT_V31_PROTO_NAME = "MQIsdp"
    _MQTT_V311_LEVEL = 4

    async def on_mqtt_packet_received(self, *, packet: Any, session: Any = None) -> None:
        """Log a helpful message when a client uses MQTT v3.1.

        amqtt only supports MQTT v3.1.1 (protocol level 4).  When an
        OwnTracks client connects with v3.1 the broker rejects the
        connection but the default error is opaque.  This handler fires
        *before* the rejection so we can tell the user exactly how to fix
        it.
        """
        # Only inspect CONNECT packets
        if not isinstance(packet, ConnectPacket):
            return

        vh = packet.variable_header
        if vh is None:
            return

        proto_name: str = vh.proto_name
        proto_level: int = vh.proto_level

        if proto_name == self._MQTT_V31_PROTO_NAME or proto_level < self._MQTT_V311_LEVEL:
            logger.warning(
                "MQTT v3.1 connection detected (proto_name=%r, proto_level=%d). "
                "This broker requires MQTT v3.1.1 (protocol level 4). "
                "To reconfigure OwnTracks: save a file containing "
                '\'{"_type": "configuration", "mqttProtocolLevel": 4}\' '
                "to your phone and open it with OwnTracks.",
                proto_name,
                proto_level,
            )

    # -- Message processing ----------------------------------------------

    async def on_broker_message_received(
        self,
        *,
        client_id: str,
        message: ApplicationMessage,
    ) -> None:
        """
        Process a message received by the broker.

        This is the main hook that amqtt calls for each published message.

        Args:
            client_id: The client ID that published the message
            message: The application message containing topic and payload
        """
        topic = message.topic

        # Quick filter: only process owntracks topics
        if not topic.startswith("owntracks/"):
            return

        session = self.context.get_session(client_id)
        transport = self._transport(client_id, session=session)
        identity = self._identity(client_id, session=session)
        logger.debug(
            "[%s] Message received: client=%s%s, topic=%s, size=%d",
            transport,
            client_id,
            identity,
            topic,
            len(message.data) if message.data else 0,
        )

        client_ip: str | None = None
        if session is not None:
            client_ip = session.remote_address

        tls_info = self._live_tls_info_for_client(client_id, session=session)
        tls_cn = tls_info.cn if tls_info is not None else ""
        payload = bytes(message.data) if isinstance(message.data, bytearray) else message.data
        await self._handler.handle_message(
            topic,
            payload,
            client_ip=client_ip,
            transport=transport,
            tls_identity=identity,
            tls_cn=tls_cn,
        )
