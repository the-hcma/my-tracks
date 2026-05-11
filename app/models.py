"""
Database models for OwnTracks location tracking.

This module defines the data models for storing device information
and location data from OwnTracks clients.
"""
import logging
import uuid
from decimal import Decimal
from typing import Any, cast

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


class Device(models.Model):
    """
    Represents a device (phone/tablet) running OwnTracks.

    Devices are uniquely identified by (owner, device_id) — two different users
    may have devices with the same device_id (e.g. both named "pixel7").
    """

    device_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Device identifier sent by OwnTracks (unique per owner)"
    )
    name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Friendly name for the device"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this device was first registered"
    )
    last_seen = models.DateTimeField(
        auto_now=True,
        help_text="Last time any MQTT activity was received from this device"
    )
    last_location_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a GPS location fix was received from this device"
    )
    is_online = models.BooleanField(
        default=False,  # type: ignore[reportArgumentType]  # django-stubs issue
        help_text="Whether the device is currently connected via MQTT"
    )
    mqtt_user = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="OwnTracks MQTT user (from topic owntracks/{user}/{device})"
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devices',
        help_text="Django user who owns this device (matched from mqtt_user)"
    )

    class Meta:
        ordering = ['-last_seen']
        verbose_name = 'Device'
        verbose_name_plural = 'Devices'
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'device_id'],
                name='unique_device_id_per_owner',
            )
        ]

    def __str__(self) -> str:
        """Return string representation of the device."""
        if self.name:
            return f"{self.name} ({self.device_id})"
        return str(self.device_id)


class Location(models.Model):
    """
    Represents a single location data point from OwnTracks.

    Stores comprehensive location information including coordinates,
    accuracy, altitude, velocity, battery level, and connection type.
    """

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='locations',
        help_text="The device that reported this location"
    )

    # Core location data (required fields)
    latitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        help_text="Latitude in decimal degrees (-90 to +90)"
    )
    longitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        help_text="Longitude in decimal degrees (-180 to +180)"
    )
    timestamp = models.DateTimeField(
        db_index=True,
        help_text="Unix timestamp when location was recorded (from 'tst' field)"
    )

    # Optional location metadata
    accuracy = models.IntegerField(
        null=True,
        blank=True,
        help_text="Accuracy of location in meters (from 'acc' field)"
    )
    altitude = models.IntegerField(
        null=True,
        blank=True,
        help_text="Altitude above sea level in meters (from 'alt' field)"
    )
    velocity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Velocity/speed in km/h (from 'vel' field)"
    )
    battery_level = models.IntegerField(
        null=True,
        blank=True,
        help_text="Battery percentage 0-100 (from 'batt' field)"
    )

    # Connection type: w=WiFi, o=Offline, m=Mobile
    CONNECTION_TYPE_CHOICES = [
        ('w', 'WiFi'),
        ('o', 'Offline'),
        ('m', 'Mobile'),
    ]
    connection_type = models.CharField(
        max_length=1,
        blank=True,
        choices=CONNECTION_TYPE_CHOICES,
        help_text="Connection type (from 'conn' field): w=WiFi, o=Offline, m=Mobile"
    )

    # Tracker ID (2-character display code from OwnTracks)
    tracker_id = models.CharField(
        max_length=10,
        blank=True,
        default='',
        help_text="OwnTracks tracker ID (from 'tid' field)"
    )

    # Client information
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the client that submitted this location"
    )

    RECEIVED_VIA_CHOICES = [
        ('http', 'HTTP'),
        ('mqtt', 'MQTT'),
    ]
    received_via = models.CharField(
        max_length=4,
        blank=True,
        default='',
        choices=RECEIVED_VIA_CHOICES,
        help_text="Transport used to receive this location: 'http' or 'mqtt'"
    )

    # Tracking metadata
    received_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the server received this location data"
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Location'
        verbose_name_plural = 'Locations'
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self) -> str:
        """Return string representation of the location."""
        return f"{self.device.device_id} @ ({self.latitude}, {self.longitude}) on {self.timestamp}"


