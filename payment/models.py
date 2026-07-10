from django.db import models
from django.utils.timezone import now


class Subscription(models.Model):
    activation_date = models.DateTimeField(
        "Fecha de activación de la suscripción",
        blank=True,
        null=True
    )
    name = models.CharField("Nombre de la suscripción", max_length=100)
    description = models.TextField(
        "Descripción",
        blank=True,
        null=True
    )
    price = models.DecimalField(
        "Precio",
        max_digits=10,
        decimal_places=2,
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
    
    def save(self, *args, **kwargs):
        """ Si el estado de la suscripción cambia, actualiza las fechas de activación y cancelación. """

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

        today = now().date()

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
        on_delete=models.CASCADE,
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