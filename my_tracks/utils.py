"""
Utility functions for OwnTracks data processing.

This module provides shared helpers used across views, serializers,
and MQTT handlers for common operations like device identification.
"""
import logging

logger = logging.getLogger(__name__)


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
    # Use user/device to match the MQTT handler's device ID format
    topic = data.get('topic')
    if topic:
        parts = str(topic).split('/')
        if len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"

    # Fallback to tid
    tid = data.get('tid')
    if tid:
        return str(tid)

    return None
