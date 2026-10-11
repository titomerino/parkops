from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from tenants.models import Parking

SESSION_KEY = "parking_id"

# Rutas que no requieren parqueo (login, admin, estáticos)
EXEMPT_PREFIXES = ("/login/", "/logout/", "/admin/", "/static/")


def get_parking_for(request):
    """
    Parqueo con el que trabaja el usuario.
    - Usuario normal: su parqueo (solo uno).
    - Superusuario: el que eligió en la sesión, o el primero.
    """
    user = request.user

    if not user.is_authenticated:
        return None

    if user.is_superuser:
        parking = None
        parking_id = request.session.get(SESSION_KEY)
        if parking_id:
            parking = Parking.objects.filter(pk=parking_id).first()
        return parking or Parking.objects.order_by("pk").first()

    membership = getattr(user, "parking_membership", None)
    return membership.parking if membership else None


class CurrentParkingMiddleware:
    """Define request.parking y bloquea usuarios sin parqueo o con parqueo suspendido."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.parking = get_parking_for(request)

        if request.user.is_authenticated and not request.path.startswith(EXEMPT_PREFIXES):

            if request.user.is_superuser:
                if request.parking is None:
                    messages.warning(request, "Crea un parqueo para empezar.")
                    return redirect("admin:tenants_parking_add")

            elif request.parking is None or not request.parking.active:
                reason = (
                    "Tu usuario no tiene un parqueo asignado."
                    if request.parking is None
                    else "El parqueo está suspendido. Contacta al administrador."
                )
                logout(request)
                messages.error(request, reason)
                return redirect("login")

        return self.get_response(request)
