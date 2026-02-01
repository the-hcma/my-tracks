"""App configuration for tracker application."""
from django.apps import AppConfig


class TrackerConfig(AppConfig):
    """Configuration for the tracker app."""

    default_auto_field: str = 'django.db.models.BigAutoField'
    name: str = 'tracker'
    verbose_name: str = 'My Tracks'
