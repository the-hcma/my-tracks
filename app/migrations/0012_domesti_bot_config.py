from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_tracks", "0011_friendrequest_auto_accept_reciprocal"),
    ]

    operations = [
        migrations.CreateModel(
            name="DomestiBotConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "domesti_base_url",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="domesti-bot HTTP origin (reference and URL building)",
                        max_length=500,
                    ),
                ),
                (
                    "participant_location_update_url",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="URL where my-tracks POSTs participant location fixes",
                        max_length=500,
                    ),
                ),
                (
                    "encrypted_api_key",
                    models.BinaryField(
                        blank=True,
                        default=b"",
                        help_text="domesti-bot API key encrypted at rest (Fernet/SECRET_KEY)",
                    ),
                ),
                (
                    "paired_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When domesti-bot last completed pairing",
                        null=True,
                    ),
                ),
                (
                    "location_updates_enabled",
                    models.BooleanField(
                        default=False,
                        help_text="When enabled, POST each saved location to domesti-bot",
                    ),
                ),
                (
                    "recent_webhook_log",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Ring buffer of the five most recent webhook delivery attempts",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "domesti-bot configuration",
            },
        ),
    ]
