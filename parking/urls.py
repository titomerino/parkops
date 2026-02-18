from .views import (
    register,
    search_plate,
    departure,
    record,
    go_to_departure,
    subscription_plate_list,
    subscription_register,
    subscription_edit,
    toggle_subscription_active,
    income_today_report,
    income_month_report_specific,
    income_month_report_today
)
from django.urls import path

urlpatterns = [
    path("busqueda/", search_plate, name="search_plate"),
    path("registro/<str:plate>", register, name="register"),
    path("salida/<int:pk>", departure, name="departure"),
    path("historial/", record, name="record"),
    path('go-to-departure/<int:pk>/', go_to_departure, name='go_to_departure'),
    path('suscripciones/', subscription_plate_list, name='subscription_plate_list'),
    path('suscripciones/registrar', subscription_register, name='subscription_register'),
    path('suscripciones/<int:pk>', subscription_edit, name='subscription_edit'),
    path('suscripciones/desactivar/<int:pk>', toggle_subscription_active, name='toggle_subscription_active'),
    path('suscripciones/activar/<int:pk>', toggle_subscription_active, name='toggle_subscription_active'),
    path('reporte-de-ingresos-hoy/', income_today_report, name='income_today_report'),
    path('reporte-de-ingresos-mes/', income_month_report_today, name='income_month_report_today'),
    path('reporte-de-ingresos-mes/<str:date>/', income_month_report_specific, name='income_month_report'),
]
