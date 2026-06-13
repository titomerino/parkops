from collections import defaultdict
from unittest import case

from django.utils.timezone import localtime, now

from parking.models import Entry, PlatePolicy
from parking.utils import minutes_to_hours_and_minutes


def _get_policy_map(entries):

    plates = entries.values_list(
        "plate",
        flat=True
    ).distinct()

    policies = (
        PlatePolicy.objects
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

def _prepare_entry(entry):

    hours, mins = minutes_to_hours_and_minutes(entry.final_minutes)

    entry.duration = f"{hours:02}:{mins:02}"

    return entry


def generate_day_report(report_date):

    entries = Entry.objects.custom_report(report_date)

    policy_map = _get_policy_map(entries)

    stats = defaultdict(int)

    for entry in entries:

        policy = policy_map.get(entry.plate)

        _prepare_entry(entry)

        stats["total_income"] += entry.final_amount

        if policy:

            if policy.billing_type == "DAILY":

                entry.type = "Suscripción - DIARIO"

                stats["daily_count"] += 1
                stats["total_income_daily"] += entry.final_amount

            elif policy.billing_type == "MONTHLY":

                entry.type = "Suscripción - MENSUAL"

                stats["monthly_count"] += 1

        else:

            entry.type = "Tarifa"

            stats["normal_count"] += 1
            stats["total_income_normal"] += entry.final_amount

    return {
        "is_day_report": True,
        "date": report_date.strftime('%d/%m/%Y'),
        "entries": entries,
        "today": localtime(now()).date(),
        "total_income": stats["total_income"],
        "summary": _build_summary(stats),
    }

def generate_month_report(date):
    
    entries = Entry.objects.custom_report(month_date=date)

    policy_map = _get_policy_map(entries)

    stats = defaultdict(int)

    for entry in entries:

        policy = policy_map.get(entry.plate)

        _prepare_entry(entry)

        stats["total_income"] += entry.final_amount

        if policy:

            if policy.billing_type == "DAILY":

                entry.type = "Suscripción - DIARIO"

                stats["daily_count"] += 1
                stats["total_income_daily"] += entry.final_amount

            elif policy.billing_type == "MONTHLY":

                entry.type = "Suscripción - MENSUAL"

                stats["monthly_count"] += 1
                stats["total_income_monthly"] += policy.amount
                stats["total_income"] += policy.amount

        else:

            entry.type = "Tarifa"

            stats["normal_count"] += 1
            stats["total_income_normal"] += entry.final_amount


    return {
        "date": date.strftime('%m/%Y'),
        "entries": entries,
        "today": localtime(now()).date(),
        "total_income": stats["total_income"],
        "summary": _build_summary(stats),
    }

def generate_period_report(start_date, end_date):
    
    entries = Entry.objects.custom_report(start_date, end_date)

    policy_map = _get_policy_map(entries)

    stats = defaultdict(int)

    for entry in entries:

        policy = policy_map.get(entry.plate)

        _prepare_entry(entry)

        stats["total_income"] += entry.final_amount

        if policy:

            if policy.billing_type == "DAILY":

                entry.type = "Suscripción - DIARIO"

                stats["daily_count"] += 1
                stats["total_income_daily"] += entry.final_amount

            elif policy.billing_type == "MONTHLY":

                entry.type = "Suscripción - MENSUAL"

                stats["monthly_count"] += 1
                stats["total_income_monthly"] += entry.final_amount

        else:

            entry.type = "Tarifa"

            stats["normal_count"] += 1
            stats["total_income_normal"] += entry.final_amount

    return {
        "start_date": start_date.strftime('%d/%m/%Y'),
        "end_date": end_date.strftime('%d/%m/%Y'),
        "entries": entries,
        "today": localtime(now()).date(),
        "total_income": stats["total_income"],
        "summary": _build_summary(stats),
    }

def generate_plate_report(n_plate, start_date, end_date):

    total_income = 0

    entries = Entry.objects.custom_report(start_date, end_date, n_plate=n_plate)

    policy = PlatePolicy.objects.filter(plate=n_plate, active=True).first()

    match policy.billing_type:
        case "DAILY":
            billing_type = "Suscripción - DIARIO"
        case "MONTHLY":
            billing_type = "Suscripción - MENSUAL"
        case _:
            billing_type = "Tarifa"

    for entry in entries:

        _prepare_entry(entry)

        total_income += entry.final_amount

    summary = [
        {
            "title": "Tipo de contrato",
            "text": billing_type + (f" - ${policy.amount}"),
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
        "today": localtime(now()).date(),
        "total_income": total_income,
        "summary": summary,
    }