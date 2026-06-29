"""Enforce minimum cooldown values on domesti-bot config fields."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0022_domesti_bot_user_location_cooldown"),
    ]

    operations = [
        migrations.AlterField(
            model_name="domestibotconfig",
            name="location_request_device_cooldown_seconds",
            field=models.PositiveIntegerField(
                default=2,
                help_text=("Minimum seconds between reportLocation requests for the same device (device endpoint)"),
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="domestibotconfig",
            name="location_request_user_cooldown_seconds",
            field=models.PositiveIntegerField(
                default=30,
                help_text=("Minimum seconds between all-device reportLocation fan-out requests for the same user"),
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
    ]
