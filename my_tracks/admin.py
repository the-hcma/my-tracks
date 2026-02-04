"""Django admin configuration for tracker app."""

from django.contrib import admin

from .models import Device, Location, OwnTracksMessage


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    """Admin interface for Device model."""

    list_display: tuple[str, ...] = ('device_id', 'name', 'last_seen', 'created_at')
    list_filter: tuple[str, ...] = ('created_at', 'last_seen')
    search_fields: tuple[str, ...] = ('device_id', 'name')
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
