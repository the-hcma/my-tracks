"""
Utility functions for OwnTracks data processing.

This module provides shared helpers used across views, serializers,
and MQTT handlers for common operations like device identification.
"""
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _get_pkg_version

logger = logging.getLogger(__name__)


def get_version() -> str:
    """Return the application version from package metadata.

    The version is read from pyproject.toml via importlib.metadata,
    making pyproject.toml the single source of truth.
    """
    try:
        return _get_pkg_version("my-tracks")
    except PackageNotFoundError:
        return "unknown"


def extract_device_id(data: dict[str, object]) -> str | None:
    """
    Extract device ID from OwnTracks message data.

    Prioritizes topic-based identification over tid (tracker ID).
    Topic format: owntracks/user/deviceid

    Args:
        data: OwnTracks message payload as a dictionary

    Returns:
        Device ID string, or None if no identifier found
    """
    # Check explicit device_id first
    device_id = data.get('device_id')
    if device_id:
        return str(device_id)

    # Extract from topic (format: owntracks/user/deviceid)
    # Use only the device name (ignore user component)
    topic = data.get('topic')
    if topic:
        parts = str(topic).split('/')
        if len(parts) >= 3:
            return parts[2]

    # Fallback to tid
    tid = data.get('tid')
    if tid:
        return str(tid)

    return None
