from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now, localtime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.models import DELETION, LogEntry
from shell.decorators import perm_required
from shell.utils import safe_redirect_url
from django.core.cache import cache
from django.db import transaction
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST
from io import BytesIO
import json

import qrcode, base64

from payment.services.payment_service import notify_pending_payments

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
from parking.utils import (
    minutes_to_hours_and_minutes, format_plate,
    render_pdf_response, export_report_excel
)
from parking.services import plate_scan
from parking.services.voice_plate import interpret
from parking.services.report_service import (
    generate_day_report, generate_month_report,
    generate_period_report,
    generate_plate_report
)


@perm_required('parking.add_entry')
def register(request, plate=None):
    """Vista que nos lleva a la pantalla de registro de entradas"""

    if not plate:
        messages.error(request, "No se proporcionó ninguna placa para registrar.")
        return redirect('search_plate')

    plate = plate.strip().upper()

    # Buscar política activa para la placa
    policy = PlatePolicy.objects.for_parking(request.parking).filter(
        plate=plate,
        active=True
    ).first()

    # Si tiene política y NO es por hora → no debe elegir tarifa
    has_subscription = policy and policy.billing_type in ["MONTHLY", "DAILY"]

    if request.method == 'POST':
        form = EntryForm(request.POST, parking=request.parking)

        if has_subscription and 'fee' in form.fields:
            form.fields.pop('fee')

        if form.is_valid():
            entry = form.save(commit=False)
            entry.parking = request.parking
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

            action = request.POST.get('action')

            if action == 'save_print':
                # redirige a la vista de impresión
                return redirect(f"/parking/busqueda/?entry_id={entry.id}")
            
            return redirect('search_plate')
    else:
        form = EntryForm(initial={'plate': plate}, parking=request.parking)

        if has_subscription and 'fee' in form.fields:
            form.fields.pop('fee')

    return render(request, "parking/register.html", {
        'form': form,
        'plate': plate,
        'policy': policy,
        'has_subscription': has_subscription
    })

@perm_required('parking.add_entry')
def departure(request, pk):
    """ Salida del parqueo """

    entry = get_object_or_404(
        Entry.objects.for_parking(request.parking).select_related("fee"),
        pk=pk
    )

    if not entry.state:
        return _departure_already_registered(request, entry)

    plate = entry.plate.strip().upper()

    policy = (
        PlatePolicy.objects.for_parking(request.parking)
        .filter(plate=plate, active=True)
        .only("billing_type", "amount")
        .first()
    )

    billing_type = policy.billing_type if policy else "HOURLY"

    total_minutes, amount = entry.calculate_amount(policy=policy)
    hours, minutes = minutes_to_hours_and_minutes(total_minutes)

    if request.method == "POST":

        with transaction.atomic():
            # Bloquea la fila: un doble envío no registra dos salidas
            entry = Entry.objects.for_parking(request.parking).select_for_update().get(pk=pk)

            if not entry.state:
                return _departure_already_registered(request, entry)

            entry.departure_date_hour = now()

            # Si es mensual o diario, ya no depende de fee
            if billing_type in ["MONTHLY", "DAILY"]:
                entry.fee_id = None

            # save() congela final_minutes y final_amount al cambiar la salida
            entry.save()

        amount = entry.final_amount

        if billing_type == "MONTHLY":
            msg = f"Salida registrada para {entry.plate} (Mensual — $0.00)"
        elif billing_type == "DAILY":
            msg = f"Salida registrada para {entry.plate} (Diario — ${amount:.2f})"
        else:
            msg = f"Salida registrada para {entry.plate} — ${amount:.2f}"

        messages.success(request, msg)

        return_url = safe_redirect_url(
            request,
            request.session.pop("departure_return_url", None)
        )
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

def _departure_already_registered(request, entry):
    departure = localtime(entry.departure_date_hour).strftime("%d/%m/%Y %I:%M %p")
    messages.warning(
        request,
        f"La entrada de {entry.plate} ya tiene salida registrada ({departure})."
    )
    return redirect("search_plate")

@login_required(login_url='login')
def go_to_departure(request, pk):
    # Página REAL de donde vino el usuario
    return_url = safe_redirect_url(request, request.META.get('HTTP_REFERER'))

    if return_url:
        request.session['departure_return_url'] = return_url

    return redirect('departure', pk)

