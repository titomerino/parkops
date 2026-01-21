from rest_framework.routers import DefaultRouter
from .views import register, search_plate, departure, record
from django.urls import path

urlpatterns = [
    path("busqueda/", search_plate, name="search_plate"),
    path("registro/<str:plate>", register, name="register"),
    path("salida/<int:pk>", departure, name="departure"),
    path("historial/", record, name="record"),
]
