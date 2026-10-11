from collections import defaultdict
from decimal import Decimal
from django.utils.timezone import localtime, now

from parking.models import Entry, PlatePolicy
from parking.utils import minutes_to_hours_and_minutes


def _get_policy_map(parking, entries):

    plates = entries.values_list(
        "plate",
        flat=True
    ).distinct()

    policies = (
        PlatePolicy.objects.for_parking(parking)
        .filter(
            plate__in=plates,
            active=True
        )
        .only(
            "plate",
            "billing_type",
            "amount"
        )
    )

    return {
        policy.plate: policy
        for policy in policies
    }

def _build_summary(stats):

    return [
        {
            "title": "Tarifas",
            "count": stats["normal_count"],
            "income": stats["total_income_normal"],
        },
        {
            "title": "Suscripción diaria",
            "count": stats["daily_count"],
            "income": stats["total_income_daily"],
        },
        {
            "title": "Suscripción mensual",
            "count": stats["monthly_count"],
            "income": stats["total_income_monthly"],
        },
    ]

def _entry_type(policy):
    """Tipo de cobro; una política por hora se cobra con la tarifa normal"""

    if policy and policy.billing_type == "DAILY":
        return "Suscripción - DIARIO"

    if policy and policy.billing_type == "MONTHLY":
        return "Suscripción - MENSUAL"

    return "Tarifa"

def _prepare_entry(entry, policy):

    # Entradas sin montos congelados (anteriores a la migración 0011)
    # se calculan al vuelo; no se guardan.
    if entry.final_minutes is None:
        entry.final_minutes, amount = entry.calculate_amount(policy=policy)

        # Entrada aún activa: todavía no hay cobro
        entry.final_amount = (
            Decimal(str(amount)) if entry.departure_date_hour else Decimal("0")
        )

    hours, mins = minutes_to_hours_and_minutes(entry.final_minutes)

    entry.duration = f"{hours:02}:{mins:02}"
    entry.type = _entry_type(policy)

    return entry

# Clave de estadísticas por tipo de cobro (ver _entry_type)
_STATS_KEY = {
    "Tarifa": "normal",
    "Suscripción - DIARIO": "daily",
    "Suscripción - MENSUAL": "monthly",
}

def _summarize(parking, entries):
    """Prepara cada entrada y acumula cantidad e ingresos por tipo de cobro."""

    policy_map = _get_policy_map(parking, entries)

    stats = defaultdict(int)

    for entry in entries:

        _prepare_entry(entry, policy_map.get(entry.plate))

        key = _STATS_KEY[entry.type]

        stats["total_income"] += entry.final_amount
        stats[f"{key}_count"] += 1
        stats[f"total_income_{key}"] += entry.final_amount

    return stats

def _report_context(entries, stats, **extra):

    return {
        **extra,
        "entries": entries,
        "today": localtime(now()),
        "total_income": stats["total_income"],
        "summary": _build_summary(stats),
    }

def generate_day_report(parking, report_date):

    entries = Entry.objects.for_parking(parking).custom_report(report_date)

    return _report_context(
        entries,
        _summarize(parking, entries),
        parking=parking,
        is_day_report=True,
        date=report_date.strftime('%d/%m/%Y'),
    )

def generate_month_report(parking, date):

    entries = Entry.objects.for_parking(parking).custom_report(month_date=date)

    stats = _summarize(parking, entries)

    # Cada mensualidad activa se suma una sola vez (igual que el dashboard),
    # no una vez por cada entrada de la placa
    monthly_income = PlatePolicy.objects.for_parking(parking).month_income()

    stats["total_income_monthly"] += monthly_income
    stats["total_income"] += monthly_income

    return _report_context(
        entries,
        stats,
        parking=parking,
        date=date.strftime('%m/%Y'),
    )

def generate_period_report(parking, start_date, end_date):

    entries = Entry.objects.for_parking(parking).custom_report(start_date, end_date)

    return _report_context(
        entries,
        _summarize(parking, entries),
        parking=parking,
        start_date=start_date.strftime('%d/%m/%Y'),
        end_date=end_date.strftime('%d/%m/%Y'),
    )

def generate_plate_report(parking, n_plate, start_date, end_date):

    total_income = 0

    entries = Entry.objects.for_parking(parking).custom_report(start_date, end_date, n_plate=n_plate)

    policy = PlatePolicy.objects.for_parking(parking).filter(plate=n_plate, active=True).first()

    if policy:
        match policy.billing_type:
            case "DAILY":
                billing_type = "Suscripción - DIARIO" + (f" - ${policy.amount}")
            case "MONTHLY":
                billing_type = "Suscripción - MENSUAL" + (f" - ${policy.amount or 0}")
            case _:
                billing_type = "Suscripción - POR HORA (tarifa normal)"
    else:
        billing_type = "Sin suscripción"

    for entry in entries:

        _prepare_entry(entry, policy)

        if entry.type != "Tarifa":
            entry.type = billing_type

        total_income += entry.final_amount

    summary = [
        {
            "title": "Tipo de contrato",
            "text": billing_type,
        },
        {
            "title": "Total de entradas",
            "text": len(entries),
        },
    ]

    return {
        "plate": n_plate,
        "start_date": start_date.strftime('%d/%m/%Y'),
        "end_date": end_date.strftime('%d/%m/%Y'),
        "entries": entries,
        "today": localtime(now()),
        "total_income": total_income,
        "summary": summary,
        "policy": policy,
        "parking": parking,
    }