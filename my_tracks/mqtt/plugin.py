"""
MQTT Plugin for processing OwnTracks messages.

This plugin intercepts MQTT messages published to the broker and processes
OwnTracks location messages, saving them to the database and broadcasting
to WebSocket clients.
"""

import logging
import ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from amqtt.broker import BrokerContext
from amqtt.mqtt.connect import ConnectPacket
from amqtt.plugins.base import BasePlugin
from amqtt.session import ApplicationMessage, Session
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from my_tracks.models import Device, Location, OwnTracksMessage
from my_tracks.mqtt.handlers import OwnTracksMessageHandler
from my_tracks.serializers import LocationSerializer

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
    der_cert = ssl_obj.getpeercert(binary_form=True)
    if der_cert is None:
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
            defaults={"name": f"Device {device_id}"},
        )

        # Mark device as online (receiving location = device is connected)
        # Also store mqtt_user from topic for command routing
        mqtt_user = location_data.get("mqtt_user", "")
        updates: dict[str, object] = {}
        if not device.is_online:
            updates["is_online"] = True
        if mqtt_user and device.mqtt_user != mqtt_user:
            updates["mqtt_user"] = mqtt_user
        if updates:
            Device.objects.filter(pk=device.pk).update(**updates)

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
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning("LWT received for unknown device: %s", device_id)
            return None

        # Mark device as offline
        Device.objects.filter(pk=device.pk).update(is_online=False)

        # Store the LWT message for audit
        OwnTracksMessage.objects.create(
            device=device,
            message_type="lwt",
            payload={
                "event": lwt_data["event"],
                "connected_at": (
                    lwt_data["connected_at"].isoformat()
                    if lwt_data.get("connected_at")
                    else None
                ),
                "disconnected_at": lwt_data["disconnected_at"].isoformat(),
            },
        )

        return {
            "device_id": device_id,
            "is_online": False,
            "event": "device_offline",
            "disconnected_at": lwt_data["disconnected_at"].isoformat(),
        }

    except Exception:
        logger.exception("Failed to process LWT for device")
        return None


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
                    "[MQTT] Client connected: %s from %s via TLS (%s)",
                    client_id, addr, tls_info,
                )
            else:
                logger.info(
                    "[MQTT] Client connected: %s from %s via TLS (no client cert)",
                    client_id, addr,
                )
        else:
            self._client_tls[client_id] = None
            logger.info(
                "[MQTT] Client connected: %s from %s (non-TLS)",
                client_id, addr,
            )

    async def on_broker_client_disconnected(
        self,
        *,
        client_id: str,
        client_session: Session,
    ) -> None:
        """Clean up cached TLS info on disconnect."""
        tls_info = self._client_tls.pop(client_id, None)
        tag = f" TLS ({tls_info})" if tls_info else " (non-TLS)"
        logger.info("[MQTT] Client disconnected: %s%s", client_id, tag)

    def _tls_tag(self, client_id: str) -> str:
        """Return a short TLS descriptor for log messages."""
        tls_info = self._client_tls.get(client_id)
        if tls_info is not None:
            return f"TLS {tls_info}"
        if client_id in self._client_tls:
            return "non-TLS"
        return "unknown"

    async def _handle_location(self, location_data: dict[str, Any]) -> None:
        """
        Handle a parsed location message.

        Saves to database and broadcasts via WebSocket.
        """
        logger.debug(
            "Processing MQTT location: device=%s, lat=%s, lon=%s",
            location_data.get("device"),
            location_data.get("latitude"),
            location_data.get("longitude"),
        )

        # Save to database (sync operation wrapped for async)
        serialized = await sync_to_async(save_location_to_db)(location_data)
        if serialized is None:
            return

        logger.info(
            "[MQTT] Location saved: id=%s, device=%s (%s)",
            serialized.get("id"),
            serialized.get("device_id_display"),
            location_data.get("tls_tag", "unknown"),
        )

        logger.info(
            "[MQTT] 📡 Broadcasting location to WebSocket (id=%s, device=%s)",
            serialized.get("id"),
            serialized.get("device_id_display"),
        )
        await self._broadcast_location(serialized)

    async def _handle_lwt(self, lwt_data: dict[str, Any]) -> None:
        """
        Handle a parsed LWT (Last Will and Testament) message.

        LWT messages indicate a device has gone offline. This marks the
        device as offline in the database and broadcasts the status change.
        """
        logger.info(
            "[MQTT] Device offline via LWT: device=%s",
            lwt_data.get("device"),
        )

        # Save LWT to database and mark device offline
        status_data = await sync_to_async(save_lwt_to_db)(lwt_data)
        if status_data is None:
            return

        logger.info(
            "[MQTT] Device marked offline: device=%s",
            status_data.get("device_id"),
        )

        # Broadcast device status change via WebSocket
        await self._broadcast_device_status(status_data)

    async def _handle_transition(self, transition_data: dict[str, Any]) -> None:
        """
        Handle a parsed transition message.

        Transition messages indicate region enter/exit events.
        """
        logger.info(
            "[MQTT] Transition: device=%s, event=%s, region=%s (%s)",
            transition_data.get("device"),
            transition_data.get("event"),
            transition_data.get("description"),
            transition_data.get("tls_tag", "unknown"),
        )
        # TODO: Store transition events when model supports it

    async def _broadcast_location(self, location_data: dict[str, Any]) -> None:
        """
        Broadcast a location update to WebSocket clients.

        Args:
            location_data: Serialized location data to broadcast
        """
        channel_layer = get_channel_layer_lazy()
        if channel_layer is None:
            logger.warning("WebSocket broadcast skipped: no channel layer configured")
            return

        try:
            await channel_layer.group_send(
                "locations",
                {
                    "type": "location_update",
                    "data": location_data,
                },
            )
            logger.info(
                "[MQTT] ✅ WebSocket broadcast completed for location %s",
                location_data.get("id"),
            )
        except Exception:
            logger.exception("[MQTT] WebSocket broadcast failed")

    async def _broadcast_device_status(self, status_data: dict[str, Any]) -> None:
        """
        Broadcast a device status change to WebSocket clients.

        Args:
            status_data: Device status data including device_id and is_online
        """
        channel_layer = get_channel_layer_lazy()
        if channel_layer is None:
            logger.warning("WebSocket broadcast skipped: no channel layer configured")
            return

        try:
            await channel_layer.group_send(
                "locations",
                {
                    "type": "device_status",
                    "data": status_data,
                },
            )
            logger.info(
                "[MQTT] ✅ WebSocket broadcast completed for device status: device=%s, online=%s",
                status_data.get("device_id"),
                status_data.get("is_online"),
            )
        except Exception:
            logger.exception("[MQTT] WebSocket broadcast failed for device status")

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

        tls_tag = self._tls_tag(client_id)
        logger.debug(
            "MQTT message received: client=%s (%s), topic=%s, size=%d",
            client_id,
            tls_tag,
            topic,
            len(message.data) if message.data else 0,
        )

        # Look up client IP from broker session
        client_ip: str | None = None
        session = self.context.get_session(client_id)
        if session is not None:
            client_ip = session.remote_address

        # Process through OwnTracks handler
        # Convert bytearray to bytes if needed
        payload = bytes(message.data) if isinstance(message.data, bytearray) else message.data
        await self._handler.handle_message(
            topic, payload, client_ip=client_ip, tls_tag=tls_tag,
        )
