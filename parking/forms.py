from django import forms
from .models import Fee, Entry, Configuration, PlatePolicy
from django.core.validators import RegexValidator
import re


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


class EntryEditForm(forms.ModelForm):
    """ Formulario para editar entradas (solo admin) """

    class Meta:
        model = Entry
        fields = [
            'plate',
            'entry_date_hour',
            'departure_date_hour',
            'fee',
            'state',
            'final_amount'
        ]
        widgets = {
            'plate': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Placa del vehículo',
                'maxlength': '10',
                'pattern': '[A-Z0-9]+',
                'oninput': "this.value = this.value.replace(/\\s/g, '').toUpperCase()"
            }),
            'entry_date_hour': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
                'required': True
            }),
            'departure_date_hour': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'fee': forms.Select(attrs={
                'class': 'form-select'
            }),
            'state': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch'
            }),
            'final_amount': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light',
                'placeholder': '... calculado automáticamente',
                'readonly': 'readonly'
            })
        }

    def clean_entry_date_hour(self):
        entry = self.cleaned_data.get('entry_date_hour')
        if not entry:
            raise forms.ValidationError(
                "La fecha y hora de entrada es obligatoria"
            )
        
        return entry
    
    def clean_departure_date_hour(self):
        departure = self.cleaned_data.get('departure_date_hour')
        entry = self.cleaned_data.get('entry_date_hour')

        if departure and entry and departure < entry:
            raise forms.ValidationError(
                "La fecha y hora de salida no puede ser anterior a la de entrada"
            )
        
        return departure
    
    def clean_plate(self):
        plate = self.cleaned_data.get('plate', '').strip()
        
        # Validar si contiene algo que no sea letra o número
        if not re.fullmatch(r'[A-Za-z0-9]+', plate):
            raise forms.ValidationError(
                "La placa solo puede contener letras y números."
            )
        
        # Validar duplicados en entradas activas (excluyendo el registro actual)
        qs = Entry.objects.filter(plate=plate, state=True).exclude(pk=self.instance.pk)
        
        if qs.exists():
            raise forms.ValidationError(
                "Ya existe una entrada activa con esta placa."
            )
        
        return plate

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.fields['fee'].choices:
            choices = [(value, label) for value, label in self.fields['fee'].choices if value != '']
            self.fields['fee'].choices = [('', '--- Sin tarifa seleccionada ---')] + choices


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
                regex=r'^[A-Za-z0-9]+$',
                message="Solo se permiten letras y números (sin espacios)"
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
                'placeholder': 'P123456',
                'maxlength': '10',
                'oninput': "this.value = this.value.replace(/\\s+/g,'').replace(/[^a-zA-Z0-9]/g,'').toUpperCase().slice(0,10);",
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

    def clean_plate(self):
        plate = self.cleaned_data['plate']

        # Normalización fuerte
        plate = re.sub(r'[^A-Za-z0-9]', '', plate).upper()[:10]

        if not plate:
            raise forms.ValidationError(
                "La placa solo puede contener letras y números"
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

