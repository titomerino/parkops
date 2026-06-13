from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now, localtime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.contrib.auth.decorators import permission_required

import qrcode, base64
from io import BytesIO
from parking.services.report_service import (
    generate_day_report, generate_month_report,
    generate_period_report,
    generate_plate_report
)

from .models import  Entry, PlatePolicy, Range
from .forms import (
    EntryForm, 
    EntryEditForm, 
    PlateSearchForm, 
    EntryExitForm, 
    PlatePolicyForm, 
    ReportFilterByDayForm,
    ReportFilterByMonthForm,
    ReportFilterByPeriodForm,
    ReportFilterByPlateForm
)
from parking.utils import minutes_to_hours_and_minutes, render_pdf_response


@permission_required('parking.add_entry', raise_exception=True)
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

            try:
                entry.save()
                messages.success(
                    request,
                    f"La entrada para {entry.plate} se guardó correctamente."
                )
            except ValueError as e:
                messages.error(request, str(e))

            # 🔥 AQUÍ LA MAGIA
            action = request.POST.get('action')

            if action == 'save_print':
                # redirige a la vista de impresión
                return redirect(f"/parking/busqueda/?entry_id={entry.id}")
            
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

@permission_required('parking.add_entry', raise_exception=True)
def departure(request, pk):
    """ Salida del parqueo """

    entry = get_object_or_404(
        Entry.objects.select_related("fee"),
        pk=pk
    )

    plate = entry.plate.strip().upper()

    policy = (
        PlatePolicy.objects
        .filter(plate=plate, active=True)
        .only("billing_type", "amount")
        .first()
    )

    billing_type = policy.billing_type if policy else "HOURLY"

    total_minutes, amount = entry.calculate_amount(policy=policy)
    hours, minutes = minutes_to_hours_and_minutes(total_minutes)

    if request.method == "POST":

        entry.departure_date_hour = now()
        entry.state = False

        # 🔒 Congelar valores históricos
        entry.final_minutes = total_minutes
        entry.final_amount = amount

        # Si es mensual o diario, ya no depende de fee
        if billing_type in ["MONTHLY", "DAILY"]:
            entry.fee_id = None

        entry.save(update_fields=[
            "departure_date_hour",
            "state",
            "final_minutes",
            "final_amount",
            "fee"
        ])

        if billing_type == "MONTHLY":
            msg = f"Salida registrada para {entry.plate} (Mensual — $0.00)"
        elif billing_type == "DAILY":
            msg = f"Salida registrada para {entry.plate} (Diario — ${amount:.2f})"
        else:
            msg = f"Salida registrada para {entry.plate} — ${amount:.2f}"

        messages.success(request, msg)

        return_url = request.session.pop("departure_return_url", None)
        return redirect(return_url or "search_plate")

    form = EntryExitForm(initial={
        "time_spent": f"{hours}:{minutes} h",
        "total_amount": f"${amount:.2f}"
    })

    if billing_type == "MONTHLY":
        form.fields.pop("total_amount", None)

    return render(request, "parking/departure.html", {
        "entry": entry,
        "form": form,
        "hours": f"{hours}:{minutes}",
        "amount": amount,
        "policy": policy,
        "billing_type": billing_type,
        "is_monthly": billing_type == "MONTHLY",
        "is_daily": billing_type == "DAILY",
    })

@login_required(login_url='login')
def go_to_departure(request, pk):
    # Página REAL de donde vino el usuario
    return_url = request.META.get('HTTP_REFERER')

    if return_url:
        request.session['departure_return_url'] = return_url

    return redirect('departure', pk)

@permission_required('parking.change_entry', raise_exception=True)
def entry_edit_view(request, pk):
    """ Vista para editar una entrada (solo admin) """

    entry = get_object_or_404(Entry, pk=pk)
    policy = PlatePolicy.objects.filter(plate=entry.plate, active=True).first()

    if request.method == "POST":
        form = EntryEditForm(request.POST, instance=entry)

        if form.is_valid():
            instance = form.save(commit=False)

            # Si se ingresó fecha de salida → marcar como salida y calcular monto
            if form.cleaned_data.get('departure_date_hour'):
                instance.state = False
                instance.final_amount = instance.calculate_amount()[1]
            else:
                instance.state = True
                instance.final_amount = None

            instance.save()

            messages.success(request, "Entrada actualizada correctamente.")
            return redirect('record')
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = EntryEditForm(instance=entry)

    return render(request, "parking/entry_edit_form.html", {
        "form": form,
        "entry": entry,
        "policy": policy
    })

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
            error_message = form.errors.get('plate')
            
            if error_message:
                messages.error(request, error_message[0])
            else:
                messages.error(request, "Formulario inválido")

    return render(request, "parking/search_plate.html", {
        'form': form
    })

