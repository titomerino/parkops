from django.db import models
from django.utils.timezone import now
from math import ceil

# Create your models here.
class Fee(models.Model):
    """Tarifas por bloques de horas"""
    duration_hours = models.PositiveSmallIntegerField(
        "Duración (horas)",
        help_text="Tiempo mínimo en horas"
    )
    amount = models.DecimalField(
        "Monto",
        max_digits=8,
        decimal_places=2
    )
    default = models.BooleanField("Activa por defecto", default=False)

    class Meta:
        verbose_name = "Tarifa"
        verbose_name_plural = "Tarifas"

    def __str__(self):
        return f'${self.amount} por {self.duration_hours}h'
    

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
        Calcula horas y monto a pagar según tiempo transcurrido
        """
        # Verifica si la placa es mensual
        is_monthly = MonthlyPlate.objects.filter(
            plate=self.plate,
            active=True
        ).exists()

        end_time = now()
        delta = end_time - self.entry_date_hour

        # Horas redondeadas hacia arriba
        hours = ceil(delta.total_seconds() / 3600)

        # Si es mensual, no paga
        if is_monthly:
            return hours, 0

        # Si no hay tarifa asignada, monto = 0
        if not self.fee or not self.fee.amount:
            return hours, 0

        amount = hours * float(self.fee.amount)
        return hours, amount


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
    

class MonthlyPlate(models.Model):
    """ Vehículos con pago mensual """
    plate = models.CharField("Placa", max_length=10, unique=True)
    owner_name = models.CharField("Nombre del propietario", max_length=150)
    monthly_amount = models.DecimalField(
        "Monto mensual",
        max_digits=8,
        decimal_places=2
    )
    active = models.BooleanField("Activo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Placa mensual"
        verbose_name_plural = "Placas mensuales"

    def __str__(self):
        return f"{self.plate} - ${self.monthly_amount}"

    