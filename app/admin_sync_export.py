"""Read-only admin export payloads for external automation consumers."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, cast

from django.contrib.auth.models import User
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import Device, Waypoint

_SOURCE = "my-tracks"


def slugify_waypoint_id(raw: str) -> str:
    """Build a stable waypoint id from username + label."""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower())
    slug = slug.strip("-")
    return slug[:64] if slug else "waypoint"


class AdminUsersWithDevicesExportView(APIView):
    """``GET /api/admin/users-with-devices/`` — active users with a primary device."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        del request
        rows: list[dict[str, Any]] = []
        for user in User.objects.filter(is_active=True).order_by("username"):
            device = (
                Device.objects.filter(owner=user)
                .order_by("-last_location_at", "-last_seen")
                .first()
            )
            if device is None:
                continue
            display_name = user.get_full_name().strip() or user.username
            device_name = device.name.strip() if device.name.strip() else device.device_id
            rows.append(
                {
                    "username": user.username,
                    "display_name": display_name,
                    "device_name": device_name,
                    "enabled": True,
                }
            )
        return Response({"source": _SOURCE, "users_with_devices": rows})


class AdminWaypointsExportView(APIView):
    """``GET /api/admin/waypoints/`` — active waypoints for admin export."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        del request
        rows: list[dict[str, Any]] = []
        for waypoint in Waypoint.objects.filter(is_active=True).select_related("user").order_by(
            "user__username",
            "label",
        ):
            geofence_id = slugify_waypoint_id(f"{waypoint.user.username}-{waypoint.label}")
            rows.append(
                {
                    "geofence_id": geofence_id,
                    "label": waypoint.label,
                    "center_lat": float(cast(Decimal, waypoint.latitude)),
                    "center_lon": float(cast(Decimal, waypoint.longitude)),
                    "radius_m": waypoint.radius,
                    "enabled": True,
                    "owntracks_rid": waypoint.rid,
                }
            )
        return Response({"source": _SOURCE, "waypoints": rows})
