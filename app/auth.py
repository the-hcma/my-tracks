"""
Custom authentication for OwnTracks command endpoints.

Provides a simple bearer token authentication backed by an environment
variable, suitable for a personal tracking server where full user
management is unnecessary.
"""

import logging

from decouple import config
from rest_framework import authentication, exceptions
from rest_framework.request import Request

logger = logging.getLogger(__name__)


class _ApiKeyUser:
    """
    Minimal user-like sentinel returned when a valid API key is presented.

    DRF's IsAuthenticated checks ``request.user.is_authenticated``; returning
    AnonymousUser (is_authenticated=False) would silently deny every API-key
    request even with the correct token.  This sentinel satisfies the check
    while remaining clearly distinct from a real Django user.
    """

    is_authenticated = True
    is_active = True
    is_anonymous = False
    is_staff = False
    username = "api-key"

    def __str__(self) -> str:
        return "api-key"


_API_KEY_USER = _ApiKeyUser()


def get_command_api_key() -> str:
    """
    Get the configured command API key.

    Returns:
        The API key string, or empty string if not configured.
    """
    return str(config("COMMAND_API_KEY", default=""))


class CommandApiKeyAuthentication(authentication.BaseAuthentication):
    """
    Bearer token authentication using a shared API key.

    Expects an Authorization header in the format:
        Authorization: Bearer <api_key>

    The API key is read from the COMMAND_API_KEY environment variable.
    If COMMAND_API_KEY is not set, authentication is skipped (open access).
    """

    def authenticate(self, request: Request) -> tuple[object, str] | None:
        """
        Authenticate the request using a bearer token.

        Args:
            request: The incoming DRF request

        Returns:
            Tuple of (user, token) if authenticated, None if auth not applicable

        Raises:
            AuthenticationFailed: If token is provided but invalid
        """
        api_key = get_command_api_key()
        if not api_key:
            # No API key configured — skip authentication (open access)
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            # No Bearer token — let SessionAuthentication (or other classes) handle the request.
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise exceptions.AuthenticationFailed("Expected 'Bearer <token>' format, got invalid Authorization header")

        token = parts[1]
        if token != api_key:
            logger.warning("Invalid command API key attempt")
            raise exceptions.AuthenticationFailed("Invalid API key")

        # Return a sentinel that satisfies IsAuthenticated
        return (_API_KEY_USER, token)
