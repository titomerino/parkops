"""
Factura mensual de un parqueo: mensualidad del plan, IA incluida y usada,
y recargas de IA del mes.
"""
from datetime import timedelta

from django.db import transaction
from django.utils.timezone import localdate, now

from parking.models import PlateScan
from payment.models import Invoice, InvoiceLine, Payment
from payment.services.payment_service import generate_current_month_payments
from tenants.models import AiTopUp

MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def month_label(day):
    return f"{MONTHS[day.month - 1]} {day.year}"


def previous_month(day=None):
    first = (day or localdate()).replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


@transaction.atomic
def generate_invoice(parking, period):
    """
    Crea o vuelve a armar la factura del mes. Se puede regenerar las veces
    que haga falta (p. ej. después de una recarga): conserva su número.
    """
    period = period.replace(day=1)
    label = month_label(period)

    if period == localdate().replace(day=1):
        generate_current_month_payments(parking)

    invoice, _ = Invoice.objects.select_for_update().get_or_create(parking=parking, period=period)
    invoice.lines.all().delete()

    lines = []
    included = 0

    payments = (
        Payment.objects
        .filter(subscription__parking=parking, billing_date__year=period.year, billing_date__month=period.month)
        .select_related("subscription__plan__ai_package")
        .order_by("subscription__name", "pk")
    )
    for payment in payments:
        subscription = payment.subscription
        lines.append(InvoiceLine(
            kind=InvoiceLine.PLAN,
            description=f"{subscription.name} — mensualidad de {label}",
            amount=payment.amount or 0,
            paid=payment.paid,
        ))

        package = subscription.plan.ai_package if subscription.plan_id else None
        if package:
            included += package.scans
            lines.append(InvoiceLine(
                kind=InvoiceLine.AI_INCLUDED,
                description=f"Incluye {package.scans:,} escaneos de placas con IA",
                detail=f"Paquete {package.name}",
                paid=True,
            ))

    top_ups = AiTopUp.objects.filter(parking=parking, month=period).select_related("package").order_by("created_at")
    for top_up in top_ups:
        included += top_up.scans
        lines.append(InvoiceLine(
            kind=InvoiceLine.TOP_UP,
            description=f"Recarga de IA: {top_up.package.name}",
            detail=f"{top_up.scans:,} escaneos · agregada el {top_up.created_at:%d/%m/%Y}",
            amount=top_up.price,
            paid=top_up.paid,
        ))

    used = (
        PlateScan.objects.for_parking(parking)
        .filter(created_at__year=period.year, created_at__month=period.month)
        .count()
    )
    if included or used:
        lines.append(InvoiceLine(
            kind=InvoiceLine.AI_INCLUDED,
            description=f"Uso de IA en {label}",
            detail=f"{used:,} de {included:,} escaneos disponibles",
            paid=True,
        ))

    for line in lines:
        line.invoice = invoice
    InvoiceLine.objects.bulk_create(lines)

    invoice.total = sum(line.amount for line in lines)
    invoice.issued_at = now()
    invoice.save(update_fields=["total", "issued_at"])
    return invoice


def balance_due(invoice):
    return sum(line.amount for line in invoice.lines.all() if not line.paid)
