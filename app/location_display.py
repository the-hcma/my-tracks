"""Format OwnTracks location fields for logs and UI display."""

from __future__ import annotations

from typing import Any

_CONNECTION_TYPE_LABELS: dict[str, str] = {
    "w": "WiFi",
    "m": "Mobile",
    "o": "Offline",
}


def _escape_log_value(value: str) -> str:
    """Escape device-supplied strings so they cannot break key=value log fragments."""
    return value.replace("\\", "\\\\").replace("\r", r"\r").replace("\n", r"\n").replace(",", r"\,")


def format_connection_type_display(
    connection_type: str | None,
    *,
    wifi_ssid: str | None = None,
) -> str:
    """Return a human-readable connection label, including WiFi SSID when known."""
    if not connection_type:
        return "N/A"
    label = _CONNECTION_TYPE_LABELS.get(connection_type, connection_type)
    if connection_type == "w" and wifi_ssid:
        return f"WiFi ({wifi_ssid})"
    return label


def location_network_vac_log_fragment(
    *,
    vertical_accuracy: int | None = None,
    fix_source: str = "",
    connection_type: str = "",
    wifi_ssid: str = "",
) -> str:
    """Comma-prefixed key=value fragments for vertical accuracy and network metadata."""
    parts: list[str] = []
    if vertical_accuracy is not None:
        parts.append(f"vac={vertical_accuracy}m")
    conn = format_connection_type_display(connection_type or None, wifi_ssid=wifi_ssid or None)
    if conn != "N/A":
        parts.append(f"conn={_escape_log_value(conn)}")
    if fix_source:
        parts.append(f"src={_escape_log_value(fix_source)}")
    if not parts:
        return ""
    return ", " + ", ".join(parts)


def location_network_vac_log_fragment_from_mapping(data: dict[str, Any]) -> str:
    """Build log fragment from serializer output or location dict."""
    vertical_accuracy = data.get("vertical_accuracy")
    return location_network_vac_log_fragment(
        vertical_accuracy=vertical_accuracy if vertical_accuracy is not None else None,
        fix_source=str(data.get("fix_source") or ""),
        connection_type=str(data.get("connection_type") or ""),
        wifi_ssid=str(data.get("wifi_ssid") or ""),
    )
