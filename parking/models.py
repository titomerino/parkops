from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils.timezone import localdate, now
from math import ceil
from django.db.models import Sum
from django.db.models import Q
from parking.utils import format_plate


class ParkingQuerySet(models.QuerySet):
    """Base para los modelos que pertenecen a un parqueo."""

    def for_parking(self, parking):
        return self.filter(parking=parking)


class Fee(models.Model):
    """Tarifas"""
    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="fees",
        verbose_name="Parqueo",
    )
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

    objects = ParkingQuerySet.as_manager()

    class Meta:
        verbose_name = "Tarifa"
        verbose_name_plural = "Tarifas"
        constraints = [
            # Una sola tarifa por defecto en cada parqueo
            models.UniqueConstraint(
                fields=["parking"],
                condition=Q(default=True),
                name="unique_default_fee_per_parking",
            ),
        ]

    def __str__(self):
        return self.name
    
    def calculate_fee(self, minute):
        amount = 0

        # self.ranges.all() reutiliza prefetch_related("fee__ranges") si existe
        for r in sorted(self.ranges.all(), key=lambda r: r.start_minute):
            if minute >= r.start_minute:
                amount = r.amount
            else:
                break
            
        return amount


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
    

class EntryQuerySet(ParkingQuerySet):
    def entries_today(self, date):
        return self.filter(entry_date_hour__date=date)
    
    def entries_today_and_active(self, date):
        return self.filter(
            Q(entry_date_hour__date=date) | Q(state=True)
        ).order_by('-entry_date_hour')

    def departure_today(self, date):
        return self.filter(departure_date_hour__date=date)

    def departure_month(self, year, month):
        return self.filter(
            departure_date_hour__year=year,
            departure_date_hour__month=month
        )
    
    def custom_report(self, start_date=None, end_date=None, month_date=None, n_plate=None):
        queryset = self.all()

        # Mes
        if month_date:
            queryset = queryset.filter(
                departure_date_hour__year=month_date.year,
                departure_date_hour__month=month_date.month
            )
        # Rango de fechas
        elif start_date and end_date:
            queryset = queryset.filter(
                departure_date_hour__date__range=(start_date, end_date)
            )
        # Solo fecha de inicio
        elif start_date:
            queryset = queryset.filter(
                Q(entry_date_hour__date=start_date)
                |
                Q(departure_date_hour__date=start_date)
                |
                Q(
                    entry_date_hour__date__lt=start_date,
                    departure_date_hour__isnull=True
                )
            )
        # Placa
        if n_plate:
            queryset = queryset.filter(plate=n_plate)

        # Los reportes muestran la tarifa y pueden recalcular montos.
        # Orden explícito: sin él Postgres devuelve las filas en cualquier orden.
        return (
            queryset
            .select_related("fee")
            .prefetch_related("fee__ranges")
            .order_by("entry_date_hour", "pk")
        )

    # Totales del dashboard: llamar sobre .for_parking(parking)
    def entries_today_count(self, date):
        return self.entries_today(date).count()

    def today_income(self, date):
        return (
            self.departure_today(date)
            .aggregate(total=Sum("final_amount"))
            ["total"] or 0
        )

    def month_income(self, year, month):
        return (
            self.departure_month(year, month)
            .aggregate(total=Sum("final_amount"))
            ["total"] or 0
        )


