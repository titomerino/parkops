from django.db import models


class Lead(models.Model):
    """Solicitud de prueba gratis enviada desde la página web.

    No crea el parqueo: tú contactas al negocio por WhatsApp, lo configuras
    y das seguimiento aquí (estado, notas y fecha del próximo contacto).
    """

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    DEMO = "DEMO"
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    DISCARDED = "DISCARDED"
    STATUSES = (
        (NEW, "Nuevo"),
        (CONTACTED, "Contactado"),
        (DEMO, "En prueba"),
        (SETUP, "Configurando"),
        (ACTIVE, "Cliente activo"),
        (DISCARDED, "Descartado"),
    )

    business_name = models.CharField("Parqueo", max_length=120)
    contact_name = models.CharField("Contacto", max_length=120)
    whatsapp = models.CharField("WhatsApp", max_length=20, help_text="Con código de país, solo dígitos")
    plan = models.ForeignKey(
        "payment.Plan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Plan de interés",
    )
    status = models.CharField("Estado", max_length=10, choices=STATUSES, default=NEW)
    notes = models.TextField("Notas de seguimiento", blank=True)
    follow_up_on = models.DateField("Próximo contacto", null=True, blank=True)
    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Parqueo creado",
        help_text="Cuando ya es cliente, el parqueo que le creaste",
    )
    ip = models.GenericIPAddressField("IP", null=True, blank=True, editable=False)
    created_at = models.DateTimeField("Recibida", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizada", auto_now=True)

    class Meta:
        verbose_name = "Solicitud de prueba"
        verbose_name_plural = "Solicitudes de prueba"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.business_name} · {self.contact_name}"

    @property
    def whatsapp_display(self):
        digits = self.whatsapp
        if digits.startswith("503") and len(digits) == 11:
            return f"+503 {digits[3:7]} {digits[7:]}"
        return f"+{digits}"
