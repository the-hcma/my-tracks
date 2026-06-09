"""Tests for admin sync export endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from hamcrest import assert_that, equal_to, has_length
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Device, Waypoint


@pytest.fixture
def admin_user(db: Any) -> User:
    return User.objects.create_user(username="admin", password="secret", is_staff=True)


@pytest.fixture
def regular_user(db: Any) -> User:
    return User.objects.create_user(username="henrique", password="secret", first_name="Henrique")


@pytest.fixture
def admin_client(admin_user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def user_client(regular_user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


def test_users_with_devices_export_requires_admin(user_client: APIClient) -> None:
    response = user_client.get("/api/admin/users-with-devices/")
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_users_with_devices_export_lists_owner_devices(
    admin_client: APIClient,
    regular_user: User,
) -> None:
    Device.objects.create(
        owner=regular_user,
        device_id="iphone",
        name="Henrique's iPhone",
        mqtt_user=regular_user.username,
    )
    response = admin_client.get("/api/admin/users-with-devices/")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["source"], equal_to("my-tracks"))
    assert_that(body["users_with_devices"], has_length(1))
    assert_that(body["users_with_devices"][0]["username"], equal_to("henrique"))
    assert_that(body["users_with_devices"][0]["device_name"], equal_to("Henrique's iPhone"))


def test_waypoints_export_lists_active_waypoints(
    admin_client: APIClient,
    regular_user: User,
) -> None:
    Waypoint.objects.create(
        user=regular_user,
        label="House",
        latitude="41.194072",
        longitude="-73.8883254",
        radius=250,
        rid="rid-house",
        is_active=True,
    )
    response = admin_client.get("/api/admin/waypoints/")
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    body = response.json()
    assert_that(body["waypoints"], has_length(1))
    assert_that(body["waypoints"][0]["geofence_id"], equal_to("henrique-house"))
    assert_that(body["waypoints"][0]["radius_m"], equal_to(250))
