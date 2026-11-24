from django.conf import settings
from django.db import models
from django.utils.timezone import now


class AuditEvent(models.Model):
    """Quién hizo qué y cuándo en un parqueo. Solo se agrega: nunca se edita ni se borra desde la app."""

    class Action(models.TextChoices):
        ENTRY_CREATED = "entry_created", "Registró entrada"
        ENTRY_DEPARTURE = "entry_departure", "Dio salida"
        ENTRY_EDITED = "entry_edited", "Editó entrada"
        ENTRY_DELETED = "entry_deleted", "Eliminó entrada"
        KEY_RECEIVED = "key_received", "Recibió llave"
        KEY_UPDATED = "key_updated", "Actualizó llave"
        FEE_CREATED = "fee_created", "Creó tarifa"
        FEE_EDITED = "fee_edited", "Editó tarifa"
        FEE_STATUS = "fee_status", "Activó/desactivó tarifa"
        SUBSCRIPTION_CREATED = "subscription_created", "Creó suscripción"
        SUBSCRIPTION_EDITED = "subscription_edited", "Editó suscripción"
        SUBSCRIPTION_STATUS = "subscription_status", "Activó/desactivó suscripción"
        BATHROOM_ENTRY = "bathroom_entry", "Cobró baño"
        BATHROOM_FEE_CREATED = "bathroom_fee_created", "Creó tarifa de baño"
        BATHROOM_FEE_EDITED = "bathroom_fee_edited", "Editó tarifa de baño"
        BATHROOM_FEE_STATUS = "bathroom_fee_status", "Activó/desactivó tarifa de baño"
        EMPLOYEE_CREATED = "employee_created", "Creó empleado"
        EMPLOYEE_EDITED = "employee_edited", "Editó empleado"
        EMPLOYEE_ACCESS = "employee_access", "Cambió acceso de empleado"
        EMPLOYEE_PASSWORD = "employee_password", "Generó contraseña temporal"
        PASSWORD_CHANGED = "password_changed", "Cambió su contraseña"
        LOGIN = "login", "Inició sesión"
        LOGIN_FAILED = "login_failed", "Intento de inicio fallido"
        LOGOUT = "logout", "Cerró sesión"

    # Grupos para el filtro de la pantalla de Auditoría
    CATEGORIES = {
        "entries": ("Entradas y salidas", ["entry_created", "entry_departure", "entry_edited", "entry_deleted"]),
        "keys": ("Llaves", ["key_received", "key_updated"]),
        "fees": ("Tarifas", ["fee_created", "fee_edited", "fee_status"]),
        "subscriptions": ("Suscripciones", ["subscription_created", "subscription_edited", "subscription_status"]),
        "bathrooms": ("Baños", ["bathroom_entry", "bathroom_fee_created", "bathroom_fee_edited", "bathroom_fee_status"]),
        "employees": ("Empleados", ["employee_created", "employee_edited", "employee_access", "employee_password"]),
        "sessions": ("Sesiones", ["login", "login_failed", "logout", "password_changed"]),
    }

    parking = models.ForeignKey(
        "tenants.Parking", on_delete=models.CASCADE, null=True, blank=True,
        related_name="audit_events", verbose_name="Parqueo",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_events", verbose_name="Usuario",
    )
    # Se guarda el nombre: si el usuario se borra, el registro sigue diciendo quién fue
    username = models.CharField("Nombre de usuario", max_length=150, blank=True)
    action = models.CharField("Acción", max_length=30, choices=Action.choices)
    target = models.CharField("Sobre", max_length=100, blank=True, help_text="Placa, tarifa o empleado afectado")
    summary = models.CharField("Resumen", max_length=300)
    changes = models.JSONField("Cambios", default=list, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("Fecha", default=now, db_index=True)

    class Meta:
        verbose_name = "Evento de auditoría"
        verbose_name_plural = "Auditoría"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["parking", "-created_at"], name="audit_parking_date")]

    def __str__(self):
        return f"{self.created_at:%d/%m/%Y %H:%M} {self.username}: {self.summary}"

    @property
    def category(self):
        for key, (_, actions) in self.CATEGORIES.items():
            if self.action in actions:
                return key
        return ""
