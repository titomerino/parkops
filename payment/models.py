from django.db import models
from django.utils.timezone import localdate, now


class Plan(models.Model):
    """Plan mensual de ParkOps. Puede incluir un paquete de escaneos con IA."""

    name = models.CharField("Nombre", max_length=80)
    price = models.DecimalField("Precio mensual (USD)", max_digits=10, decimal_places=2)
    ai_package = models.ForeignKey(
        "tenants.AiPackage",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="plans",
        verbose_name="IA incluida",
        help_text="Escaneos de placas con IA incluidos cada mes. Vacío = plan sin IA",
    )
    description = models.TextField("Descripción", blank=True)
    active = models.BooleanField("Disponible", default=True)

    class Meta:
        verbose_name = "Plan"
        verbose_name_plural = "Planes"
        ordering = ["price"]

    def __str__(self):
        ai = f" · IA {self.ai_package.scans:,}" if self.ai_package_id else ""
        return f"{self.name} · ${self.price}{ai}"


class Subscription(models.Model):
    """Mensualidad que el parqueo (cliente) paga por usar ParkOps."""

    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Parqueo",
    )
    activation_date = models.DateTimeField(
        "Fecha de activación de la suscripción",
        blank=True,
        null=True
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subscriptions",
        verbose_name="Plan",
        help_text="Al elegir un plan, el nombre y el precio se toman de él si se dejan vacíos",
    )
    name = models.CharField("Nombre de la suscripción", max_length=100, blank=True)
    description = models.TextField(
        "Descripción",
        blank=True,
        null=True
    )
    price = models.DecimalField(
        "Precio",
        max_digits=10,
        decimal_places=2,
        blank=True,
        help_text="Precio acordado con el parqueo (puede tener descuento sobre el del plan)",
    )
    active = models.BooleanField("Activo", default=False)
    cancellation_date = models.DateTimeField(
        "Fecha de cancelación",
        blank=True,
        null=True
    )

    class Meta:
        verbose_name = "Suscripción"
        verbose_name_plural = "Suscripciones"

    def __str__(self):
        return self.name
    
    def clean(self):
        from django.core.exceptions import ValidationError

        if not self.plan_id:
            errors = {}
            if not self.name:
                errors["name"] = "Elige un plan o escribe el nombre."
            if self.price is None:
                errors["price"] = "Elige un plan o escribe el precio."
            if errors:
                raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """ Si el estado de la suscripción cambia, actualiza las fechas de activación y cancelación. """

        if self.plan_id:
            if not self.name:
                self.name = self.plan.name
            if self.price is None:
                self.price = self.plan.price

        if self.pk:

            old = Subscription.objects.only(
                "active"
            ).get(pk=self.pk)

            active_changed = (
                old.active != self.active
            )

        else:
            active_changed = self.active

        if active_changed:

            if self.active:

                if self.activation_date is None:
                    self.activation_date = now()

                self.cancellation_date = None

            else:

                self.cancellation_date = now()

        super().save(*args, **kwargs)

    def ensure_current_month_payment(self):
        """
        Garantiza que exista el pago del mes actual.
        Si ya existe no hace nada.
        """

        today = localdate()

        payment, created = self.payments.get_or_create(
            billing_date__year=today.year,
            billing_date__month=today.month,
            defaults={
                "billing_date": today,
                "amount": self.price,
            }
        )

        return payment, created


class Payment(models.Model):
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    billing_date = models.DateField("Período de facturación")
    amount = models.DecimalField(
        "Monto a pagar",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True
    )
    payment_date = models.DateTimeField(
        "Fecha y hora de pago",
        blank=True,
        null=True
    )
    paid = models.BooleanField("Pagado", default=False)

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        state = "" if self.paid else "pendiente"

        return (
            f"Pago {state} de ${self.amount} "
            f"para {self.billing_date:%B de %Y}"
        )
    
    def save(self, *args, **kwargs):
        """ Si el estado de pago cambia, actualiza la fecha de pago. """

        # El monto se fija al crear el pago: un cambio de precio posterior
        # no debe alterar pagos ya generados
        if self._state.adding and self.amount is None:
            self.amount = self.subscription.price

        if self.pk:

            old = Payment.objects.only(
                "paid"
            ).get(pk=self.pk)

            paid_changed = (
                old.paid != self.paid
            )

        else:
            paid_changed = self.paid

        if paid_changed:

            if self.paid:
                self.payment_date = now()
            else:
                self.payment_date = None

        super().save(*args, **kwargs)

class Invoice(models.Model):
    """
    Factura mensual de un parqueo: plan(es), IA incluida y usada, y
    recargas del mes. Las líneas son una copia: no cambian si después
    cambian los precios.
    """

    parking = models.ForeignKey(
        "tenants.Parking",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="Parqueo",
    )
    period = models.DateField("Mes facturado", help_text="Primer día del mes")
    issued_at = models.DateTimeField("Emitida", default=now)
    total = models.DecimalField("Total (USD)", max_digits=10, decimal_places=2, default=0)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Factura"
        verbose_name_plural = "Facturas"
        ordering = ["-period", "parking__name"]
        constraints = [
            models.UniqueConstraint(fields=["parking", "period"], name="unique_invoice_per_parking_month"),
        ]

    def __str__(self):
        return f"Factura {self.number} · {self.parking} · {self.period:%m/%Y}"

    @property
    def number(self):
        return f"F-{self.pk:06d}" if self.pk else "—"


class InvoiceLine(models.Model):
    PLAN = "plan"
    AI_INCLUDED = "ai"
    TOP_UP = "topup"
    KINDS = (
        (PLAN, "Plan"),
        (AI_INCLUDED, "IA incluida"),
        (TOP_UP, "Recarga de IA"),
    )

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField("Tipo", max_length=10, choices=KINDS)
    description = models.CharField("Descripción", max_length=255)
    detail = models.CharField("Detalle", max_length=255, blank=True)
    amount = models.DecimalField("Monto (USD)", max_digits=10, decimal_places=2, default=0)
    paid = models.BooleanField("Pagado", default=False)

    class Meta:
        verbose_name = "Línea de factura"
        verbose_name_plural = "Líneas de factura"
        ordering = ["pk"]

    def __str__(self):
        return self.description


class BillingProfile(models.Model):
    """Tus datos como emisor de las facturas (una sola fila)."""

    business_name = models.CharField("Nombre comercial", max_length=150, default="ParkOps")
    tax_id = models.CharField("NIT / NRC", max_length=60, blank=True)
    address = models.CharField("Dirección", max_length=255, blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)
    email = models.EmailField("Correo", blank=True)
    footer = models.TextField(
        "Nota al pie",
        blank=True,
        help_text="Ej.: forma de pago, cuenta bancaria, fecha límite",
    )

    class Meta:
        verbose_name = "Datos de facturación"
        verbose_name_plural = "Datos de facturación"

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
