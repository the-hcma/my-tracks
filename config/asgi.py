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

    This middleware:
    1. Catches the CancelledError at the application boundary.
    2. Installs a custom event-loop exception handler that silences
       CancelledError from orphaned shielded futures (created by asgiref's
       sync_to_async). Without this, the event loop's default handler still
       logs the error even though our try/except already handled it.
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app
        self._handler_installed = False

    def _install_exception_handler(self) -> None:
        """Install a custom event-loop exception handler (once per process)."""
        if self._handler_installed:
            return
        self._handler_installed = True

        loop = asyncio.get_running_loop()
        existing_handler = loop.get_exception_handler()

        def _handle_exception(lp: asyncio.AbstractEventLoop, ctx: dict[str, Any]) -> None:
            exception = ctx.get('exception')
            if isinstance(exception, asyncio.CancelledError):
                # Shielded-future CancelledError from a client disconnect —
                # already handled by the try/except below, so drop silently.
                logger.debug(
                    "Suppressed orphaned CancelledError from shielded future: %s",
                    ctx.get('message', ''),
                )
                return
            # Everything else goes through the original handler
            if existing_handler is not None:
                existing_handler(lp, ctx)
            else:
                lp.default_exception_handler(ctx)

        loop.set_exception_handler(_handle_exception)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        self._install_exception_handler()
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

