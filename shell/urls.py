from django.urls import path
from landing.views import home
from . import views

urlpatterns = [
    # Panel si hay sesión; si no, la página de ParkOps
    path('', home, name='dashboard'),
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
]
