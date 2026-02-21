"""
ASGI config for my_tracks project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import asyncio
import logging
import os
from typing import Any, Callable, cast

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from my_tracks.routing import websocket_urlpatterns

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

logger = logging.getLogger(__name__)


class ClientDisconnectMiddleware:
    """ASGI middleware that handles client disconnections gracefully.

    When a client disconnects mid-request (e.g., browser tab closed, network
    drop), the ASGI server cancels the async task. This propagates through
    asgiref's sync_to_async as a CancelledError on a shielded future, which
    asyncio's default exception handler logs at ERROR with a full traceback.

    This middleware catches the CancelledError at the application boundary
    so it never reaches the event loop's exception handler.
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        try:
            await self.app(scope, receive, send)
        except asyncio.CancelledError:
            method = scope.get('method', '')
            path = scope.get('path', '')
            logger.debug("Client disconnected during %s %s", method, path)


application = ProtocolTypeRouter({
    "http": ClientDisconnectMiddleware(django_asgi_app),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            cast(list, websocket_urlpatterns)  # type: ignore[arg-type]
        )
    ),
})