@perm_required('parking.change_entry')
def entry_edit_view(request, pk):
    """ Vista para editar una entrada (solo admin) """

    entry = get_object_or_404(Entry, pk=pk, parking=request.parking)
    policy = PlatePolicy.objects.for_parking(request.parking).filter(plate=entry.plate, active=True).first()

    if request.method == "POST":
        form = EntryEditForm(request.POST, instance=entry, parking=request.parking)

        if form.is_valid():
            form.save()

            messages.success(request, "Entrada actualizada correctamente.")
            return redirect('record')
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = EntryEditForm(instance=entry, parking=request.parking)

    return render(request, "parking/entry_edit_form.html", {
        "form": form,
        "entry": entry,
        "policy": policy
    })

@require_POST
@perm_required("parking.delete_entry")
def entry_delete_view(request, pk):
    """ Elimina una entrada (permiso «Can delete Entrada») y deja registro en el historial del admin """

    entry = get_object_or_404(Entry, pk=pk, parking=request.parking)

    def fmt(value):
        return localtime(value).strftime("%d/%m/%Y %I:%M %p") if value else "sin salida"

    detail = (
        f"Placa {entry.plate} | entrada {fmt(entry.entry_date_hour)} | "
        f"salida {fmt(entry.departure_date_hour)} | monto ${entry.final_amount or 0}"
    )

    # Queda en Admin → Acciones recientes / historial con usuario y fecha
    LogEntry.objects.log_actions(
        user_id=request.user.pk,
        queryset=[entry],
        action_flag=DELETION,
        change_message=f"Eliminada desde la app. {detail}",
        single_object=True,
    )

    entry.delete()

    messages.success(request, f"Entrada eliminada: {detail}")
    return redirect('record')

@login_required(login_url='login')
def search_plate(request):
    """Vista principal: buscar placa y decidir flujo"""

    if request.user.has_perm("parking.view_statistics_entry"):
        notify_pending_payments(request)

    form = PlateSearchForm()

    if request.method == 'POST':
        form = PlateSearchForm(request.POST)

        if form.is_valid():
            plate = form.cleaned_data['plate'].upper()

            entry = Entry.objects.for_parking(request.parking).filter(
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
        'form': form,
        'plate_scan': plate_scan_button(request.parking),
    })

@perm_required('parking.view_entry')
def record(request):

    if request.user.has_perm("parking.view_statistics_entry"):
        notify_pending_payments(request)

    today = localtime(now()).date()

    entries = list(
        Entry.objects.for_parking(request.parking)
        .entries_today_and_active(today)
        .select_related("fee")
        .prefetch_related("fee__ranges")
        .only(
            "plate",
            "entry_date_hour",
            "departure_date_hour",
            "fee",
            "state",
            "final_minutes",
            "final_amount"
        )
        .order_by("-state", "-entry_date_hour")
    )

    # Contadores para los chips
    total_entries = len(entries)
    active_entries = sum(1 for e in entries if e.state)
    finished_entries = total_entries - active_entries

    policies = (
        PlatePolicy.objects.for_parking(request.parking)
        .filter(plate__in={e.plate for e in entries}, active=True)
        .only("plate", "billing_type", "amount")
    )

    policy_dict = {p.plate: p for p in policies}

    for e in entries:
        policy = policy_dict.get(e.plate)

        e.billing_type = policy.billing_type if policy else "HOURLY"

        if e.state or e.final_minutes is None:
            minutes, amount = e.calculate_amount(policy=policy)
        else:
            # Salida registrada: se muestra lo que se cobró, no un recálculo
            minutes, amount = e.final_minutes, e.final_amount

        e.hours, e.minutes = minutes_to_hours_and_minutes(minutes)
        e.amount = amount

    return render(request, "parking/record.html", {
        "entries": entries,
        "today": today,
        "total_entries": total_entries,
        "active_entries": active_entries,
        "finished_entries": finished_entries,
    })

@perm_required('parking.view_platepolicy')
def subscription_plate_list(request):
    """ Página de placas con pago subcripcion """

    plates = PlatePolicy.objects.for_parking(request.parking).order_by(
        '-active',
        'billing_type',
        'plate'
    )

    return render(request, "parking/subscription_plate_list.html", {
        'plates': plates
    })

