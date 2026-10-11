from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.timezone import localdate


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
    ai_package = models.ForeignKey(
        "tenants.AiPackage",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="parkings",
        verbose_name="Paquete mensual de IA",
        help_text="Escaneos incluidos cada mes. Vacío = sin límite",
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


class AiSettings(models.Model):
    """
    Configuración global de la IA (una sola fila). La API key se puede
    poner aquí o en la variable ANTHROPIC_API_KEY; la del admin tiene prioridad.
    """

    api_key = models.CharField(
        "API key de Anthropic",
        max_length=255,
        blank=True,
        help_text="Se crea en console.anthropic.com → API Keys. Déjala vacía para usar la variable de entorno",
    )
    model = models.CharField(
        "Modelo",
        max_length=60,
        default="claude-haiku-4-5-20251001",
        help_text="Haiku 4.5 es el más económico. Cambiarlo afecta el costo de cada escaneo",
    )
    price_input = models.DecimalField(
        "Precio entrada (USD por millón de tokens)",
        max_digits=8, decimal_places=4, default=Decimal("1"),
    )
    price_output = models.DecimalField(
        "Precio salida (USD por millón de tokens)",
        max_digits=8, decimal_places=4, default=Decimal("5"),
    )

    class Meta:
        verbose_name = "Configuración de IA"
        verbose_name_plural = "Configuración de IA"

    def __str__(self):
        return "Configuración de IA"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def effective_api_key(self):
        return self.api_key or settings.ANTHROPIC_API_KEY


class AiPackage(models.Model):
    """Paquete de escaneos con IA que se vende a los parqueos."""

    name = models.CharField("Nombre", max_length=80)
    scans = models.PositiveIntegerField("Escaneos incluidos")
    price = models.DecimalField(
        "Precio al cliente (USD)",
        max_digits=8, decimal_places=2,
        help_text="Lo que le cobras al parqueo por el paquete",
    )
    active = models.BooleanField("Disponible", default=True)

    class Meta:
        verbose_name = "Paquete de IA"
        verbose_name_plural = "Paquetes de IA"
        ordering = ["price"]

    def __str__(self):
        return f"{self.name} · {self.scans:,} escaneos · ${self.price}"


def first_day_of_month():
    return localdate().replace(day=1)


class AiTopUp(models.Model):
    """Paquete extra comprado para un mes, cuando el parqueo agotó el suyo."""

    parking = models.ForeignKey(
        Parking,
        on_delete=models.CASCADE,
        related_name="ai_top_ups",
        verbose_name="Parqueo",
    )
    package = models.ForeignKey(
        AiPackage,
        on_delete=models.PROTECT,
        verbose_name="Paquete",
    )
    month = models.DateField("Mes", default=first_day_of_month, help_text="Solo cuenta para este mes")
    scans = models.PositiveIntegerField("Escaneos", blank=True)
    price = models.DecimalField("Precio cobrado (USD)", max_digits=8, decimal_places=2, blank=True)
    created_at = models.DateTimeField("Agregado", auto_now_add=True)

    class Meta:
        verbose_name = "Paquete extra de IA"
        verbose_name_plural = "Paquetes extra de IA"
        ordering = ["-month", "-created_at"]

    def __str__(self):
        return f"{self.package.name} · {self.month:%m/%Y}"

    def save(self, *args, **kwargs):
        # Se guarda lo vendido: si después cambia el paquete, la recarga no cambia
        self.month = self.month.replace(day=1)
        if self.scans is None:
            self.scans = self.package.scans
        if self.price is None:
            self.price = self.package.price
        super().save(*args, **kwargs)
