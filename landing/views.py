import ipaddress
import re
from urllib.parse import quote

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from payment.models import BillingProfile, Plan
from shell.views import dashboard
from tenants.models import AiPackage

from .forms import COUNTRY_CODE, LeadForm

# Solicitudes por IP y hora (frena el spam sin captcha)
LEADS_PER_HOUR = 5
# Escaneos que usa en promedio un carro (fotos repetidas incluidas)
SCANS_PER_CAR = 1.2


def home(request):
    """`/`: el panel si iniciaste sesión; si no, la página de ParkOps."""
    if request.user.is_authenticated:
        return dashboard(request)
    return _render_home(request, LeadForm())


def _render_home(request, form, sent=None, status=200):
    plans = list(
        Plan.objects.filter(active=True, show_on_website=True)
        .select_related("ai_package")
        .order_by("price")
    )
    base = plans[0] if plans else None
    cards = []
    for plan in plans:
        scans = plan.ai_package.scans if plan.ai_package_id else 0
        cards.append({
            "plan": plan,
            "price": int(plan.price) if plan.price == int(plan.price) else plan.price,
            "scans": scans,
            "scans_label": f"{scans:,}",
            # Carros por día que cubre el paquete, redondeado a 5
            "cars_per_day": int(round(scans / 30 / SCANS_PER_CAR / 5) * 5) if scans else 0,
            "is_base": plan is base,
        })

    # Recargas: paquetes de IA que no vienen dentro de un plan
    top_ups = [
        {"scans_label": f"{pkg.scans:,}", "price": pkg.price}
        for pkg in AiPackage.objects.filter(active=True, plans__isnull=True).order_by("price")
    ]

    return render(request, "landing/home.html", {
        "plans": cards,
        "base_plan": base,
        "top_ups": top_ups,
        "form": form,
        "sent": sent,
        "whatsapp_url": _whatsapp_url(),
    }, status=status)


def _whatsapp_url():
    """Enlace a tu WhatsApp (Admin → Datos de facturación → Teléfono)."""
    profile = BillingProfile.objects.filter(pk=1).first()
    digits = re.sub(r"\D", "", profile.phone) if profile else ""
    if not digits:
        return None
    if len(digits) == 8:
        digits = COUNTRY_CODE + digits
    text = quote("Hola, quiero información sobre ParkOps")
    return f"https://wa.me/{digits}?text={text}"


def _client_ip(request):
    # Railway entrega la IP real en X-Forwarded-For
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    for candidate in (forwarded, request.META.get("REMOTE_ADDR", "")):
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


@require_POST
def lead_create(request):
    """Guarda la solicitud de prueba gratis. Responde JSON si se envió con JS."""
    wants_json = request.headers.get("X-Requested-With") == "fetch"
    form = LeadForm(request.POST)

    if form.is_bot():
        # Al bot se le dice que todo salió bien, pero no se guarda nada
        return JsonResponse({"ok": True}) if wants_json else redirect("/?solicitud=enviada#registro")

    ip = _client_ip(request)
    key = f"landing:leads:{ip}"
    if ip and cache.get(key, 0) >= LEADS_PER_HOUR:
        error = "Recibimos varias solicitudes desde tu conexión. Escríbenos por WhatsApp o intenta más tarde."
        if wants_json:
            return JsonResponse({"ok": False, "error": error}, status=429)
        form.add_error(None, error)
        return _render_home(request, form, status=429)

    if not form.is_valid():
        if wants_json:
            errors = {field: errs[0] for field, errs in form.errors.items()}
            return JsonResponse({"ok": False, "errors": errors}, status=400)
        return _render_home(request, form, status=400)

    lead = form.save(commit=False)
    lead.ip = ip
    lead.save()
    if ip:
        cache.set(key, cache.get(key, 0) + 1, 60 * 60)

    if wants_json:
        return JsonResponse({"ok": True, "business": lead.business_name})
    return _render_home(request, LeadForm(), sent=lead.business_name)
