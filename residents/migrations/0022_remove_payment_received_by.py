from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0021_userprofile_is_auto_matched"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="payment",
            name="received_by",
        ),
    ]
