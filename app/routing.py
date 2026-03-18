"""
WebSocket URL routing for tracker app.

Defines WebSocket URL patterns for real-time location updates.
"""
from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('ws/locations/', consumers.LocationConsumer.as_asgi()),
]
