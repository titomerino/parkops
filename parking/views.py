from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now, localtime
from django.db.models import Sum
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from math import ceil
import re

from .models import Fee, Entry, Configuration, MonthlyPlate
from .forms import EntryForm, PlateSearchForm, EntryExitForm, MonthlyPlateForm


@login_required(login_url='login')
def register(request, plate=None):
    """Vista que nos lleva a la pantalla de registro de entradas"""

    if not plate:
        messages.error(request, "No se proporcionó ninguna placa para registrar.")
        return redirect('search_plate')

    # Verifica si la placa tiene suscripción activa
    is_monthly = MonthlyPlate.objects.filter(
        plate=plate,
        active=True
    ).exists()

    if request.method == 'POST':
        form = EntryForm(request.POST)

        if is_monthly and 'fee' in form.fields:
            form.fields.pop('fee')

        if form.is_valid():
            entry = form.save(commit=False)

            if is_monthly:
                entry.fee = None

            entry.save()
            messages.success(request, f"La entrada para {entry.plate} se guardó correctamente.")
            return redirect('search_plate')
    else:
        form = EntryForm(initial={'plate': plate})

        if is_monthly and 'fee' in form.fields:
            form.fields.pop('fee')

    return render(request, "parking/register.html", {
        'form': form,
        'plate': plate,
        'is_monthly': is_monthly
    })


@login_required(login_url='login')
def departure(request, pk):
    """ Salida del parqueo """
    entry = get_object_or_404(Entry, pk=pk)

    # Verifica si la placa tiene suscripción activa
    is_monthly = MonthlyPlate.objects.filter(
        plate=entry.plate,
        active=True
    ).exists()

    # ⏱️ Calcula horas y monto usando el modelo
    hours, amount = entry.calculate_amount()

    # Si es mensual, fuerza a cero (doble seguridad)
    if is_monthly:
        amount = 0

    if request.method == 'POST':
        # Guardar salida
        entry.departure_date_hour = now()
        entry.state = False

        # Limpia fee si es mensual
        if is_monthly:
            entry.fee = None

        entry.save()
        messages.success(request, f"La salida para {entry.plate} se guardó correctamente.")
        return_url = request.session.pop('departure_return_url', None)
        print("RETURN URL:", request.session.get('departure_return_url'))
        return redirect(return_url or 'search_plate')

    # Mostrar datos en solo lectura
    form = EntryExitForm(initial={
        'time_spent': f"{hours} horas",
        'total_amount': f"${amount:.2f}"
    })

    # Quita campos si es mensual
    if is_monthly:
        form.fields.pop('total_amount', None)

    return render(request, "parking/departure.html", {
        'entry': entry,
        'form': form,
        'hours': hours,
        'amount': amount,
        'is_monthly': is_monthly
    })


@login_required(login_url='login')
def go_to_departure(request, pk):
    # Página REAL de donde vino el usuario
    return_url = request.META.get('HTTP_REFERER')

    if return_url:
        request.session['departure_return_url'] = return_url

    return redirect('departure', pk)
    

@login_required(login_url='login')
def search_plate(request):
    """Vista principal: buscar placa y decidir flujo"""

    form = PlateSearchForm()

    if request.method == 'POST':
        form = PlateSearchForm(request.POST)

        if form.is_valid():
            plate = form.cleaned_data['plate'].upper()

            entry = Entry.objects.filter(
                plate=plate,
                state=True
            ).first()

            if entry:
                # Existe → salida
                save_return_url(request)
                return redirect('departure', entry.id)
            else:
                # No existe → entrada
                return redirect('register', plate)
            
        else:
            messages.error(
                request,
                "La placa solo puede contener letras, números y espacios"
            )

    return render(request, "parking/search_plate.html", {
        'form': form
    })


@login_required(login_url='login')
def record(request):
    """ Pagina de historial """

    today = localtime(now()).date()

    entries = Entry.objects.filter(
        entry_date_hour__date=today
    ).order_by('-entry_date_hour')

    current_time = now()

    for e in entries:
        end_time = e.departure_date_hour or current_time

        delta = end_time - e.entry_date_hour
        e.hours = ceil(delta.total_seconds() / 3600)

        if e.fee:
            e.amount = e.hours * float(e.fee.amount)
        else:
            e.amount = 0

    return render(request, "parking/record.html", {
        'entries': entries,
        'today': today
    })


@login_required(login_url='login')
def month_plate_list(request):
    """ Página de placas con pago mensual """

    plates = MonthlyPlate.objects.all().order_by(
        '-active',
        'plate'
    )

    return render(request, "parking/month_plate_list.html", {
        'plates': plates
    })


@login_required(login_url='login')
def register_month(request):
    """ Registrar placa con mensualidad """

    if request.method == 'POST':
        form = MonthlyPlateForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Mensualidad registrada correctamente"
            )
            return redirect('month_plate_list')
        else:
            messages.error(
                request,
                "Corrige los errores del formulario"
            )
    else:
        form = MonthlyPlateForm()

    return render(request, "parking/register_monthly.html", {
        'form': form
    })


@login_required(login_url='login')
def edit_month(request, pk):
    """ Editar placa con mensualidad """

    monthly_plate = get_object_or_404(MonthlyPlate, pk=pk)

    if request.method == 'POST':
        form = MonthlyPlateForm(
            request.POST,
            instance=monthly_plate
        )

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Mensualidad actualizada correctamente"
            )
            return redirect('month_plate_list')
        else:
            messages.error(
                request,
                "Corrige los errores del formulario"
            )
    else:
        form = MonthlyPlateForm(instance=monthly_plate)

    return render(request, "parking/register_monthly.html", {
        'form': form,
        'is_edit': True,
        'monthly_plate': monthly_plate
    })


@login_required(login_url='login')
def toggle_month_active(request, pk):
    """ Activa / desactiva una mensualidad y recarga la lista """

    print("METHOD:", request.method)
    plate = get_object_or_404(MonthlyPlate, pk=pk)
    
    if request.method == "POST":
        plate.active = not plate.active
        plate.save()

        if plate.active:
            messages.success(
                request,
                f"La mensualidad de {plate.plate} fue ACTIVADA"
            )
        else:
            messages.warning(
                request,
                f"La mensualidad de {plate.plate} fue DESACTIVADA"
            )

    return redirect('month_plate_list')

## functions ##
def save_return_url(request):
    path = request.get_full_path()
    print("GUARDANDO:", path)
    # Evita guardar la misma vista de departure como retorno
    if not path.startswith("/departure"):
        request.session['departure_return_url'] = path


def get_daily_income():
    """
    Retorna un diccionario con los ingresos del día:
    - total_daily_income: ingresos de entradas normales
    - total_monthly_income: ingresos de suscripciones activas
    """
    today = localtime(now()).date()

    # Entradas normales (no mensuales)
    normal_entries = Entry.objects.filter(
        entry_date_hour__date=today
    ).exclude(
        plate__in=MonthlyPlate.objects.filter(active=True).values_list('plate', flat=True)
    )

    total_daily_income = sum(e.calculate_amount()[1] for e in normal_entries)

    # Ingresos por suscripciones activas
    total_monthly_income = MonthlyPlate.objects.filter(active=True).aggregate(
        total=Sum('monthly_amount')
    )['total'] or 0

    return {
        "total_daily_income": total_daily_income,
        "total_monthly_income": total_monthly_income
    }


def get_today_entries_count():
    """Retorna la cantidad de carros dentro hoy"""
    today = localtime(now()).date()

    return Entry.objects.filter(
        entry_date_hour__date=today
    ).count()