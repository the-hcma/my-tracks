"""Remove GlobalAutomationRule model (migrated to domesti-bot)."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0016_device_latest_location"),
    ]

    operations = [
        migrations.DeleteModel(
            name="GlobalAutomationRule",
        ),
    ]
