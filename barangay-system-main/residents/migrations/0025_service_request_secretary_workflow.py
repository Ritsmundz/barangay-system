from django.db import migrations, models


def migrate_service_request_statuses(apps, schema_editor):
    ServiceRequest = apps.get_model("residents", "ServiceRequest")
    status_map = {
        "Pending": "Submitted",
        "Approved": "For Validation",
        "Ready for Printing": "Ready for Release",
    }
    for old_status, new_status in status_map.items():
        ServiceRequest.objects.filter(status=old_status).update(status=new_status)


def rollback_service_request_statuses(apps, schema_editor):
    ServiceRequest = apps.get_model("residents", "ServiceRequest")
    status_map = {
        "Submitted": "Pending",
        "For Validation": "Approved",
        "Ready for Release": "Ready for Printing",
    }
    for new_status, old_status in status_map.items():
        ServiceRequest.objects.filter(status=new_status).update(status=old_status)


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0024_repair_payment_received_by_column"),
    ]

    operations = [
        migrations.RunPython(migrate_service_request_statuses, rollback_service_request_statuses),
        migrations.AlterField(
            model_name="servicerequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("Submitted", "Submitted"),
                    ("Under Review", "Under Review"),
                    ("For Validation", "For Validation"),
                    ("Processing", "Processing"),
                    ("Ready for Release", "Ready for Release"),
                    ("Released", "Released"),
                    ("Pending Requirements", "Pending Requirements"),
                    ("On Hold", "On Hold"),
                    ("Rejected", "Rejected"),
                    ("Cancelled", "Cancelled"),
                ],
                default="Submitted",
                max_length=20,
            ),
        ),
    ]
