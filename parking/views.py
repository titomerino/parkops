from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now, localtime
from django.db.models import F, ExpressionWrapper, DurationField
from math import ceil

from .models import Fee, Entry, Configuration, MonthlyPlate
from .forms import EntryForm, PlateSearchForm, EntryExitForm


def register(request, plate):
    """Vista que nos lleva a la pantalla de registro de entradas"""

    # Verifica si la placa tiene suscripción activa
    is_monthly = MonthlyPlate.objects.filter(
        plate=plate,
        active=True
    ).exists()

    if request.method == 'POST':
        form = EntryForm(request.POST)

        # Por seguridad: si es mensual, ignora fee aunque venga en POST
        if is_monthly and 'fee' in form.fields:
            form.fields.pop('fee')

        if form.is_valid():
            entry = form.save(commit=False)

            # Limpia fee si es mensual
            if is_monthly:
                entry.fee = None

            entry.save()
            return redirect('search_plate')
    else:
        form = EntryForm(initial={
            'plate': plate
        })

        # Oculta fee si es mensual
        if is_monthly and 'fee' in form.fields:
            form.fields.pop('fee')

    return render(request, "parking/register.html", {
        'form': form,
        'plate': plate,
        'is_monthly': is_monthly
    })


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
        return redirect('search_plate')

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
                return redirect('departure', entry.id)
            else:
                # No existe → entrada
                return redirect('register', plate)

    return render(request, "parking/search_plate.html", {
        'form': form
    })


def record(request):
    """ Pagina de historial """

    today = localtime(now()).date()

    # Traer todas las entradas del día
    entries = Entry.objects.filter(
        entry_date_hour__date=today
    ).order_by('-entry_date_hour')

    # Calcular horas y monto
    current_time = now()

    for e in entries:
        # Usa hora actual si aún no ha salido
        end_time = e.departure_date_hour or current_time

        delta = end_time - e.entry_date_hour
        e.hours = ceil(delta.total_seconds() / 3600)

        # Si no hay tarifa, monto es 0
        if e.fee:
            e.amount = e.hours * float(e.fee.amount)
        else:
            e.amount = 0

    return render(request, "parking/record.html", {
        'entries': entries,
        'today': today
    })