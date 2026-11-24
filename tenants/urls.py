from django.urls import path

from tenants import views

urlpatterns = [
    path("", views.account, name="account"),
    path("parqueo/", views.switch_parking, name="switch_parking"),
    path("empleados/", views.employees_list, name="employees_list"),
    path("empleados/nuevo/", views.employee_create, name="employee_create"),
    path("empleados/<int:pk>/", views.employee_edit, name="employee_edit"),
    path("empleados/<int:pk>/acceso/", views.employee_toggle_access, name="employee_toggle_access"),
    path("empleados/<int:pk>/contrasena/", views.employee_reset_password, name="employee_reset_password"),
]
