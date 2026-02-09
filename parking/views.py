from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now, localtime
from django.db.models import Sum
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from math import ceil
import re

from .models import Fee, Entry, Configuration, PlatePolicy
from .forms import EntryForm, PlateSearchForm, EntryExitForm, PlatePolicyForm


@login_required(login_url='login')
def register(request, plate=None):
    """Vista que nos lleva a la pantalla de registro de entradas"""

    if not plate:
        messages.error(request, "No se proporcionó ninguna placa para registrar.")
        return redirect('search_plate')

    plate = plate.strip().upper()

    # Buscar política activa para la placa
    policy = PlatePolicy.objects.filter(
        plate=plate,
        active=True
    ).first()

    # Si tiene política y NO es por hora → no debe elegir tarifa
    has_subscription = policy and policy.billing_type in ["MONTHLY", "DAILY"]

    if request.method == 'POST':
        form = EntryForm(request.POST)

        if has_subscription and 'fee' in form.fields:
            form.fields.pop('fee')

        if form.is_valid():
            entry = form.save(commit=False)
            entry.plate = plate  # aseguras formato consistente

            # Si tiene suscripción → no usar tarifa por hora
            if has_subscription:
                entry.fee = None

            entry.save()
            messages.success(
                request,
                f"La entrada para {entry.plate} se guardó correctamente."
            )
            return redirect('search_plate')
    else:
        form = EntryForm(initial={'plate': plate})

        if has_subscription and 'fee' in form.fields:
            form.fields.pop('fee')

    return render(request, "parking/register.html", {
        'form': form,
        'plate': plate,
        'policy': policy,
        'has_subscription': has_subscription
    })


@login_required(login_url='login')
def departure(request, pk):
    """ Salida del parqueo """

    entry = get_object_or_404(Entry, pk=pk)

    plate = entry.plate.strip().upper()

    # Buscar política activa para la placa
    policy = PlatePolicy.objects.filter(
        plate=plate,
        active=True
    ).first()

    billing_type = policy.billing_type if policy else "HOURLY"

    # ⏱️ Calcula horas y monto usando el modelo
    hours, amount = entry.calculate_amount()

    if request.method == 'POST':
        # Guardar salida
        entry.departure_date_hour = now()
        entry.state = False

        # Si NO es por hora → no debe quedar tarifa
        if billing_type in ["MONTHLY", "DAILY"]:
            entry.fee = None

        entry.save()

        # Mensaje según tipo de cobro
        if billing_type == "MONTHLY":
            msg = f"Salida registrada para {entry.plate} (Mensual — $0.00)"
        elif billing_type == "DAILY":
            msg = f"Salida registrada para {entry.plate} (Diario — ${amount:.2f})"
        else:
            msg = f"Salida registrada para {entry.plate} — ${amount:.2f}"

        messages.success(request, msg)

        return_url = request.session.pop('departure_return_url', None)
        return redirect(return_url or 'search_plate')

    # Mostrar datos en solo lectura
    form = EntryExitForm(initial={
        'time_spent': f"{hours} horas",
        'total_amount': f"${amount:.2f}"
    })

    # Quita campo de monto si es mensual
    if billing_type == "MONTHLY":
        form.fields.pop('total_amount', None)

    return render(request, "parking/departure.html", {
        'entry': entry,
        'form': form,
        'hours': hours,
        'amount': amount,
        'policy': policy,
        'billing_type': billing_type,
        'is_monthly': billing_type == "MONTHLY",
        'is_daily': billing_type == "DAILY",
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
    """ Página de historial """

    today = localtime(now()).date()

    entries = Entry.objects.filter(
        entry_date_hour__date=today
    ).order_by('-entry_date_hour')

    for e in entries:
        # Detectar política activa
        policy = PlatePolicy.objects.filter(
            plate=e.plate,
            active=True
        ).first()

        # Tipo de cobro para la UI
        e.billing_type = policy.billing_type if policy else "HOURLY"

        # Usar la lógica centralizada del modelo
        hours, amount = e.calculate_amount()

        e.hours = hours
        e.amount = amount

    return render(request, "parking/record.html", {
        'entries': entries,
        'today': today
    })


@login_required(login_url='login')
def subscription_plate_list(request):
    """ Página de placas con pago subcripcion """

    plates = PlatePolicy.objects.all().order_by(
        '-active',
        'billing_type',
        'plate'
    )

    return render(request, "parking/subscription_plate_list.html", {
        'plates': plates
    })


@login_required(login_url='login')
def subscription_register(request):
    """ Registrar política de cobro para una placa """

    if request.method == 'POST':
        form = PlatePolicyForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Suscripción registrada correctamente"
            )
            return redirect('subscription_plate_list')
        else:
            messages.error(
                request,
                "Corrige los errores del formulario"
            )
    else:
        form = PlatePolicyForm()

    return render(request, "parking/subscription_register.html", {
        'form': form
    })


@login_required(login_url='login')
def subscription_edit(request, pk):
    """ Editar suscripción / política de cobro de una placa """

    policy = get_object_or_404(PlatePolicy, pk=pk)

    if request.method == 'POST':
        form = PlatePolicyForm(
            request.POST,
            instance=policy
        )

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Suscripción actualizada correctamente"
            )
            return redirect('subscription_plate_list')
        else:
            messages.error(
                request,
                "Corrige los errores del formulario"
            )
    else:
        form = PlatePolicyForm(instance=policy)

    return render(request, "parking/subscription_register.html", {
        'form': form,
        'is_edit': True,
        'policy': policy
    })


