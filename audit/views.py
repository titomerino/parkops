from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.utils.timezone import localdate, localtime

from audit.models import AuditEvent
from shell.decorators import perm_required

PER_PAGE = 50
ICONS = {
    "entries": "bi-car-front-fill text-info",
    "keys": "bi-key-fill text-warning",
    "fees": "bi-cash-coin text-success",
    "subscriptions": "bi-calendar-check text-success",
    "bathrooms": "bi-droplet-fill text-info",
    "employees": "bi-people-fill text-info",
    "sessions": "bi-box-arrow-in-right text-secondary",
}
# Acciones que conviene resaltar al revisar
DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
WARNING_ACTIONS = {"entry_edited", "entry_deleted", "login_failed", "employee_password", "employee_access"}


@perm_required("audit.view_auditevent")
def audit_list(request):
    """Quién hizo qué en el parqueo, con filtros por fecha, usuario, tipo y placa."""
    today = localdate()
    date_from = parse_date(request.GET.get("desde", "")) or today - timedelta(days=6)
    date_to = parse_date(request.GET.get("hasta", "")) or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    username = request.GET.get("usuario", "")
    category = request.GET.get("tipo", "")
    text = request.GET.get("buscar", "").strip()

    base = AuditEvent.objects.filter(parking=request.parking)
    events = base.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    if username:
        events = events.filter(username=username)
    if category in AuditEvent.CATEGORIES:
        events = events.filter(action__in=AuditEvent.CATEGORIES[category][1])
    if text:
        compact = text.replace(" ", "").replace("-", "")
        events = events.filter(Q(target__icontains=compact) | Q(target__icontains=text) | Q(summary__icontains=text))

    page = Paginator(events.order_by("-created_at"), PER_PAGE).get_page(request.GET.get("pagina"))
    for event in page:
        event.local = localtime(event.created_at)
        event.day = f"{DAYS[event.local.weekday()]} {event.local:%d/%m/%Y}"
        event.icon = ICONS.get(event.category, "bi-circle")
        event.warning = event.action in WARNING_ACTIONS

    # Para que los enlaces de página conserven los filtros
    params = request.GET.copy()
    params.pop("pagina", None)

    return render(request, "audit/audit_list.html", {
        "page": page,
        "date_from": date_from,
        "date_to": date_to,
        "username": username,
        "category": category,
        "text": text,
        "usernames": base.exclude(username="").order_by("username").values_list("username", flat=True).distinct(),
        "categories": [(key, label) for key, (label, _) in AuditEvent.CATEGORIES.items()],
        "query": params.urlencode(),
        "filtered": bool(username or category or text or request.GET.get("desde") or request.GET.get("hasta")),
    })
