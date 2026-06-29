"""Per-device reportLocation cooldown setting and last-request timestamps."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0020_domesti_bot_remote_request_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="domestibotconfig",
            name="location_request_device_cooldown_seconds",
            field=models.PositiveIntegerField(
                default=2,
                help_text="Minimum seconds between reportLocation requests for the same device (device endpoint)",
            ),
        ),
        migrations.AddField(
            model_name="domestibotconfig",
            name="last_location_request_at_by_device",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Per-device ISO timestamp of the last domesti-bot reportLocation request (mqtt_user/device_id key)"
                ),
            ),
        ),
    ]
