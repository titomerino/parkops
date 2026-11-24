from django.urls import path

from . import views

urlpatterns = [
    path("solicitud/", views.lead_create, name="lead_create"),
]