class Entry(models.Model):
    """ Modelo de entradas al parqueo """
    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Parqueo",
    )
    plate = models.CharField("Placa", max_length=10)
    entry_date_hour = models.DateTimeField("Fecha y hora de entrada", default=now)
    departure_date_hour = models.DateTimeField("Fecha y hora de salida", null=True, blank=True)
    fee = models.ForeignKey(
        Fee,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='entry_fee'
    )
    state = models.BooleanField("Estado", default=True)
    final_minutes = models.PositiveIntegerField(
        "Minutos finales",
        null=True,
        blank=True,
        help_text="Tiempo total en minutos al momento de registrar la salida"
    )

    final_amount = models.DecimalField(
        "Monto final cobrado",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto calculado al momento de registrar la salida"
    )

    objects = EntryQuerySet.as_manager()

    class Meta:
        verbose_name = "Entrada"
        verbose_name_plural = "Entradas"
        permissions = [
            ("view_statistics_entry", "Puede ver estadísticas de entradas"),
        ]
        constraints = [
            # Una entrada activa por placa dentro de cada parqueo
            models.UniqueConstraint(
                fields=["parking", "plate"],
                condition=Q(state=True),
                name="unique_active_entry_per_plate",
            ),
        ]
        indexes = [
            models.Index(fields=["parking", "entry_date_hour"], name="entry_parking_entry_idx"),
            models.Index(fields=["parking", "departure_date_hour"], name="entry_parking_departure_idx"),
            models.Index(fields=["parking", "state"], name="entry_parking_state_idx"),
        ]

    def __str__(self):
        return self.plate
    
    def save(self, *args, **kwargs):

        # El estado siempre depende de la fecha de salida
        self.state = self.departure_date_hour is None

        # Validar entradas activas
        if (
            self.state
            and Entry.objects.filter(
                parking_id=self.parking_id,
                plate=self.plate,
                state=True
            ).exclude(pk=self.pk).exists()
        ):
            raise ValueError(
                f"Ya existe una entrada activa para esta placa: {self.plate}"
            )

        # Determinar si cambio la tarifa o alguna fecha que afecte el calculo de minutos y monto final
        data_changed = False

        if self.pk:

            old = Entry.objects.only(
                "entry_date_hour",
                "departure_date_hour",
                "fee"
            ).get(pk=self.pk)

            data_changed = (
                old.entry_date_hour != self.entry_date_hour
                or old.departure_date_hour != self.departure_date_hour
                or old.fee_id != self.fee_id
            )

        else: data_changed = bool(self.departure_date_hour)

        # LLama a recalcular minutos y monto final si cambio alguna fecha o tarifa
        if data_changed:

            if self.departure_date_hour:

                minutes, amount = self.calculate_amount(
                    policy=self.policy()
                )

                self.final_minutes = minutes
                self.final_amount = amount

            else:

                self.final_minutes = None
                self.final_amount = None

        # Guardar cambios
        try:
            with transaction.atomic():
                super().save(*args, **kwargs)
        except IntegrityError as e:
            # Dos registros simultáneos de la misma placa
            if "unique_active_entry_per_plate" in str(e):
                raise ValueError(
                    f"Ya existe una entrada activa para esta placa: {self.plate}"
                ) from e
            raise

    def calculate_amount(self, policy=None):
        """
        Calcula horas y monto a pagar según tiempo transcurrido,
        tarifa por bloques o monto fijo diario, o suscripción
        """
        # Tiempo final
        end_time = self.departure_date_hour or now()
        delta = end_time - self.entry_date_hour
        minute = ceil(delta.total_seconds() / 60)


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

    def formatted_plate(self):
        """
        retorna el formato de placa con espacios
        """
        return format_plate(self.plate)
    
    def policy(self):
        """
        Retorna la política de placa activa asociada a esta entrada, si existe
        """
        return (
            PlatePolicy.objects.active()
            .filter(parking_id=self.parking_id, plate=self.plate)
            .first()
        )


class PlatePolicyQuerySet(ParkingQuerySet):
    def active(self):
        return self.filter(active=True)

    def monthly(self):
        return self.active().filter(billing_type="MONTHLY")

    # Totales del dashboard: llamar sobre .for_parking(parking)
    def total_active_monthly_subscriptions(self):
        return self.monthly().count()

    def month_income(self):
        return (
            self.monthly()
            .aggregate(total=Sum("amount"))
            ["total"] or 0
        )


class PlatePolicy(models.Model):
    BILLING_TYPES = (
        ("", "-Seleccione un tipo de cobro-"),
        ("HOURLY", "Por hora"),
        ("DAILY", "Diario fijo"),
        ("MONTHLY", "Mensual"),
    )

    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="plate_policies",
        verbose_name="Parqueo",
    )

    plate = models.CharField(
        "Placa",
        max_length=10,
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

    objects = PlatePolicyQuerySet.as_manager()

    class Meta:
        verbose_name = "Política de placa"
        verbose_name_plural = "Políticas de placas"
        permissions = [
            ("view_statistics_placepolicy", "Puede ver estadísticas de suscripciones"),
        ]
        constraints = [
            # La misma placa puede tener suscripción en distintos parqueos
            models.UniqueConstraint(
                fields=["parking", "plate"],
                name="unique_plate_policy_per_parking",
            ),
        ]

    def __str__(self):
        return f"{self.plate} - {self.billing_type}"
    
    def formatted_plate(self):
        """
        retorna el formato de placa con espacios
        """
        return format_plate(self.plate)


class PlateScanQuerySet(ParkingQuerySet):
    def this_month(self):
        today = localdate()
        return self.filter(created_at__year=today.year, created_at__month=today.month)


class PlateScan(models.Model):
    """
    Cada lectura de placa con IA: sirve para el límite mensual del parqueo
    y para calcular el costo (tokens que informa la API).
    """
    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="plate_scans",
        verbose_name="Parqueo",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Usuario",
    )
    created_at = models.DateTimeField("Fecha", default=now)
    plate = models.CharField("Lectura", max_length=50, blank=True)
    model = models.CharField("Modelo", max_length=60)
    input_tokens = models.PositiveIntegerField("Tokens de entrada", default=0)
    output_tokens = models.PositiveIntegerField("Tokens de salida", default=0)
    cost = models.DecimalField("Costo (USD)", max_digits=10, decimal_places=6, default=0)

    objects = PlateScanQuerySet.as_manager()

    class Meta:
        verbose_name = "Escaneo de placa"
        verbose_name_plural = "Escaneos de placas"
        indexes = [
            models.Index(fields=["parking", "created_at"], name="platescan_parking_created_idx"),
        ]

    def __str__(self):
        return f"{self.plate or '—'} ({self.created_at:%d/%m/%Y %H:%M})"
