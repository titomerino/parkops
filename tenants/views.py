from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from shell.decorators import superuser_required
from shell.utils import safe_redirect_url
from tenants.middleware import SESSION_KEY
from tenants.models import Parking


@require_POST
@superuser_required
def switch_parking(request):
    """El superusuario elige con qué parqueo trabajar (se guarda en la sesión)."""

    parking = get_object_or_404(Parking, pk=request.POST.get("parking_id"))
    request.session[SESSION_KEY] = parking.pk

    messages.success(request, f"Ahora trabajas en: {parking.name}")

    # Volver a la página donde estaba, salvo vistas de un registro de otro parqueo
    return redirect(safe_redirect_url(request, request.POST.get("next")) or "dashboard")