@login_required(login_url='login')
def toggle_subscription_active(request, pk):
    """ Activa / desactiva una suscripción y recarga la lista """

    policy = get_object_or_404(PlatePolicy, pk=pk)

    if request.method == "POST":
        policy.active = not policy.active
        policy.save()

        if policy.active:
            messages.success(
                request,
                f"La suscripción de {policy.plate} fue ACTIVADA"
            )
        else:
            messages.warning(
                request,
                f"La suscripción de {policy.plate} fue DESACTIVADA"
            )

    return redirect('subscription_plate_list')

## functions ##
def save_return_url(request):
    path = request.get_full_path()
    print("GUARDANDO:", path)
    # Evita guardar la misma vista de departure como retorno
    if not path.startswith("/departure"):
        request.session['departure_return_url'] = path


def get_daily_income():
    """
    Retorna un diccionario con:
    - total_daily_income: ingresos del día (NO se toca)
    - total_monthly_income: ingresos acumulados del mes en curso
      (suscripciones + cobros por salidas)
    """

    today = localtime(now()).date()
    current_month = today.month
    current_year = today.year

    # =========================
    # INGRESOS DEL DÍA (IGUAL)
    # =========================
    entries = Entry.objects.filter(
        entry_date_hour__date=today
    )

    total_daily_income = sum(
        e.calculate_amount()[1]
        for e in entries
    )

    # =========================
    # INGRESOS DEL MES (NUEVO)
    # =========================

    # 🔹 Entradas cobradas este mes (por salida real)
    month_entries = Entry.objects.filter(
        departure_date_hour__year=current_year,
        departure_date_hour__month=current_month
    )

    total_entries_month = sum(
        e.calculate_amount()[1]
        for e in month_entries
    )

    # 🔹 Suscripciones mensuales activas (solo se suman una vez al mes)
    total_subscriptions_month = PlatePolicy.objects.filter(
        billing_type="MONTHLY",
        active=True
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0

    return {
        "total_daily_income": total_daily_income,
        "total_monthly_income": float(total_entries_month) + float(total_subscriptions_month)
    }


def get_today_entries_count():
    """Retorna la cantidad de carros dentro hoy"""
    today = localtime(now()).date()

    return Entry.objects.filter(
            entry_date_hour__date=today
        ).count()