from decimal import Decimal

import pytest
from django.db.models import ProtectedError
from django.utils.timezone import localdate

from payment.models import Payment, Subscription


@pytest.fixture
def subscription(parking):
    return Subscription.objects.create(parking=parking, name="ParkOps mensual", price=Decimal("25.00"), active=True)


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

        generate_current_month_payments(subscription.parking)
        generate_current_month_payments(subscription.parking)

        payments = Payment.objects.filter(subscription=subscription)
        assert payments.count() == 1
        assert payments.get().billing_date == localdate()
        assert payments.get().amount == Decimal("25.00")

    def test_respeta_el_pago_creado_a_mano_en_el_mes(self, subscription):
        from payment.services.payment_service import generate_current_month_payments

        manual = Payment.objects.create(
            subscription=subscription, billing_date=localdate().replace(day=1), amount=Decimal("20.00")
        )
        generate_current_month_payments(subscription.parking)

        assert list(Payment.objects.all()) == [manual]

    def test_no_genera_pagos_de_suscripciones_inactivas(self, parking):
        from payment.services.payment_service import generate_current_month_payments

        Subscription.objects.create(parking=parking, name="Inactiva", price=Decimal("10.00"), active=False)
        generate_current_month_payments(parking)

        assert not Payment.objects.exists()

    def test_entrar_al_dashboard_genera_el_pago_del_mes(self, admin_client, subscription):
        response = admin_client.get("/")

        assert response.status_code == 200
        assert Payment.objects.filter(subscription=subscription).count() == 1


# ---------------------------------------------------------------- Planes y facturas

from decimal import Decimal as D


@pytest.fixture
def plan_pro(db):
    from payment.models import Plan
    from tenants.models import AiPackage

    package = AiPackage.objects.create(name="IA 5,000", scans=5000, price=D("12"))
    return Plan.objects.create(name="Pro", price=D("45"), ai_package=package)


@pytest.fixture
def recarga(db):
    from tenants.models import AiPackage

    return AiPackage.objects.create(name="Recarga 2,000", scans=2000, price=D("8"))


@pytest.mark.django_db
class TestPlanes:
    def test_suscripcion_toma_nombre_y_precio_del_plan(self, parking, plan_pro):
        from payment.models import Subscription

        subscription = Subscription.objects.create(parking=parking, plan=plan_pro, active=True)
        assert (subscription.name, subscription.price) == ("Pro", D("45"))

    def test_precio_acordado_se_respeta(self, parking, plan_pro):
        from payment.models import Subscription

        subscription = Subscription.objects.create(parking=parking, plan=plan_pro, price=D("40"), active=True)
        assert subscription.price == D("40")

    def test_sin_plan_exige_nombre_y_precio(self, parking):
        from django.core.exceptions import ValidationError
        from payment.models import Subscription

        with pytest.raises(ValidationError) as error:
            Subscription(parking=parking).full_clean()
        assert {"name", "price"} <= set(error.value.message_dict)


@pytest.mark.django_db
class TestFactura:
    @pytest.fixture
    def setup(self, parking, plan_pro, recarga):
        from payment.models import Subscription
        from tenants.models import AiTopUp

        subscription = Subscription.objects.create(parking=parking, plan=plan_pro, active=True)
        AiTopUp.objects.create(parking=parking, package=recarga, paid=True)
        return subscription

    def test_factura_del_mes_con_plan_ia_y_recargas(self, parking, setup):
        from parking.models import PlateScan
        from payment.services.invoice_service import generate_invoice

        PlateScan.objects.bulk_create(PlateScan(parking=parking, model="x") for _ in range(3))
        invoice = generate_invoice(parking, localdate())

        lines = [(l.kind, l.description, l.amount, l.paid) for l in invoice.lines.all()]
        assert lines[0][0] == "plan" and lines[0][2] == D("45") and lines[0][3] is False
        assert lines[1][1] == "Incluye 5,000 escaneos de placas con IA" and lines[1][2] == 0
        assert lines[2][:3] == ("topup", "Recarga de IA: Recarga 2,000", D("8")) and lines[2][3] is True
        assert invoice.lines.last().detail == "3 de 7,000 escaneos disponibles"
        assert invoice.total == D("53")

    def test_regenerar_conserva_numero_y_agrega_la_nueva_recarga(self, parking, setup, recarga):
        from payment.services.invoice_service import generate_invoice
        from tenants.models import AiTopUp

        first = generate_invoice(parking, localdate())
        AiTopUp.objects.create(parking=parking, package=recarga)
        second = generate_invoice(parking, localdate())

        assert second.pk == first.pk
        assert second.total == D("61")
        assert second.lines.filter(kind="topup").count() == 2

    def test_no_incluye_datos_de_otro_parqueo_ni_de_otro_mes(self, parking, other_parking, setup, recarga):
        from datetime import date
        from payment.services.invoice_service import generate_invoice
        from tenants.models import AiTopUp

        AiTopUp.objects.create(parking=other_parking, package=recarga)
        AiTopUp.objects.create(parking=parking, package=recarga, month=date(2020, 1, 1))

        invoice = generate_invoice(parking, localdate())
        assert invoice.lines.filter(kind="topup").count() == 1

    def test_mes_anterior(self):
        from datetime import date
        from payment.services.invoice_service import previous_month

        assert previous_month(date(2026, 1, 15)) == date(2025, 12, 1)
        assert previous_month(date(2026, 3, 31)) == date(2026, 2, 1)

    def test_accion_del_admin_y_pdf(self, admin_client, parking, setup):
        from payment.models import Invoice

        response = admin_client.post("/admin/tenants/parking/", {
            "action": "invoice_current_month", "_selected_action": [parking.pk],
        })
        assert response.status_code == 302

        invoice = Invoice.objects.get(parking=parking)
        pdf = admin_client.get(f"/admin/payment/invoice/{invoice.pk}/pdf/")
        assert pdf.status_code == 200
        assert pdf["Content-Type"] == "application/pdf"

        listing = admin_client.get("/admin/payment/invoice/").content.decode()
        assert invoice.number in listing and "$45.00" in listing  # pendiente: el plan sin pagar

    def test_pdf_solo_para_el_admin(self, client, django_user_model, member, parking, setup):
        from payment.services.invoice_service import generate_invoice

        invoice = generate_invoice(parking, localdate())
        client.force_login(member(django_user_model.objects.create_user("dueno", password="x")))

        assert client.get(f"/admin/payment/invoice/{invoice.pk}/pdf/").status_code == 302
