from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.password_validation import validate_password

from tenants.models import Parking, ParkingMember
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
        fields = ["name", "address", "phone", "capacity", "bathrooms_enabled", "active"]

    def clean_owner_username(self):
        username = self.cleaned_data["owner_username"]
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def clean_owner_password(self):
        password = self.cleaned_data["owner_password"]
        validate_password(password)
        return password


class ParkingMemberInline(admin.TabularInline):
    model = ParkingMember
    extra = 0
    autocomplete_fields = ["user"]
    verbose_name = "Usuario"
    verbose_name_plural = "Usuarios del parqueo"


@admin.register(Parking)
class ParkingAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "bathrooms_enabled", "active", "members_count", "created_at")
    list_filter = ("active", "bathrooms_enabled")
    search_fields = ("name", "address", "phone")
    inlines = [ParkingMemberInline]

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
