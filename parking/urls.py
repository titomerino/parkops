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
    fee_list,
    fee_register,
    fee_edit
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

    # Fee URLs
    path('tarifas/registrar/', fee_register, name='fee_register'),
    path('tarifas/<int:pk>/editar/', fee_edit, name='fee_edit'),
    path('tarifas/', fee_list, name='fee_list'),
    path('tarifas/registrar/', fee_register, name='fee_register'),
    path('tarifas/<int:pk>/editar/', fee_edit, name='fee_edit'),

]
