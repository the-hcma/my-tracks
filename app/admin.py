"""Django admin configuration for tracker app."""

from django.contrib import admin

from .models import (CertificateAuthority, ClientCertificate, Device, Location,
                     OwnTracksMessage, ServerCertificate, SmtpConfig,
                     Transition, TransitionAction, UserProfile, Waypoint)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    """Admin interface for Device model."""

    list_display: tuple[str, ...] = ('device_id', 'name', 'owner', 'is_online', 'last_seen', 'created_at')
    list_filter: tuple[str, ...] = ('is_online', 'created_at', 'last_seen')
    search_fields: tuple[str, ...] = ('device_id', 'name', 'mqtt_user')
    readonly_fields: tuple[str, ...] = ('created_at', 'last_seen')


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    """Admin interface for Location model."""

    list_display: tuple[str, ...] = (
        'device',
        'latitude',
        'longitude',
        'timestamp',
        'accuracy',
        'battery_level',
        'received_at'
    )
    list_filter: tuple[str, ...] = ('device', 'timestamp', 'connection_type')
    search_fields: tuple[str, ...] = ('device__device_id', 'device__name')
    readonly_fields: tuple[str, ...] = ('received_at',)
    date_hierarchy: str = 'timestamp'


@admin.register(OwnTracksMessage)
class OwnTracksMessageAdmin(admin.ModelAdmin):
    """Admin interface for OwnTracksMessage model."""

    list_display: tuple[str, ...] = (
        'message_type',
        'device',
        'ip_address',
        'received_at'
    )
    list_filter: tuple[str, ...] = ('message_type', 'received_at')
    search_fields: tuple[str, ...] = ('device__device_id', 'device__name', 'ip_address')
    readonly_fields: tuple[str, ...] = ('received_at', 'payload')
    date_hierarchy: str = 'received_at'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin interface for UserProfile model."""

    list_display: tuple[str, ...] = ('user', 'home_label', 'home_latitude', 'home_longitude', 'updated_at')
    search_fields: tuple[str, ...] = ('user__username', 'home_label')
    readonly_fields: tuple[str, ...] = ('created_at', 'updated_at')


@admin.register(CertificateAuthority)
class CertificateAuthorityAdmin(admin.ModelAdmin):
    """Admin interface for CertificateAuthority model."""

    list_display: tuple[str, ...] = ('common_name', 'is_active', 'not_valid_before', 'not_valid_after', 'created_at')
    list_filter: tuple[str, ...] = ('is_active',)
    search_fields: tuple[str, ...] = ('common_name', 'fingerprint')
    readonly_fields: tuple[str, ...] = ('fingerprint', 'created_at', 'not_valid_before', 'not_valid_after')


@admin.register(ServerCertificate)
class ServerCertificateAdmin(admin.ModelAdmin):
    """Admin interface for ServerCertificate model."""

    list_display: tuple[str, ...] = (
        'common_name', 'issuing_ca', 'is_active', 'not_valid_before', 'not_valid_after', 'created_at',
    )
    list_filter: tuple[str, ...] = ('is_active', 'issuing_ca')
    search_fields: tuple[str, ...] = ('common_name', 'fingerprint')
    readonly_fields: tuple[str, ...] = (
        'fingerprint', 'created_at', 'not_valid_before', 'not_valid_after', 'san_entries',
    )


@admin.register(ClientCertificate)
class ClientCertificateAdmin(admin.ModelAdmin):
    """Admin interface for ClientCertificate model."""

    list_display: tuple[str, ...] = (
        'common_name', 'user', 'issuing_ca', 'is_active', 'revoked', 'not_valid_after', 'created_at',
    )
    list_filter: tuple[str, ...] = ('is_active', 'revoked', 'issuing_ca')
    search_fields: tuple[str, ...] = ('common_name', 'fingerprint', 'user__username')
    readonly_fields: tuple[str, ...] = (
        'fingerprint', 'serial_number', 'created_at', 'not_valid_before', 'not_valid_after', 'revoked_at',
    )


@admin.register(Waypoint)
class WaypointAdmin(admin.ModelAdmin):
    """Admin interface for Waypoint model."""

    list_display: tuple[str, ...] = ('label', 'user', 'latitude', 'longitude', 'radius', 'is_active', 'updated_at')
    list_filter: tuple[str, ...] = ('is_active', 'user')
    search_fields: tuple[str, ...] = ('label', 'user__username', 'rid')
    readonly_fields: tuple[str, ...] = ('rid', 'created_at', 'updated_at')


@admin.register(SmtpConfig)
class SmtpConfigAdmin(admin.ModelAdmin):
    """Admin interface for SmtpConfig singleton model."""

    list_display: tuple[str, ...] = ('host', 'port', 'username', 'from_address', 'use_tls', 'use_ssl', 'updated_at')
    readonly_fields: tuple[str, ...] = ('updated_at',)
    exclude: tuple[str, ...] = ('encrypted_password',)


@admin.register(Transition)
class TransitionAdmin(admin.ModelAdmin):
    """Admin interface for Transition model."""

    list_display: tuple[str, ...] = ('device', 'event', 'description', 'waypoint', 'timestamp', 'received_at')
    list_filter: tuple[str, ...] = ('event', 'timestamp')
    search_fields: tuple[str, ...] = ('device__device_id', 'description', 'region_id')
    readonly_fields: tuple[str, ...] = ('received_at',)
    date_hierarchy: str = 'timestamp'


@admin.register(TransitionAction)
class TransitionActionAdmin(admin.ModelAdmin):
    """Admin interface for TransitionAction model."""

    list_display: tuple[str, ...] = (
        'user', 'waypoint', 'event', 'action_type', 'email_address', 'is_active', 'created_at',
    )
    list_filter: tuple[str, ...] = ('is_active', 'event', 'action_type', 'user')
    search_fields: tuple[str, ...] = ('user__username', 'waypoint__label', 'email_address')
    readonly_fields: tuple[str, ...] = ('created_at',)
