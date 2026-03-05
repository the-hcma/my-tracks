"""
Database models for OwnTracks location tracking.

This module defines the data models for storing device information
and location data from OwnTracks clients.
"""
import logging
from typing import Any

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


class Device(models.Model):
    """
    Represents a device (phone/tablet) running OwnTracks.

    Each device is uniquely identified by its device_id, which is sent
    by the OwnTracks client in location updates.
    """

    device_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique identifier for the device (from OwnTracks 'tid' field)"
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
        help_text="Last time location data was received from this device"
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

    class Meta:
        ordering = ['-last_seen']
        verbose_name = 'Device'
        verbose_name_plural = 'Devices'

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
