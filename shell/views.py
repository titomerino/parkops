from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from .forms import LoginForm
from parking.views import get_daily_income, get_today_entries_count
import logging
from bathrooms.models import BathroomEntry
from parking.models import PlatePolicy

logger = logging.getLogger(__name__)

@login_required(login_url='login')
def dashboard(request):
    """Panel principal del sistema"""

    #Parking income and entries
    try:
        income = get_daily_income()  # Llamada a la función
        total_daily_income = income.get("total_daily_income", 0)
        total_monthly_income = income.get("total_monthly_income", 0)
        today_count = get_today_entries_count()
    except Exception as e:
        # Registrar el error en el log
        logger.error(f"Error al calcular ingresos: {e}")
        
        total_daily_income = 0
        total_monthly_income = 0

    # Parking suscripciones mensuales
    try:
        total_subscriptions_month_income = PlatePolicy.objects.month_income()
        total_active_subscriptions = PlatePolicy.objects.total_active_monthly_subscriptions()
    except Exception as e:
        logger.error(f"Error al calcular ingresos de suscripciones: {e}")

    # Bathroom income
    try:
        daily_bathroom_income = BathroomEntry.objects.today_income()
        monthly_bathroom_income = BathroomEntry.objects.month_income()
        today_total_count = BathroomEntry.objects.total_today()
    except Exception as e:
        logger.error(f"Error al calcular ingresos de baños: {e}")
        daily_bathroom_income = 0
        monthly_bathroom_income = 0
        today_total_count = 0

    context = {
        "total_daily_income": total_daily_income,
        "total_monthly_income": total_monthly_income,
        "total_today_count_entries": today_count,
        "daily_bathroom_income": daily_bathroom_income,
        "monthly_bathroom_income": monthly_bathroom_income,
        "today_total_count": today_total_count,
        "total_subscriptions_month_income": total_subscriptions_month_income,
        "total_active_subscriptions": total_active_subscriptions,
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
