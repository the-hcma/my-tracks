"""
Database models for OwnTracks location tracking.

This module defines the data models for storing device information
and location data from OwnTracks clients.
"""
from django.db import models
from django.utils import timezone


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
