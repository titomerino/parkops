from django.conf import settings
from django.db import models


class Parking(models.Model):
    """Cuenta de un parqueo (cliente). Todos los datos operativos le pertenecen."""

    name = models.CharField("Nombre", max_length=150)
    address = models.CharField("Dirección", max_length=255, blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)
    capacity = models.PositiveIntegerField("Espacios disponibles", null=True, blank=True)
    bathrooms_enabled = models.BooleanField(
        "Módulo de baños",
        default=True,
        help_text="Si se desactiva, el parqueo no ve el menú, el dashboard ni las pantallas de baños",
    )
    plate_scan_enabled = models.BooleanField(
        "Escaneo de placas con IA",
        default=False,
        help_text="Permite leer la placa con la cámara. Cada lectura tiene costo (API de Anthropic)",
    )
    plate_scan_monthly_limit = models.PositiveIntegerField(
        "Límite mensual de escaneos",
        null=True,
        blank=True,
        help_text="Vacío = sin límite. Al llegar al límite el escaneo se bloquea hasta el próximo mes",
    )
    active = models.BooleanField(
        "Activo",
        default=True,
        help_text="Un parqueo suspendido no puede iniciar sesión",
    )
    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        verbose_name = "Parqueo"
        verbose_name_plural = "Parqueos"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ParkingMember(models.Model):
    """Un usuario pertenece a un solo parqueo. Los superusuarios no necesitan."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parking_membership",
        verbose_name="Usuario",
    )
    parking = models.ForeignKey(
        Parking,
        on_delete=models.PROTECT,
        related_name="members",
        verbose_name="Parqueo",
    )

    class Meta:
        verbose_name = "Usuario del parqueo"
        verbose_name_plural = "Usuarios del parqueo"

    def __str__(self):
        return f"{self.user} → {self.parking}"
