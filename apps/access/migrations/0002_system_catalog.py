from django.db import migrations

from apps.access.catalog import sync_catalog


def forwards(apps, schema_editor):
    sync_catalog(
        apps.get_model("access", "Role"),
        apps.get_model("access", "Permission"),
        apps.get_model("access", "RolePermission"),
    )


class Migration(migrations.Migration):
    dependencies = [("access", "0001_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
