from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.timezone import now, localtime

from payment.services.payment_service import notify_pending_payments

from .forms import LoginForm
from .utils import safe_redirect_url
import logging
from bathrooms.models import BathroomEntry
from parking.models import Entry, PlatePolicy

logger = logging.getLogger(__name__)

@login_required(login_url='login')
def dashboard(request):
    """Panel principal del sistema"""

    today = localtime(now()).date()
    current_year = today.year
    current_month = today.month

    if request.user.has_perm("parking.view_statistics_entry"):
        notify_pending_payments(request)

    # Todos los totales son del parqueo actual
    entries = Entry.objects.for_parking(request.parking)
    bathroom_entries = BathroomEntry.objects.for_parking(request.parking)
    policies = PlatePolicy.objects.for_parking(request.parking)

    context = {
        "total_daily_income": entries.today_income(today),
        "total_monthly_income": entries.month_income(current_year, current_month),
        "total_today_count_entries": entries.entries_today_count(today),
        "daily_bathroom_income": bathroom_entries.today_income(),
        "monthly_bathroom_income": bathroom_entries.month_income(),
        "today_total_count": bathroom_entries.total_today(),
        "total_subscriptions_month_income": policies.month_income(),
        "total_active_subscriptions": policies.total_active_monthly_subscriptions(),
    }

    return render(request, "shell/dashboard.html", context)

def error_403(request, exception):
    return render(request, 'shell/403.html', status=403)

def error_404(request, exception):
    return render(request, 'shell/404.html', status=404)


def custom_login(request):
    """Login personalizado para usuarios"""
    if request.user.is_authenticated:
        return redirect('dashboard')  # si ya está logueado, va al dashboard

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                messages.success(request, f"Bienvenido {user.username}")
                # Solo se redirige a páginas del propio sitio
                next_url = safe_redirect_url(request, request.GET.get('next'))
                return redirect(next_url or 'dashboard')
            else:
                messages.error(request, "Usuario o contraseña incorrectos")
    else:
        form = LoginForm()

    return render(request, "shell/login.html", {"form": form})


@require_POST
def custom_logout(request):
    """Cerrar sesión del usuario"""
    logout(request)
    messages.success(request, "Sesión cerrada correctamente")
    return redirect('login')
