from .views import (
    register,
    search_plate,
    departure,
    record,
    go_to_departure
)
from django.urls import path

urlpatterns = [
    path("busqueda/", search_plate, name="search_plate"),
    path("registro/<str:plate>", register, name="register"),
    path("salida/<int:pk>", departure, name="departure"),
    path("historial/", record, name="record"),
    path('go-to-departure/<int:pk>/', go_to_departure, name='go_to_departure'),
]
