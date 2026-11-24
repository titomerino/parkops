"""Empleados de un parqueo: lo que su dueño puede ver y administrar."""
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.db.models import Q

from tenants.models import ParkingMember

MANAGE_PERMISSION = "tenants.manage_employees"
DELETE_ENTRY_PERMISSION = "parking.delete_entry"

# Sin letras ni números que se confundan (0/O, 1/l/I) para dictarla por WhatsApp
TEMP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_temp_password():
    """Contraseña temporal fácil de dictar, p. ej. «K7QM-4XHT»."""
    chars = "".join(secrets.choice(TEMP_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def _manage_permission():
    app_label, codename = MANAGE_PERMISSION.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _owners_q():
    """Usuarios que también administran empleados (otros dueños): no se tocan."""
    permission = _manage_permission()
    return Q(is_superuser=True) | Q(is_staff=True) | Q(user_permissions=permission) | Q(groups__permissions=permission)


def parking_users(parking):
    return get_user_model().objects.filter(parking_membership__parking=parking)


def manageable_employees(owner, parking):
    """Los empleados del parqueo que este dueño puede editar (nunca él mismo ni otros dueños)."""
    others = parking_users(parking).filter(_owners_q()).values("pk")
    return (
        parking_users(parking)
        .exclude(pk=owner.pk)
        .exclude(pk__in=others)
        .select_related("parking_membership")
        .prefetch_related("groups")
    )


def other_owners(owner, parking):
    """Otros dueños o administradores del parqueo (se muestran sin poder editarlos)."""
    return parking_users(parking).filter(_owners_q()).exclude(pk=owner.pk).distinct()


def assignable_groups(owner):
    """Roles que el dueño puede dar: solo con permisos que él mismo tiene y sin el de administrar empleados."""
    owner_perms = owner.get_all_permissions()
    groups = []
    for group in Group.objects.prefetch_related("permissions__content_type").order_by("name"):
        perms = {f"{p.content_type.app_label}.{p.codename}" for p in group.permissions.all()}
        if MANAGE_PERMISSION in perms:
            continue
        if owner.is_superuser or perms <= owner_perms:
            groups.append(group)
    return groups


def can_grant_delete(owner):
    return owner.has_perm(DELETE_ENTRY_PERMISSION)


@transaction.atomic
def save_employee(owner, parking, user, *, role, can_delete_entries, created):
    """Guarda el empleado, su rol (entre los que el dueño puede dar) y su permiso de eliminar entradas."""
    user.save()
    if created:
        ParkingMember.objects.create(user=user, parking=parking, must_change_password=True)

    # Solo se reemplazan los roles que este dueño administra; otros (dados en el admin) se conservan
    assignable = assignable_groups(owner)
    user.groups.remove(*assignable)
    if role:
        user.groups.add(role)

    if can_grant_delete(owner):
        app_label, codename = DELETE_ENTRY_PERMISSION.split(".")
        permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        if can_delete_entries:
            user.user_permissions.add(permission)
        else:
            user.user_permissions.remove(permission)
    return user


def reset_password(user):
    """Pone una contraseña temporal y le pide cambiarla al entrar. Devuelve la contraseña."""
    password = generate_temp_password()
    user.set_password(password)
    user.save(update_fields=["password"])
    ParkingMember.objects.filter(user=user).update(must_change_password=True)
    return password
