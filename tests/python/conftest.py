"""Shared test fixtures for the my-tracks project."""

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import Client
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _inline_domesti_location_request_queue() -> Iterator[None]:
    """Process domesti-bot location requests synchronously in tests."""
    from app.domesti_location_request_queue import set_inline_processing

    set_inline_processing(True)
    yield
    set_inline_processing(False)


@pytest.fixture
def user(db: Any) -> User:
    """Create a regular test user."""
    return User.objects.create_user(
        username='testuser', password='testpass123', email='test@example.com'
    )


@pytest.fixture
def admin_user(db: Any) -> User:
    """Create an admin/staff test user."""
    return User.objects.create_superuser(
        username='admin', password='adminpass123', email='admin@example.com'
    )


@pytest.fixture
def auth_api_client(user: User) -> APIClient:
    """Provide an authenticated DRF API client."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def admin_api_client(admin_user: User) -> APIClient:
    """Provide an admin-authenticated DRF API client."""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def logged_in_client(user: User) -> Client:
    """Provide a test client logged in as a regular user."""
    client = Client()
    client.login(username='testuser', password='testpass123')
    return client


@pytest.fixture
def admin_logged_in_client(admin_user: User) -> Client:
    """Provide a test client logged in as an admin."""
    client = Client()
    client.login(username='admin', password='adminpass123')
    return client
