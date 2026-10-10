from django.urls import path

from tenants import views

urlpatterns = [
    path("parqueo/", views.switch_parking, name="switch_parking"),
]
