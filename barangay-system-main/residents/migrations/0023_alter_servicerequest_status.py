from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0022_userprofile_address_userprofile_valid_id_image"),
    ]

    operations = [
        migrations.AlterField(
            model_name="servicerequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("Pending", "Pending"),
                    ("Processing", "Processing"),
                    ("Approved", "Approved"),
                    ("Ready for Printing", "Ready for Printing"),
                    ("Released", "Released"),
                    ("Rejected", "Rejected"),
                ],
                default="Pending",
                max_length=20,
            ),
        ),
    ]
