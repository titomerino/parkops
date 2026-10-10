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


@pytest.mark.django_db
class TestGeneracionAutomatica:
    def test_genera_un_solo_pago_por_mes(self, subscription):
        from payment.services.payment_service import generate_current_month_payments

        generate_current_month_payments()
        generate_current_month_payments()

        payments = Payment.objects.filter(subscription=subscription)
        assert payments.count() == 1
        assert payments.get().billing_date == localdate()
        assert payments.get().amount == Decimal("25.00")

    def test_respeta_el_pago_creado_a_mano_en_el_mes(self, subscription):
        from payment.services.payment_service import generate_current_month_payments

        manual = Payment.objects.create(
            subscription=subscription, billing_date=localdate().replace(day=1), amount=Decimal("20.00")
        )
        generate_current_month_payments()

        assert list(Payment.objects.all()) == [manual]

    def test_no_genera_pagos_de_suscripciones_inactivas(self, db):
        from payment.services.payment_service import generate_current_month_payments

        Subscription.objects.create(name="Inactiva", price=Decimal("10.00"), active=False)
        generate_current_month_payments()

        assert not Payment.objects.exists()

    def test_entrar_al_dashboard_genera_el_pago_del_mes(self, admin_client, subscription):
        response = admin_client.get("/")

        assert response.status_code == 200
        assert Payment.objects.filter(subscription=subscription).count() == 1
