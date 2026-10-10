from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import ProtectedError
from django.utils.timezone import localtime

from parking.models import Entry


@pytest.mark.django_db
class TestFeeProtect:
    def test_no_se_puede_borrar_tarifa_con_entradas(self, fee, make_entry):
        make_entry(duration=30)
        with pytest.raises(ProtectedError):
            fee.delete()
        assert Entry.objects.count() == 1

    def test_se_puede_borrar_tarifa_sin_uso(self, fee):
        fee.delete()


@pytest.mark.django_db
class TestCalculateFee:
    @pytest.mark.parametrize("minute,expected", [
        (1, Decimal("1.00")), (59, Decimal("1.00")), (60, Decimal("2.00")), (500, Decimal("3.00")),
    ])
    def test_cobro_por_rangos(self, fee, minute, expected):
        assert fee.calculate_fee(minute) == expected

    def test_tiempo_menor_al_primer_rango_no_cobra(self, fee):
        fee.ranges.filter(start_minute=0).update(start_minute=15)
        assert fee.calculate_fee(5) == 0

    def test_tarifa_sin_rangos_no_cobra(self, fee):
        fee.ranges.all().delete()
        assert fee.calculate_fee(30) == 0


@pytest.mark.django_db
class TestDeparture:
    def test_registra_salida_y_congela_monto(self, admin_client, make_entry):
        entry = make_entry(minutes_ago=90)
        response = admin_client.post(f"/parking/salida/{entry.pk}")
        entry.refresh_from_db()
        assert response.status_code == 302
        assert entry.state is False
        assert entry.departure_date_hour is not None
        assert entry.final_minutes in (90, 91)  # minutos parciales se redondean hacia arriba
        assert entry.final_amount == Decimal("2.00")

    def test_segunda_salida_no_modifica_la_entrada(self, admin_client, make_entry):
        entry = make_entry(minutes_ago=300, duration=30)
        before = (entry.departure_date_hour, entry.final_minutes, entry.final_amount)

        response = admin_client.post(f"/parking/salida/{entry.pk}")
        entry.refresh_from_db()

        assert response.status_code == 302
        assert (entry.departure_date_hour, entry.final_minutes, entry.final_amount) == before

    def test_get_de_entrada_cerrada_redirige(self, admin_client, make_entry):
        entry = make_entry(duration=30)
        response = admin_client.get(f"/parking/salida/{entry.pk}")
        assert response.status_code == 302

    def test_salida_mensual_no_cobra(self, admin_client, make_entry, monthly_policy):
        entry = make_entry(plate=monthly_policy.plate, minutes_ago=300, fee=None)
        admin_client.post(f"/parking/salida/{entry.pk}")
        entry.refresh_from_db()
        assert entry.final_amount == 0


@pytest.mark.django_db
class TestReports:
    def summary(self, report, title):
        return next(s for s in report["summary"] if s["title"] == title)

    def test_mensualidad_se_suma_una_vez_por_placa(self, make_entry, monthly_policy):
        from parking.services.report_service import generate_month_report
        from parking.models import PlatePolicy

        PlatePolicy.objects.create(plate="P100002", billing_type="MONTHLY", amount=Decimal("40.00"))
        for days in range(1, 6):
            make_entry(plate=monthly_policy.plate, minutes_ago=60 * 24 * days, duration=480, fee=None)

        report = generate_month_report(now_local())

        assert self.summary(report, "Suscripción mensual")["income"] == Decimal("80.00")

    def test_mensualidad_sin_monto_no_rompe_el_reporte(self, make_entry):
        from parking.services.report_service import generate_month_report
        from parking.models import PlatePolicy

        PlatePolicy.objects.create(plate="P100003", billing_type="MONTHLY", amount=None)
        make_entry(plate="P100003", duration=60, fee=None)

        report = generate_month_report(now_local())

        assert self.summary(report, "Suscripción mensual")["income"] == 0

    def test_entrada_legacy_se_calcula_al_vuelo_sin_guardarse(self, make_entry):
        from parking.services.report_service import generate_day_report, generate_period_report

        entry = make_entry(minutes_ago=200, duration=90)
        Entry.objects.filter(pk=entry.pk).update(final_minutes=None, final_amount=None)
        day = localtime(entry.departure_date_hour).date()

        assert generate_day_report(day)["total_income"] == Decimal("2.00")
        assert generate_period_report(day, day)["total_income"] == Decimal("2.00")

        entry.refresh_from_db()
        assert entry.final_amount is None

    def test_suscripcion_por_hora_se_reporta_como_tarifa(self, admin_client, make_entry):
        from parking.models import PlatePolicy

        PlatePolicy.objects.create(plate="P300001", billing_type="HOURLY", amount=Decimal("1.00"))
        entry = make_entry(plate="P300001", minutes_ago=200, duration=90)
        day = localtime(entry.departure_date_hour).date().isoformat()

        excel = admin_client.get(f"/parking/reporte/hoy/?date={day}&format=xlsx")
        plate = admin_client.get(
            f"/parking/reporte/placa/?plate=P300001&start_date={day}&end_date={day}&format=xlsx"
        )

        assert excel.status_code == 200
        assert plate.status_code == 200

    def test_entrada_activa_no_suma_ingresos(self, make_entry):
        from parking.services.report_service import generate_day_report

        make_entry(minutes_ago=30)

        assert generate_day_report(now_local())["total_income"] == 0


def now_local():
    from django.utils.timezone import localdate
    return localdate()