class OwnTracksMessage(models.Model):
    """
    Stores all OwnTracks message types (status, lwt, transition, etc.).

    This model captures non-location messages from OwnTracks clients,
    storing the complete message payload for debugging and analysis.
    """

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='messages',
        null=True,
        blank=True,
        help_text="The device that sent this message (if identifiable)"
    )

    message_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Type of OwnTracks message (status, lwt, transition, etc.)"
    )

    payload = models.JSONField(
        help_text="Complete message payload as JSON"
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the client that submitted this message"
    )

    received_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the server received this message"
    )

    class Meta:
        ordering = ['-received_at']
        verbose_name = 'OwnTracks Message'
        verbose_name_plural = 'OwnTracks Messages'
        indexes = [
            models.Index(fields=['device', '-received_at']),
            models.Index(fields=['message_type', '-received_at']),
        ]

    def __str__(self) -> str:
        """Return string representation of the message."""
        device_str = self.device.device_id if self.device else 'Unknown'
        return f"{device_str} - {self.message_type} at {self.received_at}"


class CertificateAuthority(models.Model):
    """
    Self-signed Certificate Authority for issuing server and client certificates.

    Only one CA may be active at a time (enforced by the is_active singleton pattern).
    Private keys are stored encrypted at rest using Fernet derived from SECRET_KEY.
    """

    certificate_pem = models.TextField(
        help_text="CA certificate in PEM format"
    )
    encrypted_private_key = models.BinaryField(
        help_text="CA private key encrypted at rest (Fernet)"
    )
    common_name = models.CharField(
        max_length=200,
        help_text="Subject Common Name of the CA certificate"
    )
    fingerprint = models.CharField(
        max_length=100,
        help_text="SHA-256 fingerprint of the CA certificate"
    )
    not_valid_before = models.DateTimeField(
        help_text="Certificate validity start"
    )
    not_valid_after = models.DateTimeField(
        help_text="Certificate validity end"
    )
    key_size = models.IntegerField(
        default=4096,  # type: ignore[reportArgumentType]  # django-stubs issue
        help_text="RSA key size in bits (2048, 3072, or 4096)"
    )
    is_active = models.BooleanField(
        default=True,  # type: ignore[reportArgumentType]  # django-stubs issue
        help_text="Whether this is the current active CA (only one may be active)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this CA was generated"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Certificate Authority'
        verbose_name_plural = 'Certificate Authorities'

    def __str__(self) -> str:
        """Return string representation of the CA."""
        active = " (active)" if self.is_active else ""
        return f"{self.common_name}{active}"


class ServerCertificate(models.Model):
    """
    Server certificate for MQTT TLS, signed by an active CA.

    Only one server certificate may be active at a time
    (enforced by the is_active singleton pattern with history).
    Private keys are stored encrypted at rest using Fernet derived from SECRET_KEY.
    """

    issuing_ca = models.ForeignKey(
        CertificateAuthority,
        on_delete=models.CASCADE,
        related_name='server_certificates',
        help_text="The CA that signed this server certificate"
    )
    certificate_pem = models.TextField(
        help_text="Server certificate in PEM format"
    )
    encrypted_private_key = models.BinaryField(
        help_text="Server private key encrypted at rest (Fernet)"
    )
    common_name = models.CharField(
        max_length=200,
        help_text="Subject Common Name of the server certificate"
    )
    fingerprint = models.CharField(
        max_length=100,
        help_text="SHA-256 fingerprint of the server certificate"
    )
    san_entries = models.JSONField(
        default=list,
        help_text="Subject Alternative Names (IP addresses and DNS names)"
    )
    key_size = models.IntegerField(
        default=4096,  # type: ignore[reportArgumentType]  # django-stubs issue
        help_text="RSA key size in bits (2048, 3072, or 4096)"
    )
    not_valid_before = models.DateTimeField(
        help_text="Certificate validity start"
    )
    not_valid_after = models.DateTimeField(
        help_text="Certificate validity end"
    )
    is_active = models.BooleanField(
        default=True,  # type: ignore[reportArgumentType]  # django-stubs issue
        help_text="Whether this is the current active server certificate"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this server certificate was generated"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Server Certificate'
        verbose_name_plural = 'Server Certificates'

    def __str__(self) -> str:
        """Return string representation of the server certificate."""
        active = " (active)" if self.is_active else ""
        return f"{self.common_name}{active}"


class ClientCertificate(models.Model):
    """
    Client certificate issued to a user, signed by the active CA.

    Used for MQTT TLS client authentication. The CN embeds the username
    so the broker can map certificates to users for topic ACL.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='client_certificates',
        help_text="The user this certificate was issued to"
    )
    issuing_ca = models.ForeignKey(
        CertificateAuthority,
        on_delete=models.CASCADE,
        related_name='client_certificates',
        help_text="The CA that signed this client certificate"
    )
    certificate_pem = models.TextField(
        help_text="Client certificate in PEM format"
    )
    encrypted_private_key = models.BinaryField(
        help_text="Client private key encrypted at rest (Fernet)"
    )
    common_name = models.CharField(
        max_length=200,
        help_text="Subject Common Name (matches the username)"
    )
    fingerprint = models.CharField(
        max_length=100,
        help_text="SHA-256 fingerprint of the client certificate"
    )
    serial_number = models.CharField(
        max_length=100,
        help_text="Certificate serial number (hex)"
    )
    key_size = models.IntegerField(
        default=4096,  # type: ignore[reportArgumentType]
        help_text="RSA key size in bits (2048, 3072, or 4096)"
    )
    not_valid_before = models.DateTimeField(
        help_text="Certificate validity start"
    )
    not_valid_after = models.DateTimeField(
        help_text="Certificate validity end"
    )
    is_active = models.BooleanField(
        default=True,  # type: ignore[reportArgumentType]
        help_text="Whether this certificate is currently active"
    )
    revoked = models.BooleanField(
        default=False,  # type: ignore[reportArgumentType]
        help_text="Whether this certificate has been revoked"
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this certificate was revoked"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this certificate was issued"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Client Certificate'
        verbose_name_plural = 'Client Certificates'

    def __str__(self) -> str:
        """Return string representation of the client certificate."""
        status_label = ""
        if self.revoked:
            status_label = " (revoked)"
        elif self.is_active:
            status_label = " (active)"
        return f"{self.common_name}{status_label}"


class UserProfile(models.Model):
    """
    Extended profile for users.

    Stores per-user settings beyond what the built-in User model provides.
    Automatically created when a new User is created via the post_save signal.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        help_text="The user this profile belongs to"
    )
    home_latitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Home location latitude — default map center for geofence creation"
    )
    home_longitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Home location longitude — default map center for geofence creation"
    )
    home_label = models.CharField(
        max_length=100,
        default='Home',
        help_text="Display label for the home location pin"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this profile was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this profile was last updated"
    )

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self) -> str:
        """Return string representation of the profile."""
        return f"Profile for {self.user.username}"


