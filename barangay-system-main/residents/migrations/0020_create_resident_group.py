from django.db import migrations


def create_resident_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='Resident')


def remove_resident_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='Resident').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('residents', '0019_userprofile'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_resident_group, remove_resident_group),
    ]
