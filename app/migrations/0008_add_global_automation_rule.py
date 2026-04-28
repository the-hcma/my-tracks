"""Add GlobalAutomationRule model for admin-defined multi-user geofence automations."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("my_tracks", "0007_alter_waypoint_rid"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GlobalAutomationRule",
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
                    "name",
                    models.CharField(
                        help_text="Human-readable label for this rule",
                        max_length=200,
                    ),
                ),
                (
                    "condition",
                    models.CharField(
                        choices=[
                            ("all_inside", "All users inside"),
                            ("all_outside", "All users outside"),
                        ],
                        default="all_inside",
                        help_text="'all_inside' or 'all_outside'",
                        max_length=20,
                    ),
                ),
                (
                    "action_type",
                    models.CharField(
                        choices=[("email", "Email"), ("webhook", "Webhook")],
                        default="email",
                        max_length=20,
                    ),
                ),
                (
                    "email_address",
                    models.EmailField(
                        blank=True,
                        help_text="Recipient email address (for email action)",
                    ),
                ),
                (
                    "webhook_url",
                    models.URLField(
                        blank=True,
                        help_text="HTTP endpoint to POST to (for webhook action)",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Whether this rule is currently active",
                    ),
                ),
                (
                    "last_condition_met",
                    models.BooleanField(
                        default=None,
                        help_text=(
                            "Tracks fire-once state: None=never evaluated, "
                            "True=condition met (fired), False=condition not met (reset)"
                        ),
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="Admin who created this rule",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="global_automation_rules_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "users",
                    models.ManyToManyField(
                        help_text="Users whose location is evaluated",
                        related_name="global_automation_rules",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "waypoint",
                    models.ForeignKey(
                        help_text="Geofence this rule watches",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="global_automation_rules",
                        to="my_tracks.waypoint",
                    ),
                ),
            ],
            options={
                "verbose_name": "Global Automation Rule",
                "verbose_name_plural": "Global Automation Rules",
                "ordering": ["name"],
            },
        ),
        migrations.AddIndex(
            model_name="globalautomationrule",
            index=models.Index(
                fields=["is_active"], name="gar_active_idx"
            ),
        ),
    ]
