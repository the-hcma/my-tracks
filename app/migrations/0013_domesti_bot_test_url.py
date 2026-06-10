from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0012_domesti_bot_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="domestibotconfig",
            name="participant_location_test_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="URL where my-tracks POSTs synthetic test location fixes (not live ingest)",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="domestibotconfig",
            name="participant_location_update_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="URL where my-tracks POSTs live participant location fixes",
                max_length=500,
            ),
        ),
    ]
