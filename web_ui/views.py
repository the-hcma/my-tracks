"""Views for the Web UI application."""

import logging
import socket

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from my_tracks.models import Location

logger = logging.getLogger(__name__)


class NetworkState:
    """Holds network-related state for change detection."""

    last_known_ip: str | None = None

    @classmethod
    def get_current_ip(cls) -> str:
        """Get the current local IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "Unable to detect"
        return local_ip

    @classmethod
    def check_and_update_ip(cls) -> tuple[str, bool]:
        """
        Check current IP and detect if it changed.

        Returns:
            Tuple of (current_ip, has_changed)
        """
        current_ip = cls.get_current_ip()
        has_changed = (
            cls.last_known_ip is not None and
            cls.last_known_ip != current_ip
        )

        if has_changed:
            logger.info(f"Network IP changed: {cls.last_known_ip} -> {current_ip}")

        cls.last_known_ip = current_ip
        return current_ip, has_changed


def health(request: HttpRequest) -> JsonResponse:
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


def network_info(request: HttpRequest) -> JsonResponse:
    """Return current network information for dynamic UI updates."""
    local_ip, _ = NetworkState.check_and_update_ip()
    hostname = socket.gethostname()

    return JsonResponse({
        'hostname': hostname,
        'local_ip': local_ip,
        'port': 8080
    })


def home(request: HttpRequest) -> HttpResponse:
    """Home page with live map and activity log."""
    # Get local IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "Unable to detect"

    hostname = socket.gethostname()

    # Get coordinate precision from database schema
    # The Location model defines decimal_places for lat/lon fields
    # We use this to derive a sensible collapsing precision (~1 meter = 5 decimals)
    lat_field = Location._meta.get_field('latitude')
    db_decimal_places = lat_field.decimal_places or 10  # Default to 10 if not set
    # For collapsing, use 5 decimals (~1.1m precision) - derived from DB but practical
    # This avoids over-aggregation while still grouping GPS jitter
    collapse_precision = min(db_decimal_places, 5)

    context = {
        'hostname': hostname,
        'local_ip': local_ip,
        'collapse_precision': collapse_precision,
    }

    response = render(request, 'web_ui/home.html', context)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response
