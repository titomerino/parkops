from django import forms
from .models import Fee, Entry, Configuration


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
    """ Formulario de busquedas de placa """
    plate = forms.CharField(
        max_length=10,
        help_text="Escriba la placa sin guiones",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'P123456'
        })
    )
