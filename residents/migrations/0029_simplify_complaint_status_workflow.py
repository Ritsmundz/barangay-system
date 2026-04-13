from django.db import migrations, models


def simplify_complaint_statuses(apps, schema_editor):
    Complaint = apps.get_model("residents", "Complaint")
    Complaint.objects.filter(status__in=["Received", "For Verification"]).update(status="Under Review")


def rollback_complaint_statuses(apps, schema_editor):
    Complaint = apps.get_model("residents", "Complaint")
    Complaint.objects.filter(status="Under Review").update(status="Received")


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0028_complaint_schedule_response"),
    ]

    operations = [
        migrations.RunPython(simplify_complaint_statuses, rollback_complaint_statuses),
        migrations.AlterField(
            model_name="complaint",
            name="status",
            field=models.CharField(
                choices=[
                    ("Submitted", "Submitted"),
                    ("Under Review", "Under Review"),
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
