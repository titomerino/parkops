from decimal import Decimal

import pytest
from django.db.models import ProtectedError
from django.utils.timezone import localdate

from payment.models import Payment, Subscription


@pytest.fixture
def subscription(db):
    return Subscription.objects.create(name="ParkOps mensual", price=Decimal("25.00"), active=True)


@pytest.mark.django_db
class TestPayment:
    def test_monto_se_toma_del_precio_al_crear(self, subscription):
        payment = Payment.objects.create(subscription=subscription, billing_date=localdate())
        assert payment.amount == Decimal("25.00")

    def test_cambio_de_precio_no_altera_pagos_existentes(self, subscription):
        payment = Payment.objects.create(subscription=subscription, billing_date=localdate())

        subscription.price = Decimal("30.00")
        subscription.save()
        payment.paid = True
        payment.save()

        payment.refresh_from_db()
        assert payment.amount == Decimal("25.00")
        assert payment.payment_date is not None

    def test_no_se_puede_borrar_suscripcion_con_pagos(self, subscription):
        Payment.objects.create(subscription=subscription, billing_date=localdate())
        with pytest.raises(ProtectedError):
            subscription.delete()
        assert Payment.objects.count() == 1