@perm_required('parking.add_platepolicy')
def subscription_register(request):
    """ Registrar política de cobro para una placa """

    if request.method == 'POST':
        form = PlatePolicyForm(request.POST, parking=request.parking)

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
        form = PlatePolicyForm(parking=request.parking)

    return render(request, "parking/subscription_register.html", {
        'form': form
    })

@perm_required('parking.change_platepolicy')
def subscription_edit(request, pk):
    """ Editar suscripción / política de cobro de una placa """

    policy = get_object_or_404(PlatePolicy, pk=pk, parking=request.parking)

    if request.method == 'POST':
        form = PlatePolicyForm(
            request.POST,
            instance=policy,
            parking=request.parking
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
        form = PlatePolicyForm(instance=policy, parking=request.parking)

    return render(request, "parking/subscription_register.html", {
        'form': form,
        'is_edit': True,
        'policy': policy
    })

@perm_required('parking.change_platepolicy')
def toggle_subscription_active(request, pk):
    """ Activa / desactiva una suscripción y recarga la lista """

    policy = get_object_or_404(PlatePolicy, pk=pk, parking=request.parking)

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
    # Solo se llama desde la búsqueda: al terminar la salida se vuelve aquí
    request.session['departure_return_url'] = request.get_full_path()

@perm_required('parking.add_entry')
def imprimir_ticket(request):
    entry_id = request.GET.get('entry_id', '')

    if not entry_id.isdigit():
        raise Http404("Ticket no encontrado")

    entry = get_object_or_404(Entry, pk=entry_id, parking=request.parking)

    qr_data = f"entry_id={entry.id}"

    qr = qrcode.make(qr_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    # 🔥 Buscar suscripción activa
    policy = PlatePolicy.objects.for_parking(request.parking).filter(
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
        'policy': policy,  # 🔥 opcional para usar en template
        'parking': request.parking,
    }

    return render(request, 'parking/ticket-template.html', context)

@perm_required('parking.view_statistics_entry')
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

@perm_required('parking.view_statistics_entry')
def report_day(request):

    form = ReportFilterByDayForm(request.GET)

    if not form.is_valid():
        messages.error(request, "Formulario inválido para el reporte")
        return redirect("parking_reports")

    report_date = form.cleaned_data["date"]

    context = generate_day_report(request.parking, report_date)

    match request.GET.get("format"):
        case "pdf":

            return render_pdf_response(
                request,
                "parking/reports/parking_day_report_pdf.html",
                context,
                f"reporte-dia-{report_date}.pdf"
            )
        
        case "xlsx":

            return export_report_excel(
                context,
                report_date,
                type="day"
            )
        
        case _:
            messages.error(request, "Formato no soportado para el reporte")
            return redirect("parking_reports")
    
@perm_required('parking.view_statistics_entry')
def report_month(request):
    
    form = ReportFilterByMonthForm(request.GET)

    if not form.is_valid():
        messages.error(request, "Formulario inválido para el reporte")
        return redirect("parking_reports")

    month = form.cleaned_data["month_date"]

    context = generate_month_report(request.parking, month)

    match request.GET.get("format"):
        case "pdf":

            return render_pdf_response(
                request,
                "parking/reports/parking_month_report_pdf.html",
                context,
                f"reporte-mes-{month}.pdf"
            )
        
        case "xlsx":

            return export_report_excel(
                context,
                month,
                type="monthly"
            )
        
        case _:
            messages.error(request, "Formato no soportado para el reporte")
            return redirect("parking_reports")

@perm_required('parking.view_statistics_entry')
def report_period(request):
    
    form = ReportFilterByPeriodForm(request.GET)

    if not form.is_valid():
        messages.error(request, "Formulario inválido para el reporte")
        return redirect("parking_reports")
    
    start_date = form.cleaned_data["period_start_date"]
    end_date = form.cleaned_data["period_end_date"]

    context = generate_period_report(request.parking, start_date, end_date)

    match request.GET.get("format"):
        case "pdf":

            return render_pdf_response(
                request,
                "parking/reports/parking_period_report_pdf.html",
                context,
                f"reporte-periodo-{start_date}-{end_date}.pdf"
            )
        
        case "xlsx":

            return export_report_excel(
                context,
                start_date,
                end_date,
                "period"
            )
        
        case _:
            messages.error(request, "Formato no soportado para el reporte")
            return redirect("parking_reports")

@perm_required('parking.view_statistics_entry')
def report_plate(request):

    form = ReportFilterByPlateForm(request.GET)

    if not form.is_valid():
        messages.error(request, "Formulario inválido para el reporte")
        return redirect("parking_reports")
    
    plate = form.cleaned_data["plate"].strip().upper()

    exists = Entry.objects.for_parking(request.parking).filter(plate=plate).exists()
    if not exists:
        messages.error(request, f"No se encontraron registros para la placa {plate}")
        return redirect("parking_reports")

    start_date = form.cleaned_data["start_date"]
    end_date = form.cleaned_data["end_date"]

    context = generate_plate_report(request.parking, plate, start_date, end_date)

    match request.GET.get("format"):
        case "pdf":

            return render_pdf_response(
                request,
                "parking/reports/parking_plate_report_pdf.html",
                context,
                f"reporte-placa-{plate}.pdf"
            )

        case "xlsx":

            return export_report_excel(
                context,
                start_date,
                end_date,
                "plate",
                plate=plate
            )

        case _:
            messages.error(request, "Formato no soportado para el reporte")
            return redirect("parking_reports")


@require_POST
@perm_required('parking.add_entry')
def interpret_voice_plate(request):
    """
    Recibe las alternativas del dictado por voz y devuelve la placa
    interpretada, si entrará o saldrá, y placas conocidas parecidas.
    """
    try:
        payload = json.loads(request.body)
        alternatives = payload.get("alternatives", [])
        prefix = str(payload.get("prefix") or "")[:10].upper()
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "Solicitud inválida"}, status=400)

    if not isinstance(alternatives, list):
        return JsonResponse({"ok": False, "error": "Solicitud inválida"}, status=400)

    alternatives = [str(a)[:200] for a in alternatives[:10]]
    result = interpret(request.parking, alternatives, prefix=prefix)

    return JsonResponse(_plate_result_json(result))


