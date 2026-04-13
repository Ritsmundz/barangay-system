from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0027_complaint_workflow_upgrade"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaint",
            name="resident_schedule_response",
            field=models.CharField(
                choices=[
                    ("Pending Response", "Pending Response"),
                    ("Acknowledged", "Acknowledged"),
                    ("Needs Reschedule", "Needs Reschedule"),
                    ("Cannot Attend", "Cannot Attend"),
                ],
                default="Pending Response",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="complaint",
            name="resident_schedule_responded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="complaint",
            name="resident_schedule_response_note",
            field=models.TextField(blank=True),
        ),
    ]
