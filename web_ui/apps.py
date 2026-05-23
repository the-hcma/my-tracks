"""Django app configuration for web_ui."""

from django.apps import AppConfig


class WebUiConfig(AppConfig):
    """Configuration for the Web UI application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "web_ui"
    verbose_name = "Web User Interface"
