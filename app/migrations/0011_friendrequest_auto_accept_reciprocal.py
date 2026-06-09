from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0010_phase11_friends"),
    ]

    operations = [
        migrations.AddField(
            model_name="friendrequest",
            name="auto_accept_reciprocal",
            field=models.BooleanField(
                default=False,
                help_text="Sender pre-authorizes accepting a reciprocal request from the target user.",
            ),
        ),
    ]
