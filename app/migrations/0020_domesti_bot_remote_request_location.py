"""Add domesti-bot remote request-location capability and per-user cooldown state."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0019_location_optional_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="domestibotconfig",
            name="remote_request_location_enabled",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, accept domesti-bot relay API key on request-location endpoint",
            ),
        ),
        migrations.AddField(
            model_name="domestibotconfig",
            name="last_location_request_at_by_user",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Per-user ISO timestamp of the last domesti-bot reportLocation request",
            ),
        ),
    ]
