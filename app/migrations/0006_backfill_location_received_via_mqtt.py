"""Backfill received_via='mqtt' for all existing Location records with no value."""

from django.db import migrations


def backfill_received_via_mqtt(apps, schema_editor):
    Location = apps.get_model("my_tracks", "Location")
    Location.objects.filter(received_via="").update(received_via="mqtt")


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0005_add_location_received_via"),
    ]

    operations = [
        migrations.RunPython(
            backfill_received_via_mqtt,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
