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

from config.runtime import get_mqtt_port, update_runtime_config
from my_tracks.mqtt.broker import MQTTBroker
from my_tracks.routing import websocket_urlpatterns

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

logger = logging.getLogger(__name__)

# Global MQTT broker instance
_mqtt_broker: MQTTBroker | None = None


async def lifespan_handler(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """
    Handle ASGI lifespan events to start/stop the MQTT broker.

    This is called by the ASGI server (Daphne) on startup and shutdown.
    """
    global _mqtt_broker

    while True:
        message = await receive()
        if message['type'] == 'lifespan.startup':
            try:
                mqtt_port = get_mqtt_port()
                if mqtt_port >= 0:
                    logger.info("Starting MQTT broker on port %d", mqtt_port)
                    _mqtt_broker = MQTTBroker(
                        mqtt_port=mqtt_port,
                        allow_anonymous=False,
                        use_django_auth=True,
                    )
                    await _mqtt_broker.start()

                    # If port was 0, discover and publish the actual port
                    actual_mqtt_port = _mqtt_broker.actual_mqtt_port
                    if actual_mqtt_port is not None and actual_mqtt_port != mqtt_port:
                        logger.info("MQTT broker listening on OS-allocated port %d", actual_mqtt_port)
                        update_runtime_config("actual_mqtt_port", actual_mqtt_port)

                    logger.info("MQTT broker started successfully")
                else:
                    logger.info("MQTT broker disabled (port=%d)", mqtt_port)
                await send({'type': 'lifespan.startup.complete'})
            except Exception as e:
                logger.exception("Failed to start MQTT broker: %s", e)
                await send({'type': 'lifespan.startup.failed', 'message': str(e)})
        elif message['type'] == 'lifespan.shutdown':
            try:
                if _mqtt_broker is not None and _mqtt_broker.is_running:
                    logger.info("Stopping MQTT broker...")
                    await _mqtt_broker.stop()
                    logger.info("MQTT broker stopped")
            except Exception as e:
                logger.exception("Error stopping MQTT broker: %s", e)
            await send({'type': 'lifespan.shutdown.complete'})
            return


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
    "lifespan": lifespan_handler,
})

