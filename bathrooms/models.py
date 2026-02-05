from django.db import models
from django.db.models import Sum
from django.utils.timezone import localtime, now


class BathroomFee(models.Model):
    """Tarifas por uso del baño"""

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

    class Meta:
        verbose_name = "Tarifa de Baño"
        verbose_name_plural = "Tarifas de Baños"

    def __str__(self):
        return f'{self.name} - ${self.amount}'
    

class BathroomEntryQuerySet(models.QuerySet):

    def today(self):
        today = localtime(now()).date()
        return self.filter(entry_date_hour__date=today)

    def total_income(self):
        return self.aggregate(
            total=Sum('fee__amount')
        )['total'] or 0
    

class BathroomEntryManager(models.Manager):
    def get_queryset(self):
        return BathroomEntryQuerySet(self.model, using=self._db)

    def today_income(self):
        return self.get_queryset().today().total_income()

    def month_income(self):
        now_date = localtime(now())
        return self.get_queryset().filter(
            entry_date_hour__year=now_date.year,
            entry_date_hour__month=now_date.month
        ).total_income()
    
    def total_today(self):
        return self.get_queryset().today().count()


class BathroomEntry(models.Model):
    """ Modelo de entradas al baño """
    entry_date_hour = models.DateTimeField("Fecha y hora de entrada", auto_now_add=True)
    fee = models.ForeignKey(
        BathroomFee,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='bathroom_entry_fee'
    )
    objects = BathroomEntryManager()

    class Meta:
        verbose_name = "Entrada de Baño"
        verbose_name_plural = "Entradas de Baños"

    def __str__(self):
        return f'Entrada al baño el {self.entry_date_hour}'
    
    