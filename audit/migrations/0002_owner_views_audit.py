from django.db import migrations

OWNER_GROUP = "Dueño de parqueo"


def grant_to_owners(apps, schema_editor):
    """El rol «Dueño de parqueo» ve la auditoría de su parqueo.

    Otros roles (p. ej. «Administrador») se habilitan en Admin → Grupos con
    «Can view Evento de auditoría».
    """
    from django.contrib.auth.management import create_permissions

    app_config = apps.get_app_config("audit")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permission = Permission.objects.get(content_type__app_label="audit", codename="view_auditevent")
    for group in Group.objects.filter(name=OWNER_GROUP):
        group.permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(grant_to_owners, migrations.RunPython.noop),
    ]
