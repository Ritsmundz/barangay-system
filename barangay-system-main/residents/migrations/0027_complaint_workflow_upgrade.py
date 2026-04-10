from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_complaint_statuses(apps, schema_editor):
    Complaint = apps.get_model("residents", "Complaint")
    status_map = {
        "Pending": "Submitted",
        "Under Investigation": "For Verification",
        "For Mediation": "For Scheduling",
    }
    for old_status, new_status in status_map.items():
        Complaint.objects.filter(status=old_status).update(status=new_status)


def rollback_complaint_statuses(apps, schema_editor):
    Complaint = apps.get_model("residents", "Complaint")
    status_map = {
        "Submitted": "Pending",
        "For Verification": "Under Investigation",
        "For Scheduling": "For Mediation",
    }
    for new_status, old_status in status_map.items():
        Complaint.objects.filter(status=new_status).update(status=old_status)


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0026_notification"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(migrate_complaint_statuses, rollback_complaint_statuses),
        migrations.AddField(
            model_name="complaint",
            name="meeting_datetime",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="complaint",
            name="meeting_location",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="complaint",
            name="meeting_purpose",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="complaint",
            name="scheduled_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scheduled_complaints", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="complaint",
            name="secretary_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="status",
            field=models.CharField(
                choices=[
                    ("Submitted", "Submitted"),
                    ("Received", "Received"),
                    ("Under Review", "Under Review"),
                    ("For Verification", "For Verification"),
                    ("For Scheduling", "For Scheduling"),
                    ("Scheduled for Hearing", "Scheduled for Hearing"),
                    ("Ongoing Mediation", "Ongoing Mediation"),
                    ("Resolved / Settled", "Resolved / Settled"),
                    ("Unresolved", "Unresolved"),
                    ("Referred", "Referred"),
                    ("Withdrawn", "Withdrawn"),
                ],
                default="Submitted",
                max_length=40,
            ),
        ),
    ]
