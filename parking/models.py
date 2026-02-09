from django.db import models
from django.utils.timezone import now
from math import ceil

# Create your models here.
class Fee(models.Model):
    """Tarifas"""
    name = models.CharField(
        "Nombre",
        max_length=50,
        help_text="Nombre de la tarifa"
    )
    description = models.TextField(
        "Descripción",
        blank=True,
        help_text="Descripción de la tarifa"
    )
    default = models.BooleanField("Activa por defecto", default=False)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        verbose_name = "Tarifa"
        verbose_name_plural = "Tarifas"

    def __str__(self):
        return self.name
    
    def calculate_fee(self, minute):
        ranges = Range.objects.filter(fee=self).order_by('start_minute')
        for r in ranges:
            if minute >= r.start_minute:
                amount = r.amount
        return amount if ranges.exists() else 0



class Range(models.Model):
    """Rangos de tarifas"""
    fee = models.ForeignKey(
        Fee,
        on_delete=models.CASCADE,
        related_name='ranges',
    )
    start_minute = models.PositiveIntegerField("Minuto inicial")
    amount = models.DecimalField("Monto", max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = "Rango de tarifa"
        verbose_name_plural = "Rangos de tarifas"

    def __str__(self):
        return f"{self.fee.name} - {self.start_minute} min: ${self.amount}"
    

class Entry(models.Model): 
    """ Modelo de entradas al parqueo """
    plate = models.CharField("Placa", max_length=10)
    entry_date_hour = models.DateTimeField("Fecha y hora de entrada", auto_now_add=True)
    departure_date_hour = models.DateTimeField("Fecha y hora de salida", null=True, blank=True)
    fee = models.ForeignKey(
        Fee,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='entry_fee'
    )
    state = models.BooleanField("Estado", default=True)

    class Meta:
        verbose_name = "Entrada"
        verbose_name_plural = "Entradas"

    def __str__(self):
        return self.plate

    def calculate_amount(self):
        """
        Calcula horas y monto a pagar según tiempo transcurrido,
        tarifa por bloques o monto fijo diario, o suscripción
        """
        # Tiempo final
        end_time = self.departure_date_hour or now()
        delta = end_time - self.entry_date_hour

        # Horas redondeadas hacia arriba
        minute = ceil(delta.total_seconds() / 60)

        # Buscar política activa de suscripción
        policy = PlatePolicy.objects.filter(
            plate=self.plate,
            active=True
        ).first()

        # 🟢 Mensual → no paga nunca por salida
        if policy and policy.billing_type == "MONTHLY":
            return minute, 0

        # 🟡 Diario por suscripción → paga monto fijo por salida
        if policy and policy.billing_type == "DAILY":
            return minute, float(policy.amount or 0)

        # 🔵 Tarifa normal (Fee)
        if self.fee:
                return minute, float(self.fee.calculate_fee(minute))

        # Fallback
        return minute, 0


class Configuration(models.Model):
    """ Modelo de configuración """
    name = models.CharField("Nombre", max_length=200)
    ability = models.PositiveIntegerField("Espacios disponibles")
    # logo

    class Meta:
        verbose_name = "Configuración"
        verbose_name_plural = "Configuraciones"

    def __str__(self):
        return self.name
    

class PlatePolicy(models.Model):
    BILLING_TYPES = (
        ("HOURLY", "Por hora"),
        ("DAILY", "Diario fijo"),
        ("MONTHLY", "Mensual"),
    )

    plate = models.CharField(
        "Placa",
        max_length=10,
        unique=True
    )

    billing_type = models.CharField(
        "Tipo de cobro",
        max_length=10,
        choices=BILLING_TYPES
    )

    amount = models.DecimalField(
        "Monto",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto según tipo de cobro (diario o mensual)"
    )

    owner_name = models.CharField(
        "Propietario",
        max_length=150,
        blank=True
    )

    active = models.BooleanField("Activo", default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Política de placa"
        verbose_name_plural = "Políticas de placas"

    def __str__(self):
        return f"{self.plate} - {self.billing_type}"
