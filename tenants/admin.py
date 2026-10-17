from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.password_validation import validate_password

from decimal import Decimal

from django.db.models import Avg
from django.shortcuts import redirect
from django.urls import reverse

from tenants.models import AiPackage, AiSettings, AiTopUp, Parking, ParkingMember
from tenants.services import create_parking_account, ensure_role_groups


class ParkingAccountForm(forms.ModelForm):
    """Alta de un parqueo nuevo junto con su usuario dueño."""

    owner_username = forms.CharField(label="Usuario del dueño", max_length=150)
    owner_password = forms.CharField(
        label="Contraseña del dueño",
        widget=forms.PasswordInput(render_value=False),
        help_text="El dueño podrá cambiarla después.",
    )
    with_default_fee = forms.BooleanField(
        label="Crear tarifa inicial",
        required=False,
        initial=True,
        help_text="Tarifa «Normal»: $1 la primera hora y +$0.50 cada media hora hasta $6.",
    )

    class Meta:
        model = Parking
        fields = [
            "name", "address", "phone", "capacity", "bathrooms_enabled",
            "keys_enabled", "active",
        ]

    def clean_owner_username(self):
        username = self.cleaned_data["owner_username"]
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def clean_owner_password(self):
        password = self.cleaned_data["owner_password"]
        validate_password(password)
        return password


class AiTopUpInline(admin.TabularInline):
    """Paquetes extra del mes: se agregan cuando el parqueo agotó su paquete."""

    model = AiTopUp
    extra = 0
    fields = ("package", "month", "scans", "price", "paid", "created_at")
    readonly_fields = ("scans", "price", "created_at")
    verbose_name = "Paquete extra de IA"
    verbose_name_plural = "Recargas de IA (cuentan solo en su mes y se suman a su factura)"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "package":
            kwargs["queryset"] = AiPackage.objects.filter(active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ParkingMemberInline(admin.TabularInline):
    model = ParkingMember
    extra = 0
    autocomplete_fields = ["user"]
    verbose_name = "Usuario"
    verbose_name_plural = "Usuarios del parqueo"


@admin.register(Parking)
class ParkingAdmin(admin.ModelAdmin):
    list_display = (
        "name", "phone", "current_plan", "ai_usage", "bathrooms_enabled", "active", "members_count", "created_at",
    )
    list_filter = ("active", "bathrooms_enabled", "keys_enabled")
    search_fields = ("name", "address", "phone")
    inlines = [ParkingMemberInline, AiTopUpInline]
    actions = ["invoice_current_month", "invoice_previous_month"]

    @admin.display(description="Plan")
    def current_plan(self, obj):
        names = [s.name for s in obj.subscriptions.all() if s.active]
        return ", ".join(names) or "—"

    @admin.display(description="IA este mes")
    def ai_usage(self, obj):
        from parking.services import plate_scan

        quota = plate_scan.quota(obj)
        if not quota["limit"] and not quota["used"]:
            return "—"
        status = " · AGOTADO" if quota["exhausted"] else ""
        return f"{quota['used']:,} / {quota['limit']:,}{status}"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("subscriptions")

    def _invoice(self, request, queryset, period):
        from payment.services.invoice_service import generate_invoice, month_label

        invoices = [generate_invoice(parking, period) for parking in queryset]
        self.message_user(
            request,
            f"{len(invoices)} factura(s) de {month_label(period)} generada(s). "
            "Están en Pagos → Facturas, con su PDF.",
            messages.SUCCESS,
        )

    @admin.action(description="Generar factura del mes actual")
    def invoice_current_month(self, request, queryset):
        from django.utils.timezone import localdate

        self._invoice(request, queryset, localdate().replace(day=1))

    @admin.action(description="Generar factura del mes anterior")
    def invoice_previous_month(self, request, queryset):
        from payment.services.invoice_service import previous_month

        self._invoice(request, queryset, previous_month())

    @admin.display(description="Usuarios")
    def members_count(self, obj):
        return obj.members.count()

    def get_form(self, request, obj=None, **kwargs):
        # Al crear: formulario de cuenta (parqueo + dueño); al editar: el normal
        if obj is None:
            kwargs["form"] = ParkingAccountForm
        return super().get_form(request, obj, **kwargs)

    def get_inlines(self, request, obj):
        return self.inlines if obj else []

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)

        parking, owner = create_parking_account(
            owner_username=form.cleaned_data["owner_username"],
            owner_password=form.cleaned_data["owner_password"],
            with_default_fee=form.cleaned_data["with_default_fee"],
            **{field: form.cleaned_data[field] for field in ParkingAccountForm.Meta.fields},
        )
        # El admin continúa con este objeto (mensaje y redirección)
        obj.pk = parking.pk
        obj._state.adding = False
        messages.info(request, f"Usuario dueño «{owner.username}» creado para {parking.name}.")


