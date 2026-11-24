"""Registro de auditoría: cada vista llama a record() después de guardar.

Se registra en las vistas (no con señales de cada modelo) para saber siempre
qué usuario lo hizo y escribir un resumen que el dueño entienda.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models
from django.utils.timezone import localtime, now

from audit.models import AuditEvent

RETENTION_DAYS = 365

Action = AuditEvent.Action


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return ip or None


def display(value):
    """Valor legible para el «antes → después»."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, datetime):
        return localtime(value).strftime("%d/%m/%Y %H:%M")
    if isinstance(value, Decimal):
        return f"${value:.2f}"
    return str(value)


def snapshot(obj, fields):
    """{campo: (etiqueta, valor legible)} de un registro, para comparar antes y después."""
    data = {}
    for name in fields:
        field = obj._meta.get_field(name)
        if field.choices:
            value = getattr(obj, f"get_{name}_display")()
        elif isinstance(field, models.ForeignKey):
            value = getattr(obj, name)
        else:
            value = getattr(obj, name)
        data[name] = (str(field.verbose_name).capitalize(), display(value))
    return data


def diff(before, after):
    """Lista de cambios [{field, before, after}] entre dos snapshot()."""
    return [
        {"field": label, "before": before[name][1], "after": value}
        for name, (label, value) in after.items()
        if name in before and before[name][1] != value
    ]


def record(request, action, summary, *, target="", changes=None, parking=None, user=None, username=None):
    """Guarda un evento. parking y user salen de la petición si no se pasan."""
    user = user if user is not None else getattr(request, "user", None)
    if user is not None and not user.is_authenticated:
        user = None
    if parking is None:
        parking = getattr(request, "parking", None)
    return AuditEvent.objects.create(
        parking=parking,
        user=user,
        username=(username if username is not None else (user.get_username() if user else ""))[:150],
        action=action,
        target=str(target)[:100],
        summary=summary[:300],
        changes=changes or [],
        ip=client_ip(request),
    )


def purge_old(days=RETENTION_DAYS):
    """Borra los eventos más viejos que `days` (por defecto 12 meses)."""
    deleted, _ = AuditEvent.objects.filter(created_at__lt=now() - timedelta(days=days)).delete()
    return deleted
