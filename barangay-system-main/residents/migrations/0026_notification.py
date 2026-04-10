from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0025_service_request_secretary_workflow"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("message", models.TextField()),
                ("category", models.CharField(choices=[("service_request", "Service Request"), ("account", "Account"), ("complaint", "Complaint"), ("payment", "Payment"), ("general", "General")], default="general", max_length=30)),
                ("target_url", models.CharField(blank=True, max_length=255)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "is_read", "created_at"], name="residents_no_user_id_1dd752_idx"),
        ),
    ]
