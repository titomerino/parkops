from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.timezone import now, localtime

from .forms import LoginForm
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

    context = {
        "total_daily_income": Entry.objects.today_income(today),
        "total_monthly_income": Entry.objects.month_income(current_year, current_month),
        "total_today_count_entries": Entry.objects.entries_today_count(today),
        "daily_bathroom_income": BathroomEntry.objects.today_income(),
        "monthly_bathroom_income": BathroomEntry.objects.month_income(),
        "today_total_count": BathroomEntry.objects.total_today(),
        "total_subscriptions_month_income": PlatePolicy.objects.month_income(),
        "total_active_subscriptions": PlatePolicy.objects.total_active_monthly_subscriptions(),
    }

    return render(request, "shell/dashboard.html", context)


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
                next_url = request.GET.get('next')  # opcional: redirigir a la página original
                return redirect(next_url if next_url else 'dashboard')
            else:
                messages.error(request, "Usuario o contraseña incorrectos")
    else:
        form = LoginForm()

    return render(request, "shell/login.html", {"form": form})


def custom_logout(request):
    """Cerrar sesión del usuario"""
    logout(request)
    messages.success(request, "Sesión cerrada correctamente")
    return redirect('login')