def _plate_result_json(result):
    """Formato común del dictado y del escaneo: placa, entrada/salida y sugerencias."""
    if result["ok"]:
        result["formatted"] = format_plate(result["plate"])
        entry_date = result.pop("entry_date_hour")
        result["entry_time"] = localtime(entry_date).strftime("%I:%M %p") if entry_date else None

        for candidate in result["candidates"]:
            candidate["formatted"] = format_plate(candidate["plate"])

    return result


def plate_scan_button(parking):
    """None si el parqueo no tiene el escaneo; si lo tiene, si su paquete se agotó."""
    if not plate_scan.is_enabled(parking):
        return None
    return {"exhausted": plate_scan.quota(parking)["exhausted"]}


# Escaneos por usuario y minuto: evita gasto por errores o abuso
SCAN_RATE_PER_MINUTE = 10


@require_POST
@perm_required('parking.add_entry')
def scan_plate_photo(request):
    """
    Recibe el recorte de la placa tomado con la cámara, lo lee con IA y
    devuelve lo mismo que el dictado por voz.
    """
    parking = request.parking

    if not plate_scan.is_enabled(parking):
        return JsonResponse({"ok": False, "error": "El escaneo de placas no está activo para este parqueo."}, status=403)

    if plate_scan.quota(parking)["exhausted"]:
        return JsonResponse({
            "ok": False,
            "error": "Se terminó el paquete de IA de este mes. Digita o dicta la placa.",
        }, status=429)

    rate_key = f"plate_scan_rate:{request.user.pk}"
    cache.add(rate_key, 0, timeout=60)
    if cache.incr(rate_key) > SCAN_RATE_PER_MINUTE:
        return JsonResponse({"ok": False, "error": "Demasiados escaneos seguidos. Espera un momento."}, status=429)

    upload = request.FILES.get("image")
    if not upload:
        return JsonResponse({"ok": False, "error": "Solicitud inválida"}, status=400)

    try:
        readings = plate_scan.read_plate(parking, request.user, upload.read(plate_scan.MAX_UPLOAD_BYTES + 1))
    except plate_scan.PlateScanError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    result = interpret(parking, readings)
    result["heard"] = ", ".join(readings) or "sin placa legible"

    return JsonResponse(_plate_result_json(result))
