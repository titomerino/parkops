import re

from django import forms

from payment.models import Plan

from .models import Lead

COUNTRY_CODE = "503"


class LeadForm(forms.ModelForm):
    """Solicitud rápida: parqueo, nombre, WhatsApp y plan (opcional)."""

    # Campo trampa: las personas no lo ven; los bots lo llenan
    website = forms.CharField(required=False)

    class Meta:
        model = Lead
        fields = ["business_name", "contact_name", "whatsapp", "plan"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Plan.objects.filter(active=True, show_on_website=True)
        self.fields["plan"].required = False

    def clean_business_name(self):
        return self._clean_text("business_name", "Escribe el nombre de tu parqueo.")

    def clean_contact_name(self):
        return self._clean_text("contact_name", "Escribe tu nombre.")

    def _clean_text(self, field, message):
        value = " ".join(self.cleaned_data.get(field, "").split())
        if len(value) < 2:
            raise forms.ValidationError(message)
        return value

    def clean_whatsapp(self):
        digits = re.sub(r"\D", "", self.cleaned_data.get("whatsapp", ""))
        if len(digits) == 8:
            digits = COUNTRY_CODE + digits
        if not (len(digits) == 11 and digits.startswith(COUNTRY_CODE)):
            raise forms.ValidationError("Escribe un número de 8 dígitos.")
        return digits

    def is_bot(self):
        return bool(self.data.get("website"))
