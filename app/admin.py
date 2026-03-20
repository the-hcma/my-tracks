"""Django admin configuration for tracker app."""

from django.contrib import admin

from .models import Device, Location, OwnTracksMessage, Transition, Waypoint


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


@admin.register(Waypoint)
class WaypointAdmin(admin.ModelAdmin):
    """Admin interface for Waypoint model."""

    list_display: tuple[str, ...] = ('label', 'user', 'latitude', 'longitude', 'radius', 'is_active', 'updated_at')
    list_filter: tuple[str, ...] = ('is_active', 'user')
    search_fields: tuple[str, ...] = ('label', 'user__username', 'rid')
    readonly_fields: tuple[str, ...] = ('rid', 'created_at', 'updated_at')


@admin.register(Transition)
class TransitionAdmin(admin.ModelAdmin):
    """Admin interface for Transition model."""

    list_display: tuple[str, ...] = ('device', 'event', 'description', 'waypoint', 'timestamp', 'received_at')
    list_filter: tuple[str, ...] = ('event', 'timestamp')
    search_fields: tuple[str, ...] = ('device__device_id', 'description', 'region_id')
    readonly_fields: tuple[str, ...] = ('received_at',)
    date_hierarchy: str = 'timestamp'
