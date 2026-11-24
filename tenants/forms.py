from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group
from django.forms.utils import ErrorDict
from django.utils import translation

from tenants.employees import assignable_groups, can_grant_delete
from tenants.services import OPERATOR_GROUP

INPUT = "form-control bg-dark text-light border border-secondary"


class SpanishErrorsMixin:
    """Errores de Django (contraseñas, usuario repetido...) en español.

    El sitio usa LANGUAGE_CODE en inglés para no cambiar el formato de números
    y fechas; solo estos mensajes se traducen.
    """

    def full_clean(self):
        with translation.override("es"):
            super().full_clean()
            if self._errors:
                self._errors = ErrorDict({
                    field: self.error_class([str(message) for message in errors])
                    for field, errors in self._errors.items()
                })


class AccountPasswordForm(SpanishErrorsMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            "old_password": "Contraseña actual",
            "new_password1": "Contraseña nueva",
            "new_password2": "Repite la contraseña nueva",
        }
        for name, label in labels.items():
            self.fields[name].label = label
            self.fields[name].help_text = ""
            self.fields[name].widget.attrs["class"] = INPUT
        self.fields["old_password"].widget.attrs["autofocus"] = False


class EmployeeForm(SpanishErrorsMixin, forms.ModelForm):
    """Datos y acceso de un empleado, editados por el dueño del parqueo."""

    role = forms.ModelChoiceField(queryset=None, label="Rol", required=False, empty_label="Sin rol (no puede usar la app)")
    can_delete_entries = forms.BooleanField(label="Puede eliminar entradas", required=False)

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "username", "email", "is_active"]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "username": "Usuario para iniciar sesión",
            "email": "Correo (opcional)",
            "is_active": "Acceso al sistema",
        }

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        groups = assignable_groups(owner)
        self.fields["role"].queryset = Group.objects.filter(pk__in=[g.pk for g in groups]).order_by("name")
        if self.instance.pk:
            current = [g for g in self.instance.groups.all() if g in groups]
            self.fields["role"].initial = current[0] if current else None
            self.fields["can_delete_entries"].initial = self.instance.user_permissions.filter(
                content_type__app_label="parking", codename="delete_entry").exists()
        else:
            # Empleado nuevo: rol de operador si existe
            self.fields["role"].initial = next((g for g in groups if g.name == OPERATOR_GROUP), None)
        if not can_grant_delete(owner):
            del self.fields["can_delete_entries"]

        self.fields["username"].help_text = "Letras, números y @ . + - _ (sin espacios)."
        self.fields["is_active"].help_text = "Apágalo para que no pueda entrar, sin borrar su historial."
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = INPUT if name != "role" else "form-select bg-dark text-light border border-secondary"
        self.fields["first_name"].required = True
