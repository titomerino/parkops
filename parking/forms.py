from django import forms
from .models import Fee, Entry, Configuration, MonthlyPlate
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


class MonthlyPlateForm(forms.ModelForm):
    class Meta:
        model = MonthlyPlate
        fields = ['plate', 'owner_name', 'monthly_amount', 'active']

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
                'required': True,
            }),
            'monthly_amount': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light border-secondary rounded-end-3',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
                'required': True,
            }),
            'active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch'
            }),
        }

    def clean_plate(self):
        plate = self.cleaned_data['plate'].strip().upper()

        # Regex: solo letras, números y espacios
        if not re.match(r'^[A-Z0-9 ]+$', plate):
            raise forms.ValidationError(
                "La placa solo puede contener letras, números y espacios"
            )

        qs = MonthlyPlate.objects.filter(plate=plate)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(
                "Esta placa ya tiene una mensualidad registrada"
            )

        return plate
