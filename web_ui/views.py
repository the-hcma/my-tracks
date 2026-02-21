"""Views for the Web UI application."""

import logging
import socket

import netifaces
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from config.runtime import get_actual_mqtt_port, get_mqtt_port
from my_tracks.models import Location

logger = logging.getLogger(__name__)


def get_all_local_ips() -> list[str]:
    """
    Get all non-loopback IPv4 addresses from broadcast-capable interfaces.

    Only includes addresses that have a broadcast address, which filters out
    VPN/tunnel interfaces (utun, tun, wg, ipsec) that use point-to-point links.

    Returns:
        Sorted list of IPv4 address strings (e.g., ['10.0.1.5', '192.168.1.10'])
    """
    ips: list[str] = []
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface)
        for addr_info in addrs.get(netifaces.AF_INET, []):
            ip = addr_info.get('addr', '')
            has_broadcast = bool(addr_info.get('broadcast'))
            if ip and not ip.startswith('127.') and has_broadcast:
                ips.append(ip)
    return sorted(set(ips))


def update_allowed_hosts(ips: list[str]) -> None:
    """
    Dynamically add discovered local IPs to Django's ALLOWED_HOSTS.

    Only adds IPs that aren't already in the list. This ensures the server
    accepts requests on all its network interfaces without manual configuration.

    Args:
        ips: List of local IP addresses to allow
    """
    for ip in ips:
        if ip not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append(ip)
            logger.info("Added %s to ALLOWED_HOSTS", ip)


class NetworkState:
    """Holds network-related state for change detection."""

    last_known_ips: list[str] | None = None

    @classmethod
    def get_current_ips(cls) -> list[str]:
        """Get all current non-loopback IPv4 addresses."""
        return get_all_local_ips()

    @classmethod
    def get_current_ip(cls) -> str:
        """Get the primary local IP address (first detected)."""
        ips = cls.get_current_ips()
        return ips[0] if ips else "Unable to detect"

    @classmethod
    def check_and_update_ips(cls) -> tuple[list[str], bool]:
        """
        Check current IPs and detect if they changed.

        Also dynamically updates ALLOWED_HOSTS with any new IPs.

        Returns:
            Tuple of (current_ips, has_changed)
        """
        current_ips = cls.get_current_ips()
        has_changed = (
            cls.last_known_ips is not None and
            set(cls.last_known_ips) != set(current_ips)
        )

        if has_changed:
            logger.info("Network IPs changed: %s -> %s", cls.last_known_ips, current_ips)

        cls.last_known_ips = current_ips
        update_allowed_hosts(current_ips)
        return current_ips, has_changed

    @classmethod
    def check_and_update_ip(cls) -> tuple[str, bool]:
        """
        Check current IP and detect if it changed.

        Legacy wrapper that returns the primary IP.

        Returns:
            Tuple of (primary_ip, has_changed)
        """
        ips, changed = cls.check_and_update_ips()
        primary_ip = ips[0] if ips else "Unable to detect"
        return primary_ip, changed


def health(request: HttpRequest) -> JsonResponse:
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


def network_info(request: HttpRequest) -> JsonResponse:
    """Return current network information for dynamic UI updates."""
    ips, _ = NetworkState.check_and_update_ips()
    hostname = socket.gethostname()
    server_port = request.META.get('SERVER_PORT', '8080')

    return JsonResponse({
        'hostname': hostname,
        'local_ip': ips[0] if ips else 'Unable to detect',
        'local_ips': ips,
        'port': int(server_port)
    })


def home(request: HttpRequest) -> HttpResponse:
    """Home page with live map and activity log."""
    ips, _ = NetworkState.check_and_update_ips()
    primary_ip = ips[0] if ips else 'Unable to detect'
    hostname = socket.gethostname()

    # Get the actual port from the request (handles port 0 case correctly)
    server_port = request.META.get('SERVER_PORT', '8080')

    # Get coordinate precision from database schema
    # The Location model defines decimal_places for lat/lon fields
    # We use this to derive a sensible collapsing precision (~1 meter = 5 decimals)
    lat_field = Location._meta.get_field('latitude')
    db_decimal_places = lat_field.decimal_places or 10  # Default to 10 if not set
    # For collapsing, use 5 decimals (~1.1m precision) - derived from DB but practical
    # This avoids over-aggregation while still grouping GPS jitter
    collapse_precision = min(db_decimal_places, 5)

    # Get MQTT port (actual port if OS-allocated, else configured port)
    mqtt_configured_port = get_mqtt_port()
    mqtt_actual_port = get_actual_mqtt_port()
    mqtt_port = mqtt_actual_port if mqtt_actual_port is not None else mqtt_configured_port
    mqtt_enabled = mqtt_configured_port >= 0

    context = {
        'hostname': hostname,
        'local_ip': primary_ip,
        'local_ips': ips,
        'server_port': server_port,
        'collapse_precision': collapse_precision,
        'mqtt_port': mqtt_port,
        'mqtt_enabled': mqtt_enabled,
    }

    response = render(request, 'web_ui/home.html', context)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response
