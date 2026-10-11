from tenants.models import Parking

# Quién ve el aviso del paquete de IA: el dueño/administrador del parqueo
AI_ALERT_PERMISSION = "parking.view_statistics_entry"


def current_parking(request):
    """Parqueo actual en las plantillas y, para el superusuario, la lista para cambiar."""

    context = {"current_parking": getattr(request, "parking", None)}

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_superuser:
        context["switchable_parkings"] = Parking.objects.order_by("name")

    return context


def ai_scan_alert(request):
    """Aviso cuando el paquete de IA del mes se está acabando o se terminó."""

    parking = getattr(request, "parking", None)
    user = getattr(request, "user", None)

    if parking is None or user is None or not user.is_authenticated:
        return {}
    if not user.has_perm(AI_ALERT_PERMISSION):
        return {}

    from parking.services import plate_scan

    if not plate_scan.is_enabled(parking):
        return {}

    quota = plate_scan.quota(parking)
    if not (quota["exhausted"] or quota["low"]):
        return {}

    return {"ai_scan_alert": quota}
