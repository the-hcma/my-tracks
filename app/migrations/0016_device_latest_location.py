"""Add Device.latest_location FK and backfill from existing Location rows."""

from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def backfill_device_latest_locations(apps, schema_editor) -> None:
    Device = apps.get_model("my_tracks", "Device")
    Location = apps.get_model("my_tracks", "Location")
    connection = schema_editor.connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE my_tracks_device AS d
                SET latest_location_id = sub.id
                FROM (
                    SELECT DISTINCT ON (device_id) id, device_id
                    FROM my_tracks_location
                    ORDER BY device_id, timestamp DESC, id DESC
                ) AS sub
                WHERE d.id = sub.device_id
                """
            )
        return

    latest_id = Subquery(
        Location.objects.filter(device_id=OuterRef("pk")).order_by("-timestamp", "-id").values("id")[:1]
    )
    for device in Device.objects.annotate(_latest_id=latest_id).iterator():
        Device.objects.filter(pk=device.pk).update(latest_location_id=device._latest_id)


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0015_nomenclature_help_text"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="latest_location",
            field=models.ForeignKey(
                blank=True,
                help_text="Most recent location row for this device (by timestamp)",
                null=True,
                on_delete=models.SET_NULL,
                related_name="+",
                to="my_tracks.location",
            ),
        ),
        migrations.RunPython(
            backfill_device_latest_locations,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
