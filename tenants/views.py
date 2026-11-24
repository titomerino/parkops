from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from shell.decorators import perm_required, superuser_required
from tenants.employees import (
    MANAGE_PERMISSION, assignable_groups, generate_temp_password, manageable_employees,
    other_owners, reset_password, save_employee,
)
from tenants.forms import AccountPasswordForm, EmployeeForm
from audit.services import Action, diff, record as audit
from shell.utils import safe_redirect_url
from tenants.middleware import SESSION_KEY
from tenants.models import Parking


@require_POST
@superuser_required
def switch_parking(request):
    """El superusuario elige con qué parqueo trabajar (se guarda en la sesión)."""

    parking = get_object_or_404(Parking, pk=request.POST.get("parking_id"))
    request.session[SESSION_KEY] = parking.pk

    messages.success(request, f"Ahora trabajas en: {parking.name}")

    # Volver a la página donde estaba, salvo vistas de un registro de otro parqueo
    return redirect(safe_redirect_url(request, request.POST.get("next")) or "dashboard")


# ---------------------------------------------------------------- Mi cuenta

@login_required(login_url="login")
def account(request):
    """Datos del usuario y cambio de su propia contraseña.

    Si alguien le asignó una contraseña temporal, la app lo trae aquí hasta
    que ponga una suya (ver CurrentParkingMiddleware).
    """
    membership = getattr(request.user, "parking_membership", None)
    forced = bool(membership and membership.must_change_password)

    form = AccountPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # no cierra su sesión
        audit(request, Action.PASSWORD_CHANGED, "Cambió su contraseña", target=user.get_username())
        if membership and membership.must_change_password:
            membership.must_change_password = False
            membership.save(update_fields=["must_change_password"])
        messages.success(request, "Tu contraseña se cambió correctamente.")
        return redirect("dashboard")

    return render(request, "tenants/account.html", {
        "form": form,
        "forced": forced,
        "roles": ", ".join(g.name for g in request.user.groups.all()) or ("Superusuario" if request.user.is_superuser else "—"),
    })


# ---------------------------------------------------------------- Empleados
#
# La tarjeta del empleado se despliega con sus acciones; editar, contraseña,
# acceso y agregar se abren en la modal de la app
# (cabecera X-Entry-Modal: 1): las vistas responden con la tarjeta o con JSON
# al guardar. Sin la cabecera funcionan como páginas normales.

def _is_modal(request):
    return request.headers.get("X-Entry-Modal") == "1"


def _employee_or_404(request, pk):
    """Solo empleados de su parqueo que puede administrar (nunca otros dueños ni él mismo)."""
    return get_object_or_404(manageable_employees(request.user, request.parking), pk=pk)


def _employee_row(user, assignable):
    roles = [g.name for g in user.groups.all() if g in assignable] or [g.name for g in user.groups.all()]
    return {
        "user": user,
        "roles": ", ".join(roles) or "Sin rol",
        "pending": user.parking_membership.must_change_password,
    }


def _display_name(user):
    return user.get_full_name() or user.username


def _employee_snapshot(owner, user):
    """Datos del empleado para el «antes → después» de la auditoría."""
    assignable = set(assignable_groups(owner))
    role = ", ".join(g.name for g in user.groups.all() if g in assignable) or "Sin rol"
    return {
        "first_name": ("Nombre", user.first_name or "—"),
        "last_name": ("Apellido", user.last_name or "—"),
        "username": ("Usuario", user.username),
        "email": ("Correo", user.email or "—"),
        "is_active": ("Acceso", "Sí" if user.is_active else "No"),
        "role": ("Rol", role),
        "can_delete": ("Puede eliminar entradas", "Sí" if user.has_perm("parking.delete_entry") else "No"),
    }


def _credentials(request, employee, password, created):
    template = "tenants/_employee_credentials_card.html" if _is_modal(request) else "tenants/employee_credentials.html"
    return render(request, template, {
        "employee": employee, "password": password, "created": created, "modal": _is_modal(request),
    })


@perm_required(MANAGE_PERMISSION)
def employees_list(request):
    employees = manageable_employees(request.user, request.parking).order_by("-is_active", "first_name", "username")
    assignable = set(assignable_groups(request.user))
    return render(request, "tenants/employees_list.html", {
        "rows": [_employee_row(user, assignable) for user in employees],
        "owners": other_owners(request.user, request.parking),
    })


def _form_response(request, context):
    template = "tenants/_employee_form_card.html" if _is_modal(request) else "tenants/employee_form.html"
    return render(request, template, dict(context, modal=_is_modal(request)))


