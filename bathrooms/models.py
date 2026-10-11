from django.db import models
from django.db.models import Sum
from django.utils.timezone import localtime, now

from parking.models import ParkingQuerySet


class BathroomFee(models.Model):
    """Tarifas por uso del baño"""

    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="bathroom_fees",
        verbose_name="Parqueo",
    )
    name = models.CharField(
        "Nombre de la tarifa",
        max_length=50
    )
    amount = models.DecimalField(
        "Monto",
        max_digits=6,
        decimal_places=2
    )
    color = models.CharField(
        "Color",
        max_length=20,
        default="primary"
    )
    state = models.BooleanField("Estado", default=True)

    objects = ParkingQuerySet.as_manager()

    class Meta:
        verbose_name = "Tarifa de Baño"
        verbose_name_plural = "Tarifas de Baños"

    def __str__(self):
        return f'{self.name} - ${self.amount}'
    

class BathroomEntryQuerySet(ParkingQuerySet):

    def today(self):
        today = localtime(now()).date()
        return self.filter(entry_date_hour__date=today)

    def total_income(self):
        return self.aggregate(
            total=Sum('fee__amount')
        )['total'] or 0

    # Totales del dashboard: llamar sobre .for_parking(parking)
    def today_income(self):
        return self.today().total_income()

    def month_income(self):
        now_date = localtime(now())
        return self.filter(
            entry_date_hour__year=now_date.year,
            entry_date_hour__month=now_date.month
        ).total_income()

    def total_today(self):
        return self.today().count()


class BathroomEntry(models.Model):
    """ Modelo de entradas al baño """
    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="bathroom_entries",
        verbose_name="Parqueo",
    )
    entry_date_hour = models.DateTimeField("Fecha y hora de entrada", auto_now_add=True)
    fee = models.ForeignKey(
        BathroomFee,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='bathroom_entry_fee'
    )
    objects = BathroomEntryQuerySet.as_manager()

    class Meta:
        verbose_name = "Entrada de Baño"
        verbose_name_plural = "Entradas de Baños"
        permissions = [
            ("view_statistics_bathroomentry", "Puede ver estadísticas de uso de baños"),
        ]
        indexes = [
            models.Index(fields=["parking", "entry_date_hour"], name="bathentry_parking_entry_idx"),
        ]

    def __str__(self):
        return f'Entrada al baño el {self.entry_date_hour}'
    
    