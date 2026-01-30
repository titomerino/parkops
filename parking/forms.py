from django import forms
from .models import Fee, Entry, Configuration, PlatePolicy
from django.core.validators import RegexValidator
import re


class FeeForm(forms.ModelForm):
    """ Formulario para cuotas """
    
    class Meta:
        model = Fee
        fields = [
            'duration_hours',
            'amount',
            'default'
        ]
        widgets = {
            'duration_hours': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'placeholder': 'Horas mínimas'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Monto en dólares'
            }),
            'default': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }


class EntryForm(forms.ModelForm):
    """ Formulario para entradas """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Buscar tarifa por defecto
        default_fee = Fee.objects.filter(default=True).first()

        if default_fee:
            self.fields['fee'].initial = default_fee.id

    class Meta:
        model = Entry
        fields = [
            'plate',
            'fee'
        ]
        widgets = {
            'plate': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Placa del vehículo',
                'maxlength': 10,
                'readonly': True
            }),
            'fee': forms.Select(attrs={
                'class': 'form-select'
            })
        }


class EntryExitForm(forms.ModelForm):
    """ Formulario para salida de parqueo (solo confirmación) """

    time_spent = forms.CharField(
        label="Tiempo en parqueo",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': True
        })
    )

    total_amount = forms.CharField(
        label="Total a pagar",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': True
        })
    )

    class Meta:
        model = Entry
        fields = []  # no editamos nada directamente

        

class ConfigurationForm(forms.ModelForm):
    """ Formulario para configuraciones """

    class Meta:
        model = Configuration
        fields = [
            'name',
            'ability'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de la configuración'
            }),
            'ability': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'placeholder': 'Cantidad de espacios disponibles'
            })
        }


class PlateSearchForm(forms.Form):
    plate = forms.CharField(
        max_length=10,
        label="Placa",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'P123456'
        }),
        validators=[
            RegexValidator(
                regex=r'^[A-Za-z0-9 ]+$',
                message="Solo se permiten letras, números y espacios"
            )
        ]
    )


class PlatePolicyForm(forms.ModelForm):
    class Meta:
        model = PlatePolicy
        fields = ['plate', 'owner_name', 'billing_type', 'amount', 'active']

        widgets = {
            'plate': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light border-secondary rounded-3',
                'placeholder': 'ABC 1234',
                'maxlength': '10',
                'oninput': 'this.value = this.value.toUpperCase()',
                'required': True,
            }),
            'owner_name': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light border-secondary rounded-3',
                'placeholder': 'Juan Pérez',
                'maxlength': '150',
                'required': False,
            }),
            'billing_type': forms.Select(attrs={
                'class': 'form-select bg-dark text-light border-secondary rounded-3',
                'required': True,
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light border-secondary rounded-end-3',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
            }),
            'active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch'
            }),
        }

    # 🔐 Validación de placa
    def clean_plate(self):
        plate = self.cleaned_data['plate'].strip().upper()

        # Solo letras, números y espacios
        if not re.match(r'^[A-Z0-9 ]+$', plate):
            raise forms.ValidationError(
                "La placa solo puede contener letras, números y espacios"
            )

        qs = PlatePolicy.objects.filter(plate=plate)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(
                "Esta placa ya tiene una política registrada"
            )

        return plate

    # 🧠 Validación semántica de cobro
    def clean(self):
        cleaned_data = super().clean()
        billing_type = cleaned_data.get('billing_type')
        amount = cleaned_data.get('amount')

        # Mensual → amount opcional (informativo)
        if billing_type == "MONTHLY":
            return cleaned_data

        # Diario / Hora → amount obligatorio
        if billing_type in ["DAILY", "HOURLY"] and not amount:
            raise forms.ValidationError(
                "Debes indicar un monto para este tipo de cobro"
            )

        return cleaned_data