class Waypoint(models.Model):
    """
    Server-side record of a geofence region for a user.

    Each waypoint is a circular region identified by a stable UUID (rid) that
    matches the OwnTracks region ID. The server can push waypoints to devices
    via CommandPublisher.set_waypoints().
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='waypoints',
        help_text="User who owns this geofence"
    )
    label = models.CharField(
        max_length=200,
        help_text="Display name for this geofence (maps to OwnTracks 'desc')"
    )
    latitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        help_text="Center latitude of the geofence circle"
    )
    longitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        help_text="Center longitude of the geofence circle"
    )
    radius = models.IntegerField(
        default=100,  # type: ignore[reportArgumentType]
        help_text="Radius of the geofence circle in metres"
    )
    rid = models.CharField(
        max_length=36,
        unique=True,
        help_text="Content-derived UUID5 (owner + desc + lat + lon + rad); same content always yields the same rid"
    )
    is_active = models.BooleanField(
        default=True,  # type: ignore[reportArgumentType]
        help_text="Whether this waypoint is active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['label']
        verbose_name = 'Waypoint'
        verbose_name_plural = 'Waypoints'
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.rid:
            self.rid = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.label} ({self.user.username})"

    def as_device_sync_row(self) -> dict[str, Any]:
        """
        Build one OwnTracks waypoint row for setWaypoints device sync.

        Matches the payload shape produced by the geofences 'sync to device'
        flow (desc, lat, lon, rad, tst).
        """
        # Decimal at runtime; pyright needs cast for float(lat/lon).
        return {
            'desc': self.label,
            'lat': float(cast(Decimal, self.latitude)),
            'lon': float(cast(Decimal, self.longitude)),
            'rad': self.radius,
            'tst': int(self.updated_at.timestamp()),
        }


class Transition(models.Model):
    """
    Persisted enter/leave event fired when a device crosses a geofence boundary.

    Matches the OwnTracks '_type: transition' message. The waypoint FK is
    populated by matching rid to an existing Waypoint; stays null if no
    server-side waypoint exists for that rid.
    """

    ENTER = 'enter'
    LEAVE = 'leave'
    EVENT_CHOICES = [
        (ENTER, 'Enter'),
        (LEAVE, 'Leave'),
    ]

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='transitions',
        help_text="Device that fired this transition"
    )
    waypoint = models.ForeignKey(
        Waypoint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transitions',
        help_text="Matched server-side waypoint (null if rid has no server record)"
    )
    event = models.CharField(
        max_length=10,
        choices=EVENT_CHOICES,
        help_text="'enter' or 'leave'"
    )
    region_id = models.CharField(
        max_length=36,
        help_text="OwnTracks rid from the transition message"
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        help_text="OwnTracks desc from the transition message"
    )
    timestamp = models.DateTimeField(
        help_text="When the transition occurred on the device (tst)"
    )
    latitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Device latitude at transition time"
    )
    longitude = models.DecimalField(
        max_digits=15,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Device longitude at transition time"
    )
    accuracy = models.IntegerField(
        null=True,
        blank=True,
        help_text="Location accuracy in metres at transition time"
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Transition'
        verbose_name_plural = 'Transitions'
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['waypoint', '-timestamp']),
        ]

    def __str__(self) -> str:
        return f"{self.device.device_id} {self.event} {self.description} @ {self.timestamp}"


class SmtpConfig(models.Model):
    """
    Singleton SMTP configuration for outgoing email notifications.

    Only one row ever exists (pk=1, enforced by save()). Use SmtpConfig.get()
    to retrieve it; returns None when SMTP has not been configured yet.
    """

    host = models.CharField(max_length=255, help_text="SMTP server hostname")
    port = models.PositiveIntegerField(
        default=587,  # type: ignore[reportArgumentType]
        help_text="SMTP port (587 for STARTTLS, 465 for SSL)",
    )
    username = models.CharField(max_length=255, blank=True)
    encrypted_password = models.BinaryField(
        blank=True,
        default=b"",
        help_text="SMTP password encrypted at rest (Fernet/SECRET_KEY)",
    )
    use_tls = models.BooleanField(default=True, help_text="Use STARTTLS")  # type: ignore[reportArgumentType]
    use_ssl = models.BooleanField(
        default=False,  # type: ignore[reportArgumentType]
        help_text="Use implicit SSL (port 465)",
    )
    from_address = models.EmailField(help_text="From address for outgoing emails")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SMTP configuration"

    def __str__(self) -> str:
        return f"SMTP {self.host}:{self.port}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Enforce singleton by always writing to pk=1."""
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "SmtpConfig | None":
        """Return the singleton config, or None if SMTP has not been configured."""
        return cls.objects.filter(pk=1).first()