@never_cache
@perm_required(MANAGE_PERMISSION)
def employee_create(request):
    form = EmployeeForm(request.POST or None, owner=request.user, initial={"is_active": True})
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        password = generate_temp_password()
        user.set_password(password)
        save_employee(
            request.user, request.parking, user, created=True,
            role=form.cleaned_data["role"],
            can_delete_entries=form.cleaned_data.get("can_delete_entries", False),
        )
        role = form.cleaned_data["role"]
        audit(
            request, Action.EMPLOYEE_CREATED,
            f"Creó el empleado {_display_name(user)} (@{user.username}) · {role.name if role else 'sin rol'}",
            target=user.username,
        )
        # La contraseña se muestra una sola vez (no se guarda en la sesión ni en mensajes)
        return _credentials(request, user, password, created=True)
    return _form_response(request, {"form": form, "creating": True})


@perm_required(MANAGE_PERMISSION)
def employee_edit(request, pk):
    employee = _employee_or_404(request, pk)
    before = _employee_snapshot(request.user, employee) if request.method == "POST" else None
    form = EmployeeForm(request.POST or None, instance=employee, owner=request.user)
    if request.method == "POST" and form.is_valid():
        save_employee(
            request.user, request.parking, form.save(commit=False), created=False,
            role=form.cleaned_data["role"],
            can_delete_entries=form.cleaned_data.get("can_delete_entries", False),
        )
        # Permisos y grupos recién cambiados: se vuelve a leer el usuario
        changes = diff(before, _employee_snapshot(request.user, type(employee).objects.get(pk=employee.pk)))
        if changes:
            audit(
                request, Action.EMPLOYEE_EDITED,
                f"Editó al empleado {_display_name(employee)}: " + ", ".join(c["field"].lower() for c in changes),
                target=employee.username, changes=changes,
            )
        message = f"Se guardaron los datos de {_display_name(employee)}."
        if _is_modal(request):
            return JsonResponse({"ok": True, "message": message})
        messages.success(request, message)
        return redirect("employees_list")
    return _form_response(request, {"form": form, "employee": employee})


def _confirm(request, employee, **context):
    """GET de una acción: en la modal, su confirmación; como página, la ficha del empleado."""
    if not _is_modal(request):
        return redirect("employee_edit", pk=employee.pk)
    return render(request, "tenants/_employee_confirm_card.html", dict(context, employee=employee))


@require_http_methods(["GET", "POST"])
@perm_required(MANAGE_PERMISSION)
def employee_toggle_access(request, pk):
    """Quita o devuelve el acceso a la app. Sin acceso, su sesión abierta deja de funcionar."""
    employee = _employee_or_404(request, pk)
    name = _display_name(employee)

    if request.method == "GET":
        if employee.is_active:
            return _confirm(
                request, employee, title="Desactivar empleado", icon="bi-person-slash",
                text=f"{name} ya no podrá entrar a ParkOps. Sus registros se conservan y puedes activarlo cuando quieras.",
                action=request.path, button="Sí, desactivar", button_class="btn-danger",
            )
        return _confirm(
            request, employee, title="Activar empleado", icon="bi-person-check",
            text=f"{name} podrá volver a entrar a ParkOps con su usuario y contraseña.",
            action=request.path, button="Sí, activar", button_class="btn-success",
        )

    employee.is_active = not employee.is_active
    employee.save(update_fields=["is_active"])
    audit(
        request, Action.EMPLOYEE_ACCESS,
        f"{'Activó' if employee.is_active else 'Desactivó'} al empleado {name}", target=employee.username,
    )

    if employee.is_active:
        message = f"{name} puede volver a entrar a ParkOps."
    else:
        message = f"{name} ya no puede entrar a ParkOps."
    if _is_modal(request):
        return JsonResponse({"ok": True, "message": message})
    messages.success(request, message)
    return redirect("employees_list")


@never_cache
@require_http_methods(["GET", "POST"])
@perm_required(MANAGE_PERMISSION)
def employee_reset_password(request, pk):
    employee = _employee_or_404(request, pk)
    if request.method == "GET":
        return _confirm(
            request, employee, title="Contraseña temporal", icon="bi-key",
            text="Su contraseña actual dejará de funcionar y te mostraremos una temporal para dársela. "
                 "Al entrar, la app le pedirá crear la suya.",
            action=request.path, button="Sí, generar contraseña", button_class="btn-warning",
        )
    password = reset_password(employee)
    audit(
        request, Action.EMPLOYEE_PASSWORD,
        f"Generó una contraseña temporal para {_display_name(employee)}", target=employee.username,
    )
    return _credentials(request, employee, password, created=False)
