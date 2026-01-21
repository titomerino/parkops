from django.shortcuts import render

def dashboard(request):
    """Panel principal del sistema"""
    return render(request, "shell/dashboard.html")
