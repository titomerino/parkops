from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.timezone import now, localtime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.models import DELETION, LogEntry
from shell.decorators import perm_required
from shell.utils import safe_redirect_url
from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from io import BytesIO
import json

import qrcode, base64

from payment.services.payment_service import notify_pending_payments

from .models import  Entry, Fee, KeyDeposit, PlatePolicy, Range
from .forms import (
    EntryForm, 
    EntryEditForm, 
    PlateSearchForm, 
    EntryExitForm, 
    PlatePolicyForm, 
    ReportFilterByDayForm,
    ReportFilterByMonthForm,
    ReportFilterByPlateForm,
    FeeForm,
    RangeFormSet,
)
from parking.utils import (
    minutes_to_hours_and_minutes, format_plate,
    render_pdf_response, export_report_excel
)
from parking.services import key_photo, plate_scan
from tenants.decorators import keys_enabled_required
from audit.services import Action, diff, record as audit, snapshot
from parking.services.voice_plate import interpret
from parking.services.report_service import (
    generate_day_report, generate_month_report,
    generate_plate_report
)


def _is_modal(request):
    """La pantalla se pidió para mostrarse dentro de una modal (EntryModal)."""
    return request.headers.get("X-Entry-Modal") == "1"


def _modal_error(message, status=409):
    return JsonResponse({"ok": False, "error": message}, status=status)


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

            entry.created_by = request.user

            try:
                entry.save()
            except ValueError as e:
                # Ya está adentro (o se registró dos veces): no hay ticket que imprimir
                if _is_modal(request):
                    return _modal_error(str(e))
                messages.error(request, str(e))
                return redirect('search_plate')

            charge = f"suscripción {policy.get_billing_type_display().lower()}" if has_subscription else (
                f"tarifa {entry.fee.name}" if entry.fee else "sin tarifa"
            )
            audit(request, Action.ENTRY_CREATED, f"Registró entrada de {entry.plate} · {charge}", target=entry.plate)

            message = f"La entrada para {entry.plate} se guardó correctamente."
            print_ticket = request.POST.get('action') == 'save_print'

            if _is_modal(request):
                return JsonResponse({
                    "ok": True,
                    "message": message,
                    "entry_id": entry.id,
                    "print": print_ticket,
                })

            messages.success(request, message)

            if print_ticket:
                # redirige a la vista de impresión
                return redirect(f"/parking/busqueda/?entry_id={entry.id}")

            return redirect('search_plate')
    else:
        form = EntryForm(initial={'plate': plate}, parking=request.parking)

        if has_subscription and 'fee' in form.fields:
            form.fields.pop('fee')

    template = "parking/partials/_entry_register_card.html" if _is_modal(request) else "parking/register.html"
    return render(request, template, {
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
            entry.departure_by = request.user

            # Si es mensual o diario, ya no depende de fee
            if billing_type in ["MONTHLY", "DAILY"]:
                entry.fee_id = None

            # La llave se borra al dar salida: se anota en la auditoría que se entregó
            key_hook = KeyDeposit.objects.filter(entry=entry).values_list("hook", flat=True).first()

            # save() congela final_minutes y final_amount al cambiar la salida
            entry.save()

        amount = entry.final_amount

        spent_hours, spent_minutes = minutes_to_hours_and_minutes(entry.final_minutes or 0)
        summary = f"Dio salida a {entry.plate} · cobró ${amount or 0:.2f} · {spent_hours}:{spent_minutes} h"
        if billing_type in ["MONTHLY", "DAILY"]:
            summary += f" ({'mensual' if billing_type == 'MONTHLY' else 'diario'})"
        if key_hook is not None:
            summary += f" · entregó la llave{f' (gancho {key_hook})' if key_hook else ''}"
        audit(request, Action.ENTRY_DEPARTURE, summary, target=entry.plate)

        if billing_type == "MONTHLY":
            msg = f"Salida registrada para {entry.plate} (Mensual — $0.00)"
        elif billing_type == "DAILY":
            msg = f"Salida registrada para {entry.plate} (Diario — ${amount:.2f})"
        else:
            msg = f"Salida registrada para {entry.plate} — ${amount:.2f}"

        return_url = _pop_return_url(request, entry.pk)

        if _is_modal(request):
            return JsonResponse({"ok": True, "message": msg, "entry_id": entry.pk})

        messages.success(request, msg)
        return redirect(return_url or "search_plate")

    form = EntryExitForm(initial={
        "time_spent": f"{hours}:{minutes} h",
        "total_amount": f"${amount:.2f}"
    })

    if billing_type == "MONTHLY":
        form.fields.pop("total_amount", None)

    key_deposit = None
    if request.parking.keys_enabled:
        key_deposit = KeyDeposit.objects.filter(entry=entry).defer("photo").first()

    template = "parking/partials/_entry_departure_card.html" if _is_modal(request) else "parking/departure.html"
    return render(request, template, {
        "entry": entry,
        "key_deposit": key_deposit,
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
    message = f"La entrada de {entry.plate} ya tiene salida registrada ({departure})."

    if _is_modal(request):
        return _modal_error(message)

    messages.warning(request, message)
    return redirect("search_plate")


def _pop_return_url(request, pk):
    """Página a la que se vuelve después de cobrar la salida de `pk`.

    Solo vale para la entrada con la que se guardó: si se abrió la salida de
    otro carro y no se cobró, no debe mandar a esa página.
    """
    saved = request.session.pop("departure_return_url", None)
    if isinstance(saved, dict) and saved.get("pk") == pk:
        return safe_redirect_url(request, saved.get("url"))
    return None

@login_required(login_url='login')
def go_to_departure(request, pk):
    # Página REAL de donde vino el usuario
    return_url = safe_redirect_url(request, request.META.get('HTTP_REFERER'))

    if return_url:
        request.session['departure_return_url'] = {"pk": pk, "url": return_url}
    else:
        request.session.pop('departure_return_url', None)

    return redirect('departure', pk)

# Campos de la entrada que se comparan al editar (antes → después)
ENTRY_AUDIT_FIELDS = ["plate", "entry_date_hour", "departure_date_hour", "fee", "state", "final_amount"]


@perm_required('parking.change_entry')
def entry_edit_view(request, pk):
    """ Vista para editar una entrada (solo admin) """

    entry = get_object_or_404(Entry, pk=pk, parking=request.parking)
    policy = PlatePolicy.objects.for_parking(request.parking).filter(plate=entry.plate, active=True).first()

    modal = _is_modal(request)

    if request.method == "POST":
        before = snapshot(entry, ENTRY_AUDIT_FIELDS)
        form = EntryEditForm(request.POST, instance=entry, parking=request.parking)

        if form.is_valid():
            try:
                form.save()
            except ValueError as e:
                # Quitar la salida de un carro que ya volvió a entrar: dos entradas activas
                form.add_error(None, str(e))
            else:
                changes = diff(before, snapshot(entry, ENTRY_AUDIT_FIELDS))
                if changes:
                    audit(
                        request, Action.ENTRY_EDITED,
                        f"Editó entrada de {entry.plate}: " + ", ".join(c["field"].lower() for c in changes),
                        target=entry.plate, changes=changes,
                    )
                message = "Entrada actualizada correctamente."
                if modal:
                    return JsonResponse({"ok": True, "message": message, "entry_id": entry.pk})
                messages.success(request, message)
                return redirect('record')

        if not modal:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = EntryEditForm(instance=entry, parking=request.parking)

    template = "parking/partials/_entry_edit_card.html" if modal else "parking/entry_edit_form.html"
    return render(request, template, {
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

    audit(request, Action.ENTRY_DELETED, f"Eliminó entrada · {detail}", target=entry.plate)

    entry.delete()

    message = f"Entrada eliminada: {detail}"
    if _is_modal(request):
        return JsonResponse({"ok": True, "message": message})

    messages.success(request, message)
    return redirect('record')

@login_required(login_url='login')
def search_plate(request):
    """Vista principal: buscar placa y decidir flujo"""

    modal = _is_modal(request)

    if not modal and request.user.has_perm("parking.view_statistics_entry"):
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

            if modal:
                # La búsqueda solo dice qué pantalla abrir en la modal
                url = reverse('departure', args=[entry.id]) if entry else reverse('register', args=[plate])
                return JsonResponse({"ok": True, "url": url})

            if entry:
                # Existe → salida
                save_return_url(request, entry.id)
                return redirect('departure', entry.id)
            else:
                # No existe → entrada
                return redirect('register', plate)

        else:
            error_message = form.errors.get('plate')
            error_message = error_message[0] if error_message else "Formulario inválido"

            if modal:
                return _modal_error(error_message, status=400)

            messages.error(request, error_message)

    return render(request, "parking/search_plate.html", {
        'form': form,
        'plate_scan': plate_scan_button(request.parking),
    })

@login_required(login_url='login')
def ticket_plate(request, pk):
    """Placa del ticket escaneado: el QR solo llena el buscador.

    `active` dice si el vehículo sigue adentro (si no, el ticket ya se cobró).
    """
    entry = Entry.objects.for_parking(request.parking).filter(pk=pk).only("plate", "state").first()
    if not entry:
        return _modal_error("Ese ticket no es de este parqueo.", status=404)
    return JsonResponse({"ok": True, "plate": entry.plate, "active": entry.state})


SUGGESTION_LIMIT = 30  # el listado tiene scroll


@perm_required('parking.view_entry')
def plate_suggestions(request):
    """Sugerencias mientras se digita una placa en la búsqueda.

    Solo vehículos que están adentro (entradas activas); al elegir uno se va
    a su salida. Las placas que no están adentro se registran con el botón.
    """
    q = "".join(ch for ch in request.GET.get("q", "") if ch.isalnum()).upper()[:10]
    if len(q) < 2:
        return JsonResponse({"results": []})

    parking = request.parking
    active = (
        Entry.objects.for_parking(parking)
        .filter(state=True, plate__contains=q)
        .select_related("fee")
        .only("plate", "entry_date_hour", "fee__name")
    )
    if parking.keys_enabled:
        active = active.annotate(
            key_hook=Subquery(KeyDeposit.objects.filter(entry=OuterRef("pk")).values("hook")[:1])
        )

    # Las que empiezan con lo digitado, primero
    entries = sorted(active, key=lambda e: (not e.plate.startswith(q), e.plate))[:SUGGESTION_LIMIT]

    return JsonResponse({"results": [
        {
            "plate": entry.plate,
            "label": format_plate(entry.plate),
            "detail": "Adentro desde " + localtime(entry.entry_date_hour).strftime("%I:%M %p")
                      + (f" · {entry.fee.name}" if entry.fee else ""),
            "hook": getattr(entry, "key_hook", None),
            "url": reverse("go_to_departure", args=[entry.pk]),
            "modal_url": reverse("departure", args=[entry.pk]),
        }
        for entry in entries
    ]})


@perm_required('parking.view_entry')
def record(request):

    if request.user.has_perm("parking.view_statistics_entry"):
        notify_pending_payments(request)

    today = localtime(now()).date()

    queryset = (
        Entry.objects.for_parking(request.parking)
        .entries_today_and_active(today)
        .select_related("fee", "created_by", "departure_by")
        .prefetch_related("fee__ranges")
        .only(
            "plate",
            "entry_date_hour",
            "departure_date_hour",
            "fee",
            "state",
            "final_minutes",
            "final_amount",
            "created_by__username",
            "departure_by__username",
        )
        .order_by("-state", "-entry_date_hour")
    )

    if request.parking.keys_enabled:
        keys = KeyDeposit.objects.filter(entry=OuterRef("pk"))
        queryset = queryset.annotate(
            has_key=Exists(keys),
            key_hook=Subquery(keys.values("hook")[:1]),
            key_version=Subquery(keys.values("updated_at")[:1]),
        )

    entries = list(queryset)

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
            policy = form.save()
            audit(
                request, Action.SUBSCRIPTION_CREATED,
                f"Creó suscripción de {policy.plate} · {policy.get_billing_type_display().lower()} ${policy.amount or 0:.2f}",
                target=policy.plate,
            )
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

SUBSCRIPTION_AUDIT_FIELDS = ["plate", "owner_name", "billing_type", "amount", "active"]


@perm_required('parking.change_platepolicy')
def subscription_edit(request, pk):
    """ Editar suscripción / política de cobro de una placa """

    policy = get_object_or_404(PlatePolicy, pk=pk, parking=request.parking)

    if request.method == 'POST':
        before = snapshot(policy, SUBSCRIPTION_AUDIT_FIELDS)
        form = PlatePolicyForm(
            request.POST,
            instance=policy,
            parking=request.parking
        )

        if form.is_valid():
            form.save()
            changes = diff(before, snapshot(policy, SUBSCRIPTION_AUDIT_FIELDS))
            if changes:
                audit(
                    request, Action.SUBSCRIPTION_EDITED,
                    f"Editó suscripción de {policy.plate}: " + ", ".join(c["field"].lower() for c in changes),
                    target=policy.plate, changes=changes,
                )
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
        audit(
            request, Action.SUBSCRIPTION_STATUS,
            f"{'Activó' if policy.active else 'Desactivó'} la suscripción de {policy.plate}",
            target=policy.plate,
        )

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
def save_return_url(request, pk):
    # Solo se llama desde la búsqueda: al terminar la salida se vuelve aquí
    request.session['departure_return_url'] = {"pk": pk, "url": request.get_full_path()}

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


# ---------------------------------------------------------------- Llaves en custodia

@perm_required('parking.view_entry')
@keys_enabled_required
def keys_list(request):
    """Llaves de los carros que están adentro, ordenadas por gancho."""

    deposits = sorted(
        KeyDeposit.objects.for_parking(request.parking)
        .filter(entry__state=True)
        .select_related("entry")
        .defer("photo"),
        key=lambda deposit: (deposit.hook_sort_key, deposit.created_at),
    )

    return render(request, "parking/keys_list.html", {"deposits": deposits})


@require_POST
@perm_required('parking.add_entry')
@keys_enabled_required
def key_save(request, entry_id):
    """Guarda la foto y el gancho de la llave de un carro que está adentro."""

    entry = get_object_or_404(Entry.objects.for_parking(request.parking), pk=entry_id, state=True)
    deposit = KeyDeposit.objects.filter(entry=entry).defer("photo").first()
    upload = request.FILES.get("photo")

    if upload is None and deposit is None:
        return JsonResponse({"ok": False, "error": "Toma la foto de la llave."}, status=400)

    created = deposit is None
    old_hook = None if created else deposit.hook
    if created:
        deposit = KeyDeposit(parking=request.parking, entry=entry, created_by=request.user)

    if upload is not None:
        try:
            deposit.photo = key_photo.optimize(upload.read(key_photo.MAX_UPLOAD_BYTES + 1))
        except key_photo.KeyPhotoError as error:
            return JsonResponse({"ok": False, "error": str(error)}, status=400)

    deposit.hook = request.POST.get("hook", "").strip()[:10]
    deposit.save()

    hook = f"gancho {deposit.hook}" if deposit.hook else "sin gancho"
    if created:
        audit(request, Action.KEY_RECEIVED, f"Recibió la llave de {entry.plate} · {hook}", target=entry.plate)
    else:
        changes = []
        if upload is not None:
            changes.append({"field": "Foto", "before": "anterior", "after": "nueva"})
        if old_hook != deposit.hook:
            changes.append({"field": "Gancho", "before": old_hook or "—", "after": deposit.hook or "—"})
        if changes:
            audit(request, Action.KEY_UPDATED, f"Actualizó la llave de {entry.plate} · {hook}", target=entry.plate, changes=changes)

    return JsonResponse({"ok": True, "hook": deposit.hook})


@perm_required('parking.view_entry')
@keys_enabled_required
def key_photo_view(request, entry_id):
    """La foto se sirve solo a usuarios del parqueo y solo mientras el carro está adentro."""

    deposit = get_object_or_404(
        KeyDeposit.objects.for_parking(request.parking).only("photo"),
        entry_id=entry_id,
        entry__state=True,
    )

    response = HttpResponse(bytes(deposit.photo), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=300"
    return response


# ---------------------------------------------------------------- Tarifas
#
# Lista con tarjetas que se despliegan; crear, editar y activar/desactivar se
# abren en la modal de la app (cabecera X-Entry-Modal: 1). Sin la cabecera
# funcionan como páginas normales.

def minutes_label(minutes):
    """90 → «1 h 30 min»."""
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def ranges_text(fee):
    """«Al entrar $1.00 · 1 h $1.50 · …» para comparar los precios antes y después."""
    ranges = sorted(fee.ranges.all(), key=lambda r: r.start_minute) if fee.pk else []
    return " · ".join(
        f"{'al entrar' if r.start_minute == 0 else minutes_label(r.start_minute)} ${r.amount:.2f}" for r in ranges
    ) or "—"


FEE_AUDIT_FIELDS = ["name", "description", "default", "is_active"]


def _fee_or_404(request, pk):
    return get_object_or_404(Fee.objects.for_parking(request.parking), pk=pk)


@perm_required("parking.change_fee")
def fees_list(request):
    fees = (
        Fee.objects.for_parking(request.parking)
        .prefetch_related("ranges")
        .order_by("-is_active", "-default", "name")
    )
    for fee in fees:
        fee.sorted_ranges = [
            {"label": minutes_label(r.start_minute), "amount": r.amount}
            for r in sorted(fee.ranges.all(), key=lambda r: r.start_minute)
        ]
    return render(request, "parking/fees_list.html", {"fees": fees})


@transaction.atomic
def _save_fee(form, formset):
    fee = form.save(commit=False)
    if fee.default:
        # Solo una tarifa por defecto en el parqueo
        Fee.objects.for_parking(fee.parking).filter(default=True).exclude(pk=fee.pk).update(default=False)
    fee.save()
    formset.instance = fee
    formset.save()
    return fee


def _fee_form(request, fee=None):
    creating = fee is None
    fee = fee or Fee(parking=request.parking, is_active=True)
    data = request.POST if request.method == "POST" else None
    before = None if creating else dict(snapshot(fee, FEE_AUDIT_FIELDS), ranges=("Precios", ranges_text(fee)))
    form = FeeForm(data, instance=fee, parking=request.parking)
    formset = RangeFormSet(data, instance=fee, prefix="ranges")

    if creating and data is None:
        # Arranca con el primer rango (lo que paga al entrar)
        formset = RangeFormSet(instance=fee, prefix="ranges", queryset=Range.objects.none())
        formset.extra = 1
        formset.initial_extra = [{"start_minute": 0}]

    if data is not None and form.is_valid() and formset.is_valid():
        fee = _save_fee(form, formset)
        if creating:
            audit(request, Action.FEE_CREATED, f"Creó la tarifa {fee.name} · {ranges_text(fee)}", target=fee.name)
        else:
            changes = diff(before, dict(snapshot(fee, FEE_AUDIT_FIELDS), ranges=("Precios", ranges_text(fee))))
            if changes:
                audit(
                    request, Action.FEE_EDITED,
                    f"Editó la tarifa {fee.name}: " + ", ".join(c["field"].lower() for c in changes),
                    target=fee.name, changes=changes,
                )
        message = f"Tarifa «{fee.name}» {'creada' if creating else 'actualizada'} correctamente."
        if _is_modal(request):
            return JsonResponse({"ok": True, "message": message})
        messages.success(request, message)
        return redirect("fees_list")

    template = "parking/partials/_fee_form_card.html" if _is_modal(request) else "parking/fee_form.html"
    return render(request, template, {"form": form, "formset": formset, "fee": fee, "creating": creating})


@perm_required("parking.add_fee")
def fee_create(request):
    return _fee_form(request)


@perm_required("parking.change_fee")
def fee_edit(request, pk):
    return _fee_form(request, _fee_or_404(request, pk))


@perm_required("parking.change_fee")
def fee_toggle_active(request, pk):
    """Activa o desactiva la tarifa. En la modal, el GET muestra la confirmación."""
    fee = _fee_or_404(request, pk)

    if request.method == "GET":
        if not _is_modal(request):
            return redirect("fee_edit", pk=fee.pk)
        return render(request, "parking/partials/_fee_confirm_card.html", {"fee": fee})

    if request.method != "POST":
        return HttpResponse(status=405)

    if fee.is_active and fee.default:
        error = "No puedes desactivar la tarifa por defecto. Elige otra por defecto primero."
        if _is_modal(request):
            return _modal_error(error)
        messages.error(request, error)
        return redirect("fees_list")

    fee.is_active = not fee.is_active
    fee.save(update_fields=["is_active"])
    audit(request, Action.FEE_STATUS, f"{'Activó' if fee.is_active else 'Desactivó'} la tarifa {fee.name}", target=fee.name)
    message = f"Tarifa «{fee.name}» {'activada' if fee.is_active else 'desactivada'}."
    if _is_modal(request):
        return JsonResponse({"ok": True, "message": message})
    messages.success(request, message)
    return redirect("fees_list")

