"""Rename domesti-bot relay URL fields to user/location nomenclature."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0013_domesti_bot_test_url"),
    ]

    operations = [
        migrations.RenameField(
            model_name="domestibotconfig",
            old_name="participant_location_update_url",
            new_name="user_location_update_url",
        ),
        migrations.RenameField(
            model_name="domestibotconfig",
            old_name="participant_location_test_url",
            new_name="user_location_test_url",
        ),
        migrations.AlterField(
            model_name="domestibotconfig",
            name="user_location_update_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="URL where my-tracks POSTs live user location updates",
                max_length=500,
            ),
        ),
    ]
