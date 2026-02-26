from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now, localtime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.db.models import Sum, Count

from .models import  Entry, PlatePolicy
from bathrooms.models import BathroomEntry
from .forms import EntryForm, PlateSearchForm, EntryExitForm, PlatePolicyForm
from parking.utils import minutes_to_hours_and_minutes
import weasyprint


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

            try:
                entry.save()
                messages.success(
                    request,
                    f"La entrada para {entry.plate} se guardó correctamente."
                )
            except ValueError as e:
                messages.error(request, str(e))
            
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

@login_required(login_url='login')
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
    )

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
        "today": today
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


def income_day_report(date):

    day = date

    entries = (
        Entry.objects
        .entries_today(day)
        .select_related("fee")
        .only(
            "plate",
            "entry_date_hour",
            "departure_date_hour",
            "fee",
            "state"
        )
    )

    plates = entries.values_list("plate", flat=True).distinct()

    policies = (
        PlatePolicy.objects
        .filter(plate__in=plates, active=True)
        .only("plate", "billing_type", "amount")
    )

    policy_map = {p.plate: p for p in policies}

    total_income = 0
    daily_subscription_count = 0
    normal_fee_count = 0
    total_income_normal = 0
    total_income_daily = 0

    for e in entries:

        policy = policy_map.get(e.plate)

        if e.departure_date_hour:
            minutes, amount = e.calculate_amount(policy=policy)
            total_income += amount
        else:
            minutes, amount = 0, 0

        e.hours, e.minutes = minutes_to_hours_and_minutes(minutes)
        e.amount = amount

        if policy and policy.billing_type == "DAILY":
            daily_subscription_count += 1
            total_income_daily += amount
            e.type = "Suscripción - DIARIO"

        elif policy and policy.billing_type == "MONTHLY":
            e.type = "Suscripción - MENSUAL"

        else:
            normal_fee_count += 1
            total_income_normal += amount
            e.type = "Tarifa"

    bathroom_data = (
        BathroomEntry.objects
        .filter(entry_date_hour__date=day)
        .aggregate(
            total_income=Sum("fee__amount"),
            total_uses=Count("id")
        )
    )

    total_use_bathroom = BathroomEntry.objects.total_today()
    bathroom_income = float(bathroom_data["total_income"] or 0)

    html_string = render_to_string(
        "parking/reports/parking_income_day_pdf.html",
        {
            "entries": entries,
            "total_income": total_income,
            "today": day,
            "daily_count": daily_subscription_count,
            "normal_count": normal_fee_count,
            "total_income_normal": total_income_normal,
            "total_income_daily": total_income_daily,
            "total_use_bathroom": total_use_bathroom,
            "total_income_bathroom": bathroom_income,
            "total_income_today": total_income + bathroom_income,
        }
    )

    pdf = weasyprint.HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="Parqueo-Reporte_de_ingresos_{day}.pdf"'
    )

    return response

@login_required(login_url='login')
def income_today_report(request):
    """LLama a la función de generación de reporte de ingresos del día actual"""
    today = localtime(now()).date()
    return income_day_report(today)
