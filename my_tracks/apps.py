"""App configuration for my_tracks application."""
from django.apps import AppConfig


class MyTracksConfig(AppConfig):
    """Configuration for the my_tracks app."""

    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'my_tracks'
    verbose_name: str = 'My Tracks'
