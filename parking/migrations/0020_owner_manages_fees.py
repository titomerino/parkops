from django.db import migrations

OWNER_GROUP = "Dueño de parqueo"


def grant_to_owners(apps, schema_editor):
    """El rol «Dueño de parqueo» puede crear y modificar las tarifas de su parqueo.

    Otros roles (p. ej. «Administrador») se habilitan en Admin → Grupos con
    «Can add Tarifa» y «Can change Tarifa».
    """
    from django.contrib.auth.management import create_permissions

    # En una base nueva los permisos se crean recién en post_migrate
    app_config = apps.get_app_config("parking")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permissions = Permission.objects.filter(content_type__app_label="parking", codename__in=["add_fee", "change_fee"])
    for group in Group.objects.filter(name=OWNER_GROUP):
        group.permissions.add(*permissions)


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('parking', '0019_key_deposit'),
    ]

    operations = [
        migrations.RunPython(grant_to_owners, migrations.RunPython.noop),
    ]
