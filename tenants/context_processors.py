from tenants.models import Parking


def current_parking(request):
    """Parqueo actual en las plantillas y, para el superusuario, la lista para cambiar."""

    context = {"current_parking": getattr(request, "parking", None)}

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_superuser:
        context["switchable_parkings"] = Parking.objects.order_by("name")

    return context
