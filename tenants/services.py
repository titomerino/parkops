"""Alta de cuentas de parqueo y roles de usuario."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from parking.models import Fee, Range
from tenants.models import Parking, ParkingMember

OWNER_GROUP = "Dueño de parqueo"
OPERATOR_GROUP = "Operador"

# (app, codename) por rol. Eliminar entradas (delete_entry) se asigna aparte.
ROLE_PERMISSIONS = {
    OPERATOR_GROUP: [
        ("parking", "add_entry"),
        ("parking", "view_entry"),
        ("parking", "view_platepolicy"),
        ("bathrooms", "add_bathroomentry"),
        ("bathrooms", "view_bathroomentry"),
    ],
    OWNER_GROUP: [
        ("parking", "add_entry"),
        ("parking", "change_entry"),
        ("parking", "view_entry"),
        ("parking", "view_statistics_entry"),
        ("parking", "add_platepolicy"),
        ("parking", "change_platepolicy"),
        ("parking", "view_platepolicy"),
        ("parking", "view_statistics_placepolicy"),
        ("parking", "view_fee"),
        ("bathrooms", "add_bathroomentry"),
        ("bathrooms", "view_bathroomentry"),
        ("bathrooms", "view_statistics_bathroomentry"),
        ("bathrooms", "add_bathroomfee"),
        ("bathrooms", "change_bathroomfee"),
        ("bathrooms", "view_bathroomfee"),
    ],
}

# Tarifa inicial: $1 la primera hora y +$0.50 cada media hora hasta $6
DEFAULT_FEE_RANGES = [(0, Decimal("1.00"))] + [
    (60 + 30 * i, Decimal("1.50") + Decimal("0.50") * i) for i in range(10)
]


def ensure_role_groups():
    """Crea o actualiza los grupos de roles con sus permisos."""
    groups = {}
    for name, perms in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(
            Permission.objects.get(content_type__app_label=app, codename=codename)
            for app, codename in perms
        )
        groups[name] = group
    return groups


def create_default_fee(parking):
    fee = Fee.objects.create(
        parking=parking,
        name="Normal",
        description="$1 la primera hora, luego +$0.50 cada media hora hasta $6",
        default=True,
    )
    Range.objects.bulk_create(
        Range(fee=fee, start_minute=minute, amount=amount)
        for minute, amount in DEFAULT_FEE_RANGES
    )
    return fee


@transaction.atomic
def create_parking_account(*, owner_username, owner_password, with_default_fee=True, **parking_fields):
    """
    Crea el parqueo, su usuario dueño (rol «Dueño de parqueo») y, si se
    pide, la tarifa inicial por defecto. Todo o nada.
    """
    parking = Parking.objects.create(**parking_fields)

    owner = get_user_model().objects.create_user(username=owner_username, password=owner_password)
    owner.groups.add(ensure_role_groups()[OWNER_GROUP])
    ParkingMember.objects.create(user=owner, parking=parking)

    if with_default_fee:
        create_default_fee(parking)

    return parking, owner
