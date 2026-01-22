from django.urls import path
from .views import dashboard
from . import views

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
]
