from .views import (
    register,
    search_plate,
    departure,
    record,
    go_to_departure,
    month_plate_list,
    register_month,
    edit_month,
    toggle_month_active
)
from django.urls import path

urlpatterns = [
    path("busqueda/", search_plate, name="search_plate"),
    path("registro/<str:plate>", register, name="register"),
    path("salida/<int:pk>", departure, name="departure"),
    path("historial/", record, name="record"),
    path('go-to-departure/<int:pk>/', go_to_departure, name='go_to_departure'),
    path('mensualidades/', month_plate_list, name='month_plate_list'),
    path('mensualidades/registrar', register_month, name='register_month'),
    path('mensualidades/<int:pk>', edit_month, name='edit_month'),
    path('mensualidades/desactivar/<int:pk>', toggle_month_active, name='toggle_month_active'),
    path('mensualidades/activar/<int:pk>', toggle_month_active, name='toggle_month_active'),
]
