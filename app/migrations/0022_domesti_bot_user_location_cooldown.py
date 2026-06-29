"""Admin-configurable per-user reportLocation cooldown."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0021_domesti_bot_device_location_cooldown"),
    ]

    operations = [
        migrations.AddField(
            model_name="domestibotconfig",
            name="location_request_user_cooldown_seconds",
            field=models.PositiveIntegerField(
                default=30,
                help_text=("Minimum seconds between all-device reportLocation fan-out requests for the same user"),
            ),
        ),
    ]