class LocationQualitySettings(models.Model):
    """
    Singleton: optional GPS accuracy gate for path rendering and geofence logic.

    When ``filter_accuracy_enabled`` is true, any Location with a known
    ``accuracy`` value strictly greater than ``minimum_accuracy_meters`` is ignored
    when choosing the latest fix for server-side geofence state (and the web UI
    excludes those points from live/historic polylines). Rows with null
    accuracy are always treated as passing the gate.
    """

    filter_accuracy_enabled = models.BooleanField(
        default=False,  # type: ignore[reportArgumentType]
        help_text="When enabled, ignore fixes whose reported accuracy exceeds minimum_accuracy_meters.",
    )
    minimum_accuracy_meters = models.PositiveIntegerField(
        default=100,  # type: ignore[reportArgumentType]
        help_text=(
            "Minimum accuracy (meters): use a fix only if accuracy is unknown or "
            "≤ this value (discard when reported accuracy is greater than this)."
        ),
    )

    class Meta:
        verbose_name = "Location quality settings"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Enforce singleton by always writing to pk=1."""
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "LocationQualitySettings":
        """Return the singleton row, creating defaults if missing."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TransitionAction(models.Model):
    """
    Rule that triggers an email when a geofence transition fires.

    Belongs to a user and optionally a specific Waypoint (null = any geofence).
    The event field controls which direction triggers the rule.
    """

    ENTER = 'enter'
    LEAVE = 'leave'
    ANY = 'any'
    EVENT_CHOICES = [
        (ENTER, 'Enter'),
        (LEAVE, 'Leave'),
        (ANY, 'Either'),
    ]

    ACTION_EMAIL = 'email'
    ACTION_CHOICES = [
        (ACTION_EMAIL, 'Email'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='transition_actions',
    )
    waypoint = models.ForeignKey(
        Waypoint,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='actions',
        help_text="Target waypoint; null means 'any geofence'",
    )
    event = models.CharField(
        max_length=10,
        choices=EVENT_CHOICES,
        default=ANY,
        help_text="'enter', 'leave', or 'any'",
    )
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        default=ACTION_EMAIL,
    )
    email_address = models.EmailField(
        help_text="Recipient email address for the notification",
    )
    is_active = models.BooleanField(
        default=True,  # type: ignore[reportArgumentType]
        help_text="Whether this rule is currently active",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['waypoint__label', 'event']
        verbose_name = 'Transition Action'
        verbose_name_plural = 'Transition Actions'
        indexes = [
            models.Index(fields=['user', 'is_active'], name='ta_user_active_idx'),
        ]

    def __str__(self) -> str:
        wp_label = self.waypoint.label if self.waypoint else 'Any'
        return f"{self.user.username}: {wp_label} {self.event} → {self.email_address}"


class GlobalAutomationRule(models.Model):
    """
    Admin-defined rule that fires when a set of users all meet a geofence condition.

    Condition is evaluated server-side using the latest Location for each watched
    user (haversine distance to waypoint centre). Fires once when the condition
    transitions from not-met to met; resets automatically when it is no longer met.
    Only admins (is_staff) may create these rules.
    """

    CONDITION_ALL_INSIDE = 'all_inside'
    CONDITION_ALL_OUTSIDE = 'all_outside'
    CONDITION_CHOICES = [
        (CONDITION_ALL_INSIDE, 'All users inside'),
        (CONDITION_ALL_OUTSIDE, 'All users outside'),
    ]

    ACTION_EMAIL = 'email'
    ACTION_WEBHOOK = 'webhook'
    ACTION_CHOICES = [
        (ACTION_EMAIL, 'Email'),
        (ACTION_WEBHOOK, 'Webhook'),
    ]

    name = models.CharField(
        max_length=200,
        help_text="Human-readable label for this rule",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='global_automation_rules_created',
        help_text="Admin who created this rule",
    )
    waypoint = models.ForeignKey(
        Waypoint,
        on_delete=models.CASCADE,
        related_name='global_automation_rules',
        help_text="Geofence this rule watches",
    )
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default=CONDITION_ALL_INSIDE,
        help_text="'all_inside' or 'all_outside'",
    )
    users = models.ManyToManyField(
        User,
        related_name='global_automation_rules',
        help_text="Users whose location is evaluated",
    )
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        default=ACTION_EMAIL,
    )
    email_address = models.EmailField(
        blank=True,
        help_text="Recipient email address (for email action)",
    )
    webhook_url = models.URLField(
        blank=True,
        help_text="HTTP endpoint to POST to (for webhook action)",
    )
    is_active = models.BooleanField(
        default=True,  # type: ignore[reportArgumentType]
        help_text="Whether this rule is currently active",
    )
    last_condition_met = models.BooleanField(
        null=True,
        default=None,  # type: ignore[reportArgumentType]
        help_text=(
            "Tracks fire-once state: None=never evaluated, "
            "True=condition met (fired), False=condition not met (reset)"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Global Automation Rule'
        verbose_name_plural = 'Global Automation Rules'
        indexes = [
            models.Index(fields=['is_active'], name='gar_active_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.condition})"


@receiver(post_save, sender=User)
def create_user_profile(
    sender: type[User], instance: User, created: bool, **kwargs: Any
) -> None:
    """Auto-create a UserProfile whenever a new User is created."""
    if created:
        role = "admin" if instance.is_staff else "user"
        logger.info("New user created: '%s' (role=%s, email='%s')",
                    instance.username, role, instance.email or "")
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=ServerCertificate)
def reload_tls_on_server_cert(
    sender: type[ServerCertificate],
    instance: ServerCertificate,
    **kwargs: Any,
) -> None:
    """Hot-reload MQTT TLS when a new server certificate is activated."""
    if not instance.is_active:
        return
    from app.apps import trigger_tls_reload
    trigger_tls_reload(
        reason=f"new server certificate activated (CN={instance.common_name}, fingerprint={instance.fingerprint})"
    )


@receiver(post_save, sender=ClientCertificate)
def reload_tls_on_client_cert_revoked(
    sender: type[ClientCertificate],
    instance: ClientCertificate,
    **kwargs: Any,
) -> None:
    """Hot-reload MQTT TLS when a client certificate is revoked (CRL update)."""
    if not instance.revoked:
        return
    from app.apps import trigger_tls_reload
    trigger_tls_reload(
        reason=f"client certificate revoked (CN={instance.common_name}, serial={instance.serial_number})"
    )
