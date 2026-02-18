from django import forms
from bathrooms.models import BathroomFee, BathroomEntry


class BathroomFeeForm(forms.ModelForm):
    """ Formulario para tarifas de baño """
    
    class Meta:
        model = BathroomFee
        fields = [
            'name',
            'amount',
            'color',
            'state'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de la tarifa',
                'maxlength': 50
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Monto en dólares'
            }),
            'color': forms.HiddenInput(),
            'state': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        error_messages = {
            'name': {
                'required': 'Debes ingresar el nombre de la tarifa',
            },
            'amount': {
                'required': 'Debes ingresar el monto de la tarifa',
            },
        }

    def clean_color(self):
        color = self.cleaned_data.get('color')
        allowed = [
            'primary', 'secondary', 'success',
            'danger', 'warning', 'info', 'dark'
        ]
        if color not in allowed:
            raise forms.ValidationError('Selecciona un color válido')
        return color
    
    def clean_name(self):
        name = self.cleaned_data.get('name')

        qs = BathroomFee.objects.filter(name__iexact=name)

        # Si estoy editando, excluyo el registro actual
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError('Ya existe una tarifa con este nombre')

        return name
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return amount
