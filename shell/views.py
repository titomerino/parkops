from django.shortcuts import render
from parking.views import get_daily_income
import logging

logger = logging.getLogger(__name__)

def dashboard(request):
    """Panel principal del sistema"""
    try:
        income = get_daily_income()  # Llamada a la función
        total_daily_income = income.get("total_daily_income", 0)
        total_monthly_income = income.get("total_monthly_income", 0)
    except Exception as e:
        # Registrar el error en el log
        logger.error(f"Error al calcular ingresos: {e}")
        
        total_daily_income = 0
        total_monthly_income = 0

    context = {
        "total_daily_income": total_daily_income,
        "total_monthly_income": total_monthly_income,
    }

    return render(request, "shell/dashboard.html", context)