@permission_required('parking.view_entry', raise_exception=True)
def record(request):

    today = localtime(now()).date()

    entries = (
        Entry.objects
        .entries_today_and_active(today)
        .select_related("fee")
        .only(
            "plate",
            "entry_date_hour",
            "departure_date_hour",
            "fee",
            "state"
        )
        .order_by("-state", "-entry_date_hour")
    )

    # Contadores para los chips
    total_entries = entries.count()
    active_entries = entries.filter(state=True).count()
    finished_entries = entries.filter(state=False).count()

    plates = entries.values_list("plate", flat=True)

    policies = (
        PlatePolicy.objects
        .filter(plate__in=plates, active=True)
        .only("plate", "billing_type", "amount")
    )

    policy_dict = {p.plate: p for p in policies}

    for e in entries:
        policy = policy_dict.get(e.plate)

        e.billing_type = policy.billing_type if policy else "HOURLY"

        minutes, amount = e.calculate_amount(policy=policy)
        e.hours, e.minutes = minutes_to_hours_and_minutes(minutes)
        e.amount = amount

    return render(request, "parking/record.html", {
        "entries": entries,
        "today": today,
        "total_entries": total_entries,
        "active_entries": active_entries,
        "finished_entries": finished_entries,
    })

@permission_required('parking.view_platepolicy', raise_exception=True)
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

@permission_required('parking.add_platepolicy', raise_exception=True)
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

@permission_required('parking.change_platepolicy', raise_exception=True)
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

@permission_required('parking.change_platepolicy', raise_exception=True)
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

@login_required(login_url='login')
def imprimir_ticket(request):
    entry_id = request.GET.get('entry_id')
    entry = Entry.objects.get(id=entry_id)

    qr_data = f"entry_id={entry.id}"

    qr = qrcode.make(qr_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    # 🔥 Buscar suscripción activa
    policy = PlatePolicy.objects.filter(
        plate=entry.plate,
        active=True
    ).first()

    # 🔥 Determinar qué mostrar como costo
    if policy:
        if policy.billing_type == "MONTHLY":
            costo = "Suscripción mensual activa"
        elif policy.billing_type == "DAILY":
            costo = f"Suscripción diaria (${policy.amount})"
        else:
            costo = "Suscripción activa"
    else:
        # 🔥 usar tarifa por rango
        first_range = Range.objects.filter(fee=entry.fee).order_by('start_minute').first()
        costo = f"${first_range.amount}" if first_range else "0.00"

    context = {
        'placa': entry.plate,
        'fecha_llegada': localtime(entry.entry_date_hour).strftime('%d/%m/%Y'),
        'hora_llegada': localtime(entry.entry_date_hour).strftime('%I:%M %p'),
        'costo_hora': costo,
        'qr_code': qr_base64,
        'policy': policy  # 🔥 opcional para usar en template
    }

    return render(request, 'parking/ticket-template.html', context)

@permission_required('parking.view_statistics_entry', raise_exception=True)
def parking_generate_reports_form(request):

    context = {
        "formDay": ReportFilterByDayForm(),
        "formMonth": ReportFilterByMonthForm(),
        "formPeriod": ReportFilterByPeriodForm(),
        "formPlate": ReportFilterByPlateForm(),
    }

    return render(
        request,
        "parking/generate_report_form.html",
        context
    )

@permission_required('parking.view_statistics_entry', raise_exception=True)
def report_day_pdf(request):

    form = ReportFilterByDayForm(request.GET)

    if not form.is_valid():
        messages.error(request, "Fecha inválida para el reporte")
        return redirect("parking_reports")

    report_date = form.cleaned_data["date"]

    context = generate_day_report(report_date)

    return render_pdf_response(
        request,
        "parking/reports/parking_day_report_pdf.html",
        context,
        f"reporte-dia-{report_date}.pdf"
    )

@permission_required('parking.view_statistics_entry', raise_exception=True)
def report_month_pdf(request):
    
    form = ReportFilterByMonthForm(request.GET)

    if not form.is_valid():
        return HttpResponseBadRequest("Formulario inválido")

    month = form.cleaned_data["month_date"]

    context = generate_month_report(month)

    return render_pdf_response(
        request,
        "parking/reports/parking_month_report_pdf.html",
        context,
        f"reporte-mes-{month}.pdf"
    )

@permission_required('parking.view_statistics_entry', raise_exception=True)
def report_period_pdf(request):
    
    form = ReportFilterByPeriodForm(request.GET)

    if not form.is_valid():
        return HttpResponseBadRequest("Formulario inválido")
    
    start_date = form.cleaned_data["period_start_date"]
    end_date = form.cleaned_data["period_end_date"]

    context = generate_period_report(start_date, end_date)

    return render_pdf_response(
        request,
        "parking/reports/parking_period_report_pdf.html",
        context,
        f"reporte-periodo-{start_date}-{end_date}.pdf"
    )

@permission_required('parking.view_statistics_entry', raise_exception=True)
def report_plate_pdf(request):

    form = ReportFilterByPlateForm(request.GET)

    if not form.is_valid():
        return HttpResponseBadRequest("Formulario inválido")
    
    plate = form.cleaned_data["plate"].strip().upper()
    start_date = form.cleaned_data["start_date"]
    end_date = form.cleaned_data["end_date"]

    context = generate_plate_report(plate, start_date, end_date)

    return render_pdf_response(
        request,
        "parking/reports/parking_plate_report_pdf.html",
        context,
        f"reporte-placa-{plate}.pdf"
    )
