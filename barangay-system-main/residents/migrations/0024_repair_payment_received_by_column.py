from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0023_alter_servicerequest_status"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE residents_payment
                ADD COLUMN IF NOT EXISTS received_by_id integer NULL
            """,
            reverse_sql="""
                ALTER TABLE residents_payment
                DROP COLUMN IF EXISTS received_by_id
            """,
        ),
    ]
