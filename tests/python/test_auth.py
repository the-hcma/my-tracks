"""Tests for user authentication, account management, and admin user endpoints."""

from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from hamcrest import (assert_that, contains_string, equal_to, greater_than,
                      has_entries, has_key, has_length, instance_of, is_,
                      is_not, not_none)
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient, APIRequestFactory

from my_tracks.auth import CommandApiKeyAuthentication, get_command_api_key
from my_tracks.models import UserProfile


@pytest.mark.django_db
class TestLoginPage:
    """Test the login page and login/logout flow."""

    def test_login_page_renders(self) -> None:
        """Test that the login page renders for unauthenticated users."""
        client = Client()
        response = client.get('/login/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Sign in'))
        assert_that(content, contains_string('My Tracks'))

    def test_login_success_redirects_to_home(self, user: User) -> None:
        """Test that successful login redirects to home page."""
        client = Client()
        response = client.post('/login/', {
            'username': 'testuser',
            'password': 'testpass123',
        })
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, equal_to('/'))

    def test_login_invalid_credentials(self, user: User) -> None:
        """Test that invalid credentials show error."""
        client = Client()
        response = client.post('/login/', {
            'username': 'testuser',
            'password': 'wrongpassword',
        })
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        content = response.content.decode('utf-8')
        assert_that(content, contains_string('Invalid username or password'))

    def test_logout_redirects_to_login(self, logged_in_client: Client) -> None:
        """Test that logout redirects to login page."""
        response = logged_in_client.post('/logout/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, equal_to('/login/'))

    def test_authenticated_user_can_access_home(self, logged_in_client: Client) -> None:
        """Test that authenticated user can access the home page."""
        response = logged_in_client.get('/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    def test_unauthenticated_home_redirects_to_login(self) -> None:
        """Test that unauthenticated access to home redirects to login."""
        client = Client()
        response = client.get('/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, contains_string('/login/'))

    def test_unauthenticated_network_info_redirects(self) -> None:
        """Test that unauthenticated access to network-info redirects."""
        client = Client()
        response = client.get('/network-info/')
        assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
        assert_that(response.url, contains_string('/login/'))

    def test_health_endpoint_no_auth_required(self) -> None:
        """Test that health endpoint works without authentication."""
        client = Client()
        response = client.get('/health/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


@pytest.mark.django_db
class TestUserProfileModel:
    """Test UserProfile auto-creation and model behavior."""

    def test_profile_auto_created_on_user_creation(self) -> None:
        """Test that UserProfile is automatically created for new users."""
        user = User.objects.create_user(username='newuser', password='pass123')
        assert_that(hasattr(user, 'profile'), is_(True))
        assert_that(user.profile, is_not(equal_to(None)))
        assert_that(user.profile, is_(not_none()))

    def test_profile_str_representation(self, user: User) -> None:
        """Test string representation of UserProfile."""
        assert_that(str(user.profile), equal_to('Profile for testuser'))

    def test_profile_timestamps(self, user: User) -> None:
        """Test that profile has created_at and updated_at timestamps."""
        profile = user.profile
        assert_that(profile.created_at, is_(not_none()))
        assert_that(profile.updated_at, is_(not_none()))


@pytest.mark.django_db
class TestAPIAuthEnforcement:
    """Test that API endpoints enforce authentication correctly."""

    def test_location_post_allows_unauthenticated(self) -> None:
        """Test that OwnTracks POST to /api/locations/ works without auth."""
        client = APIClient()
        payload = {
            "_type": "location",
            "lat": 37.7749,
            "lon": -122.4194,
            "tst": 1700000000,
            "tid": "AB",
        }
        response = client.post('/api/locations/', payload, format='json')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    def test_location_list_requires_auth(self) -> None:
        """Test that GET /api/locations/ requires authentication."""
        client = APIClient()
        response = client.get('/api/locations/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_device_list_requires_auth(self) -> None:
        """Test that GET /api/devices/ requires authentication."""
        client = APIClient()
        response = client.get('/api/devices/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_location_list_with_auth_succeeds(self, auth_api_client: APIClient) -> None:
        """Test that authenticated GET /api/locations/ succeeds."""
        response = auth_api_client.get('/api/locations/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    def test_device_list_with_auth_succeeds(self, auth_api_client: APIClient) -> None:
        """Test that authenticated GET /api/devices/ succeeds."""
        response = auth_api_client.get('/api/devices/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


@pytest.mark.django_db
class TestAccountAPI:
    """Test account self-service endpoints."""

    def test_get_account_profile(self, auth_api_client: APIClient, user: User) -> None:
        """Test GET /api/account/ returns user profile."""
        response = auth_api_client.get('/api/account/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['username'], equal_to('testuser'))
        assert_that(response.data['email'], equal_to('test@example.com'))

    def test_get_account_requires_auth(self) -> None:
        """Test that GET /api/account/ requires authentication."""
        client = APIClient()
        response = client.get('/api/account/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_patch_account_updates_user_fields(
        self, auth_api_client: APIClient, user: User
    ) -> None:
        """Test PATCH /api/account/ updates user fields."""
        response = auth_api_client.patch(
            '/api/account/',
            {'first_name': 'Updated', 'last_name': 'Name'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        user.refresh_from_db()
        assert_that(user.first_name, equal_to('Updated'))
        assert_that(user.last_name, equal_to('Name'))

    def test_change_password_success(self, auth_api_client: APIClient, user: User) -> None:
        """Test POST /api/account/change-password/ changes password."""
        response = auth_api_client.post(
            '/api/account/change-password/',
            {
                'current_password': 'testpass123',
                'new_password': 'newpass456!',
            },
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['detail'], contains_string('Password updated'))

        user.refresh_from_db()
        assert_that(user.check_password('newpass456!'), is_(True))

    def test_change_password_wrong_current(self, auth_api_client: APIClient) -> None:
        """Test that change-password rejects wrong current password."""
        response = auth_api_client.post(
            '/api/account/change-password/',
            {
                'current_password': 'wrongpassword',
                'new_password': 'newpass456!',
            },
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_change_password_too_short(self, auth_api_client: APIClient) -> None:
        """Test that change-password rejects short new password."""
        response = auth_api_client.post(
            '/api/account/change-password/',
            {
                'current_password': 'testpass123',
                'new_password': 'short',
            },
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@pytest.mark.django_db
class TestAdminUserAPI:
    """Test admin user management endpoints."""

    def test_list_users_as_admin(self, admin_api_client: APIClient, admin_user: User) -> None:
        """Test GET /api/admin/users/ lists all users."""
        response = admin_api_client.get('/api/admin/users/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(greater_than(0)))

    def test_list_users_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test that non-admin users cannot list users."""
        response = auth_api_client.get('/api/admin/users/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_list_users_forbidden_for_unauthenticated(self) -> None:
        """Test that unauthenticated users cannot list users."""
        client = APIClient()
        response = client.get('/api/admin/users/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_create_user_as_admin(self, admin_api_client: APIClient) -> None:
        """Test POST /api/admin/users/ creates a new user."""
        response = admin_api_client.post(
            '/api/admin/users/',
            {
                'username': 'newuser',
                'email': 'new@example.com',
                'password': 'securepass123',
                'first_name': 'New',
                'last_name': 'User',
            },
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data['username'], equal_to('newuser'))

        created_user = User.objects.get(username='newuser')
        assert_that(created_user.check_password('securepass123'), is_(True))
        assert_that(hasattr(created_user, 'profile'), is_(True))

    def test_create_user_forbidden_for_non_admin(self, auth_api_client: APIClient) -> None:
        """Test that non-admin users cannot create users."""
        response = auth_api_client.post(
            '/api/admin/users/',
            {'username': 'hacker', 'password': 'pass123'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_create_duplicate_user(self, admin_api_client: APIClient, user: User) -> None:
        """Test that creating a user with existing username returns 409."""
        response = admin_api_client.post(
            '/api/admin/users/',
            {'username': 'testuser', 'password': 'pass123'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))

    def test_create_user_without_password(self, admin_api_client: APIClient) -> None:
        """Test that creating a user without password returns 400."""
        response = admin_api_client.post(
            '/api/admin/users/',
            {'username': 'nopass'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_deactivate_user(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test DELETE /api/admin/users/{id}/ deactivates the user."""
        response = admin_api_client.delete(f'/api/admin/users/{user.pk}/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['detail'], contains_string('deactivated'))

        user.refresh_from_db()
        assert_that(user.is_active, is_(False))

    def test_deactivate_self_forbidden(
        self, admin_api_client: APIClient, admin_user: User
    ) -> None:
        """Test that admin cannot deactivate their own account."""
        response = admin_api_client.delete(f'/api/admin/users/{admin_user.pk}/')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('own account'))

    def test_deactivate_nonexistent_user(self, admin_api_client: APIClient) -> None:
        """Test that deactivating a nonexistent user returns 404."""
        response = admin_api_client.delete('/api/admin/users/99999/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_create_admin_user(self, admin_api_client: APIClient) -> None:
        """Test creating a user with is_staff=True makes them admin."""
        response = admin_api_client.post(
            '/api/admin/users/',
            {
                'username': 'newadmin',
                'password': 'securepass123',
                'is_staff': True,
            },
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))

        created_user = User.objects.get(username='newadmin')
        assert_that(created_user.is_staff, is_(True))
        assert_that(created_user.is_superuser, is_(True))

    def test_reactivate_user(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test POST /api/admin/users/{id}/reactivate/ reactivates a user."""
        user.is_active = False
        user.save()

        response = admin_api_client.post(f'/api/admin/users/{user.pk}/reactivate/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['detail'], contains_string('reactivated'))

        user.refresh_from_db()
        assert_that(user.is_active, is_(True))

    def test_reactivate_nonexistent_user(self, admin_api_client: APIClient) -> None:
        """Test reactivating a nonexistent user returns 404."""
        response = admin_api_client.post('/api/admin/users/99999/reactivate/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_toggle_admin_promotes_user(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test toggle-admin promotes a regular user to admin."""
        assert_that(user.is_staff, is_(False))

        response = admin_api_client.post(f'/api/admin/users/{user.pk}/toggle-admin/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['is_staff'], is_(True))

        user.refresh_from_db()
        assert_that(user.is_staff, is_(True))
        assert_that(user.is_superuser, is_(True))

    def test_toggle_admin_demotes_admin(
        self, admin_api_client: APIClient, db: Any
    ) -> None:
        """Test toggle-admin demotes an admin to regular user."""
        other_admin = User.objects.create_superuser(
            username='otheradmin', password='pass123'
        )
        assert_that(other_admin.is_staff, is_(True))

        response = admin_api_client.post(f'/api/admin/users/{other_admin.pk}/toggle-admin/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['is_staff'], is_(False))

        other_admin.refresh_from_db()
        assert_that(other_admin.is_staff, is_(False))
        assert_that(other_admin.is_superuser, is_(False))

    def test_toggle_admin_self_forbidden(
        self, admin_api_client: APIClient, admin_user: User
    ) -> None:
        """Test that admin cannot toggle their own admin status."""
        response = admin_api_client.post(f'/api/admin/users/{admin_user.pk}/toggle-admin/')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('own admin status'))

    def test_toggle_admin_nonexistent_user(self, admin_api_client: APIClient) -> None:
        """Test toggling admin on a nonexistent user returns 404."""
        response = admin_api_client.post('/api/admin/users/99999/toggle-admin/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_hard_delete_user(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test permanently deleting a user."""
        user_pk = user.pk
        response = admin_api_client.delete(f'/api/admin/users/{user_pk}/hard-delete/')
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['detail'], contains_string('permanently deleted'))
        assert_that(User.objects.filter(pk=user_pk).exists(), is_(False))

    def test_hard_delete_self_forbidden(
        self, admin_api_client: APIClient, admin_user: User
    ) -> None:
        """Test that admins cannot delete their own account."""
        response = admin_api_client.delete(f'/api/admin/users/{admin_user.pk}/hard-delete/')
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('own account'))

    def test_hard_delete_nonexistent_user(self, admin_api_client: APIClient) -> None:
        """Test deleting a nonexistent user returns 404."""
        response = admin_api_client.delete('/api/admin/users/99999/hard-delete/')
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_hard_delete_forbidden_for_regular_user(
        self, auth_api_client: APIClient, admin_user: User
    ) -> None:
        """Test that non-admin users cannot hard-delete."""
        response = auth_api_client.delete(f'/api/admin/users/{admin_user.pk}/hard-delete/')
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_set_password(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test setting a user's password."""
        response = admin_api_client.post(
            f'/api/admin/users/{user.pk}/set-password/',
            {'password': 'newSecureP@ss99'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data['detail'], contains_string('updated'))

        user.refresh_from_db()
        assert_that(user.check_password('newSecureP@ss99'), is_(True))

    def test_set_password_too_short(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test setting a password that is too short."""
        response = admin_api_client.post(
            f'/api/admin/users/{user.pk}/set-password/',
            {'password': 'short'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('at least 8'))

    def test_set_password_missing(
        self, admin_api_client: APIClient, user: User
    ) -> None:
        """Test setting a password with no password field."""
        response = admin_api_client.post(
            f'/api/admin/users/{user.pk}/set-password/',
            {},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.data['error'], contains_string('required'))

    def test_set_password_nonexistent_user(self, admin_api_client: APIClient) -> None:
        """Test setting password on a nonexistent user returns 404."""
        response = admin_api_client.post(
            '/api/admin/users/99999/set-password/',
            {'password': 'newSecureP@ss99'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_set_password_forbidden_for_regular_user(
        self, auth_api_client: APIClient, admin_user: User
    ) -> None:
        """Test that non-admin users cannot set passwords."""
        response = auth_api_client.post(
            f'/api/admin/users/{admin_user.pk}/set-password/',
            {'password': 'newSecureP@ss99'},
            format='json',
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# ---------------------------------------------------------------------------
# CommandApiKeyAuthentication
# ---------------------------------------------------------------------------

factory = APIRequestFactory()


class TestGetCommandApiKey:
    """Tests for get_command_api_key helper."""

    @patch("my_tracks.auth.config", return_value="test-secret-key")
    def test_returns_configured_key(self, mock_config: Any) -> None:
        """Returns the configured COMMAND_API_KEY."""
        result = get_command_api_key()
        assert_that(result, equal_to("test-secret-key"))

    @patch("my_tracks.auth.config", return_value="")
    def test_returns_empty_when_not_set(self, mock_config: Any) -> None:
        """Returns empty string when COMMAND_API_KEY is not configured."""
        result = get_command_api_key()
        assert_that(result, equal_to(""))


class TestCommandApiKeyAuthentication:
    """Tests for CommandApiKeyAuthentication bearer-token auth."""

    def _make_request(self, auth_header: str | None = None) -> Any:
        """Build a DRF request with optional Authorization header."""
        kwargs: dict[str, str] = {}
        if auth_header is not None:
            kwargs["HTTP_AUTHORIZATION"] = auth_header
        return factory.get("/fake/", **kwargs)

    @patch("my_tracks.auth.get_command_api_key", return_value="")
    def test_no_api_key_configured_skips_auth(self, mock_key: Any) -> None:
        """When no key is configured, authentication is skipped (returns None)."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request()
        result = auth.authenticate(request)
        assert_that(result, is_(None))

    @patch("my_tracks.auth.get_command_api_key", return_value="my-secret")
    def test_missing_header_raises(self, mock_key: Any) -> None:
        """Raises AuthenticationFailed when Authorization header is absent."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request()
        try:
            auth.authenticate(request)
            raise AssertionError("Expected AuthenticationFailed")
        except AuthenticationFailed as exc:
            assert_that(str(exc.detail), contains_string("Authorization header"))

    @patch("my_tracks.auth.get_command_api_key", return_value="my-secret")
    def test_invalid_format_raises(self, mock_key: Any) -> None:
        """Raises AuthenticationFailed for non-Bearer format."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request("Basic dXNlcjpwYXNz")
        try:
            auth.authenticate(request)
            raise AssertionError("Expected AuthenticationFailed")
        except AuthenticationFailed as exc:
            assert_that(str(exc.detail), contains_string("Bearer"))

    @patch("my_tracks.auth.get_command_api_key", return_value="my-secret")
    def test_wrong_token_raises(self, mock_key: Any) -> None:
        """Raises AuthenticationFailed when token doesn't match."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request("Bearer wrong-token")
        try:
            auth.authenticate(request)
            raise AssertionError("Expected AuthenticationFailed")
        except AuthenticationFailed as exc:
            assert_that(str(exc.detail), contains_string("Invalid API key"))

    @patch("my_tracks.auth.get_command_api_key", return_value="my-secret")
    def test_valid_token_returns_anonymous_user(self, mock_key: Any) -> None:
        """Returns (AnonymousUser, token) tuple for valid Bearer token."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request("Bearer my-secret")
        result = auth.authenticate(request)
        assert_that(result, is_not(None))
        assert_that(result[1], equal_to("my-secret"))

    @patch("my_tracks.auth.get_command_api_key", return_value="my-secret")
    def test_bearer_case_insensitive(self, mock_key: Any) -> None:
        """'bearer' prefix is matched case-insensitively."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request("bearer my-secret")
        result = auth.authenticate(request)
        assert_that(result, is_not(None))
        assert_that(result[1], equal_to("my-secret"))

    @patch("my_tracks.auth.get_command_api_key", return_value="my-secret")
    def test_single_word_header_raises(self, mock_key: Any) -> None:
        """Raises AuthenticationFailed for single-word Authorization header."""
        auth = CommandApiKeyAuthentication()
        request = self._make_request("my-secret")
        try:
            auth.authenticate(request)
            raise AssertionError("Expected AuthenticationFailed")
        except AuthenticationFailed as exc:
            assert_that(str(exc.detail), contains_string("Bearer"))
