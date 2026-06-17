"""Track last relayed location per user to avoid duplicate domesti-bot deliveries."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0017_remove_global_automation_rule"),
    ]

    operations = [
        migrations.AddField(
            model_name="domestibotconfig",
            name="last_relayed_location_by_user",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Per-user fingerprint of the last live location successfully relayed to domesti-bot",
            ),
        ),
    ]
