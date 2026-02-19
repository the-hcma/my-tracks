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


def get_command_api_key() -> str:
    """
    Get the configured command API key.

    Returns:
        The API key string, or empty string if not configured.
    """
    return str(config('COMMAND_API_KEY', default=''))


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

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header:
            raise exceptions.AuthenticationFailed(
                "Expected Authorization header with Bearer token, got none"
            )

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise exceptions.AuthenticationFailed(
                "Expected 'Bearer <token>' format, got invalid Authorization header"
            )

        token = parts[1]
        if token != api_key:
            logger.warning("Invalid command API key attempt")
            raise exceptions.AuthenticationFailed(
                "Invalid API key"
            )

        # Return a simple anonymous user representation with the token
        from django.contrib.auth.models import AnonymousUser
        return (AnonymousUser(), token)
