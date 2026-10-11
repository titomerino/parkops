"""
Paso 2 de multi-parqueo: asigna todos los datos existentes a un parqueo.

- Si la base ya tiene datos (entradas, tarifas, usuarios...), crea
  «Parqueo principal» y le asigna TODOS los registros y usuarios no
  superusuarios. No modifica montos, fechas ni placas.
- Una base nueva (sin datos) no crea ningún parqueo.
- Deja en la base un valor por defecto temporal (el parqueo principal)
  para que, mientras Railway cambia de versión, el código anterior pueda
  seguir registrando sin error. Se quita en una versión posterior.
"""
from django.conf import settings
from django.db import migrations

TABLES = [
    ("parking", "Fee"),
    ("parking", "Entry"),
    ("parking", "PlatePolicy"),
    ("bathrooms", "BathroomFee"),
    ("bathrooms", "BathroomEntry"),
    ("payment", "Subscription"),
]


def check_single_default_fee(apps):
    Fee = apps.get_model("parking", "Fee")
    defaults = list(Fee.objects.filter(default=True).values_list("pk", "name"))

    if len(defaults) > 1:
        detail = "\n".join(f"  - id {pk}: {name}" for pk, name in defaults)
        raise RuntimeError(
            "Hay más de una tarifa marcada como «Activa por defecto»:\n"
            f"{detail}\n"
            "Deja solo una marcada desde el admin y vuelve a migrar."
        )


def assign_to_principal(apps, schema_editor):
    check_single_default_fee(apps)

    Parking = apps.get_model("tenants", "Parking")
    Member = apps.get_model("tenants", "ParkingMember")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Configuration = apps.get_model("parking", "Configuration")
    models = [apps.get_model(app, model) for app, model in TABLES]

    has_data = (
        any(M.objects.exists() for M in models)
        or User.objects.filter(is_superuser=False).exists()
    )
    if not has_data:
        return

    config = Configuration.objects.order_by("pk").first()
    principal = Parking.objects.order_by("pk").first() or Parking.objects.create(
        name=config.name if config else "Parqueo principal",
        capacity=config.ability if config else None,
    )

    for M in models:
        M.objects.filter(parking__isnull=True).update(parking=principal)

    for user in User.objects.filter(is_superuser=False, parking_membership__isnull=True):
        Member.objects.create(user=user, parking=principal)

    # Las verificaciones de llave foránea quedan pendientes tras el UPDATE y
    # Postgres no permite ALTER TABLE así: se ejecutan ahora.
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    quote = schema_editor.quote_name
    for M in models:
        schema_editor.execute(
            f"ALTER TABLE {quote(M._meta.db_table)} "
            f"ALTER COLUMN {quote('parking_id')} SET DEFAULT {int(principal.pk)}"
        )


def unassign(apps, schema_editor):
    quote = schema_editor.quote_name
    for app, model in TABLES:
        M = apps.get_model(app, model)
        schema_editor.execute(
            f"ALTER TABLE {quote(M._meta.db_table)} ALTER COLUMN {quote('parking_id')} DROP DEFAULT"
        )
        M.objects.update(parking=None)

    apps.get_model("tenants", "ParkingMember").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("parking", "0016_parking_nullable"),
        ("bathrooms", "0004_parking_nullable"),
        ("payment", "0003_parking_nullable"),
    ]

    operations = [
        migrations.RunPython(assign_to_principal, unassign),
    ]
