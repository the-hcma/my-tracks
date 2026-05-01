"""
Client IP extraction helpers.

We store an IP address on incoming OwnTracks HTTP/MQTT messages for diagnostics.
When running behind a reverse proxy, REMOTE_ADDR is typically the proxy's IP;
the real client address is conveyed via X-Forwarded-For / X-Real-IP.
"""

from __future__ import annotations

from typing import Any, Mapping


def _first_csv_item(value: str) -> str:
    return value.split(",", 1)[0].strip()


def get_http_client_ip(meta: dict[str, Any]) -> str | None:
    """
    Best-effort extract the real client IP from a Django request.META.

    Order:
    - X-Forwarded-For (first hop)
    - X-Real-IP
    - REMOTE_ADDR
    """
    xff = meta.get("HTTP_X_FORWARDED_FOR")
    if xff:
        ip = _first_csv_item(str(xff))
        if ip:
            return ip

    x_real = meta.get("HTTP_X_REAL_IP")
    if x_real:
        ip = str(x_real).strip()
        if ip:
            return ip

    remote = meta.get("REMOTE_ADDR")
    if remote:
        ip = str(remote).strip()
        if ip:
            return ip

    return None


def get_ws_client_ip(scope: Mapping[str, Any]) -> str | None:
    """
    Best-effort extract the real client IP from a Channels WebSocket scope.
    """
    headers = dict(scope.get("headers", []))
    xff = headers.get(b"x-forwarded-for")
    if xff:
        ip = _first_csv_item(xff.decode(errors="ignore"))
        if ip:
            return ip

    x_real = headers.get(b"x-real-ip")
    if x_real:
        ip = x_real.decode(errors="ignore").strip()
        if ip:
            return ip

    client = scope.get("client")
    if client:
        return client[0]

    return None