# Usuarios: asignar parqueo y ver a cuál pertenecen
class UserParkingInline(admin.StackedInline):
    model = ParkingMember
    fk_name = "user"
    max_num = 1
    can_delete = False
    verbose_name = "Parqueo"
    verbose_name_plural = "Parqueo (los superusuarios no necesitan)"


User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserParkingInline]
    list_display = BaseUserAdmin.list_display + ("parking_name",)
    list_filter = BaseUserAdmin.list_filter + ("parking_membership__parking",)
    list_select_related = ("parking_membership__parking",)

    @admin.display(description="Parqueo", ordering="parking_membership__parking__name")
    def parking_name(self, obj):
        membership = getattr(obj, "parking_membership", None)
        return membership.parking.name if membership else "—"

    def get_inline_instances(self, request, obj=None):
        # En el alta del usuario Django muestra solo usuario/contraseña
        return super().get_inline_instances(request, obj) if obj else []

    def changelist_view(self, request, extra_context=None):
        # Garantiza que existan los grupos de roles para asignarlos
        ensure_role_groups()
        return super().changelist_view(request, extra_context)


# ---------------------------------------------------------------- IA

class AiSettingsForm(forms.ModelForm):
    """La API key no se vuelve a mostrar: vacía = conservar la actual."""

    api_key = forms.CharField(
        label="API key de Anthropic",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "size": 60}),
    )
    clear_api_key = forms.BooleanField(label="Borrar la API key guardada", required=False)

    class Meta:
        model = AiSettings
        fields = ["api_key", "clear_api_key", "model", "price_input", "price_output"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        key = self.instance.api_key
        if key:
            status = f"Guardada (termina en …{key[-4:]}). Déjala vacía para conservarla."
        elif self.instance.effective_api_key:
            status = "No hay una guardada aquí: se usa la variable ANTHROPIC_API_KEY del servidor."
        else:
            status = "Sin configurar: el escaneo con IA está desactivado en todos los parqueos."
        self.fields["api_key"].help_text = status

    def clean_api_key(self):
        key = self.cleaned_data["api_key"].strip()
        if self.cleaned_data.get("clear_api_key"):
            return ""
        if key and not key.startswith("sk-ant-"):
            raise forms.ValidationError("Una API key de Anthropic empieza con «sk-ant-».")
        return key or self.instance.api_key

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("clear_api_key"):
            cleaned["api_key"] = ""
        return cleaned


@admin.register(AiSettings)
class AiSettingsAdmin(admin.ModelAdmin):
    form = AiSettingsForm

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Una sola configuración: se abre directo
        AiSettings.objects.get_or_create(pk=1)
        return redirect(reverse("admin:tenants_aisettings_change", args=[1]))


# Costo de referencia por escaneo cuando todavía no hay escaneos reales
REFERENCE_SCAN_COST = Decimal("0.0003")


@admin.register(AiPackage)
class AiPackageAdmin(admin.ModelAdmin):
    list_display = ("name", "scans", "price", "estimated_cost", "estimated_margin", "active")
    list_filter = ("active",)

    def changelist_view(self, request, extra_context=None):
        from parking.models import PlateScan

        average = PlateScan.objects.aggregate(avg=Avg("cost"))["avg"]
        self._scan_cost = Decimal(average) if average else REFERENCE_SCAN_COST
        return super().changelist_view(request, extra_context)

    def _cost(self, obj):
        return obj.scans * getattr(self, "_scan_cost", REFERENCE_SCAN_COST)

    @admin.display(description="Costo IA si se usa completo")
    def estimated_cost(self, obj):
        return f"${self._cost(obj):.2f}"

    @admin.display(description="Ganancia estimada")
    def estimated_margin(self, obj):
        margin = obj.price - self._cost(obj)
        percent = (margin / obj.price * 100) if obj.price else 0
        return f"${margin:.2f} ({percent:.0f}%)"
