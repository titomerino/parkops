"""Reportes: PDF con ReportLab, vista previa en la modal y resumen por día del mes."""
import re
from decimal import Decimal

import pytest
from django.utils.timezone import localdate

from parking.models import PlatePolicy

MODAL = {"HTTP_X_ENTRY_MODAL": "1"}


def pages(pdf):
    return len(re.findall(rb"/Type /Page[^s]", pdf))


@pytest.fixture
def month():
    return localdate().strftime("%Y-%m")


@pytest.mark.django_db
class TestPdf:

    def test_pdf_de_los_tres_reportes_se_abre_en_el_navegador(self, admin_client, make_entry, month):
        make_entry(plate="P111111", duration=90)
        day = localdate()
        for url in (
            f"/parking/reporte/hoy/?date={day}&format=pdf",
            f"/parking/reporte/mes/?month_date={month}&format=pdf",
            f"/parking/reporte/placa/?plate=P111111&start_date={day}&end_date={day}&format=pdf",
        ):
            response = admin_client.get(url)
            assert response["Content-Type"] == "application/pdf", url
            assert response["Content-Disposition"].startswith("inline;"), url
            assert response.content.startswith(b"%PDF"), url

    def test_mes_resumido_por_defecto_y_detalle_opcional(self, admin_client, make_entry, month):
        for i in range(120):
            make_entry(plate=f"P{200000 + i}", duration=30)
        url = f"/parking/reporte/mes/?month_date={month}&format=pdf"

        summary = admin_client.get(url).content
        detail = admin_client.get(url + "&detalle=1").content
        assert pages(summary) == 1
        assert pages(detail) > pages(summary)


@pytest.mark.django_db
class TestVistaPrevia:

    def test_pantalla_de_reportes_abre_la_vista_previa(self, admin_client):
        html = admin_client.get("/parking/reportes/").content.decode()
        assert html.count('value="preview"') == 3 and "Generar PDF" not in html
        assert 'id="entryModal"' in html

    def test_vista_previa_del_mes_en_la_modal(self, admin_client, make_entry, parking, month):
        make_entry(plate="P111111", duration=90)      # $2.00 con la tarifa del fixture
        make_entry(plate="P222222", duration=30)      # $1.00
        PlatePolicy.objects.create(parking=parking, plate="P900000", billing_type="MONTHLY", amount=Decimal("40"))

        response = admin_client.get(f"/parking/reporte/mes/?month_date={month}&format=preview", **MODAL)
        html = response.content.decode()
        assert "<html" not in html
        assert "Ingresos por día" in html and "data-report-detail" in html
        assert "$43.00" in html                       # 2 + 1 de tarifas + 40 de la mensualidad
        assert f"month_date={month}&amp;format=pdf" in html and "format=xlsx" in html

        days = response.context["days"]
        assert len(days) == 1 and days[0]["count"] == 2 and days[0]["total"] == Decimal("3.00")

    def test_vista_previa_del_dia_trae_el_detalle(self, admin_client, make_entry):
        make_entry(plate="P333333", duration=45)
        html = admin_client.get(f"/parking/reporte/hoy/?date={localdate()}&format=preview", **MODAL).content.decode()
        assert "P333333" in html and "Entradas (1)" in html

    def test_errores_en_la_modal_sin_cambiar_de_pantalla(self, admin_client):
        response = admin_client.get("/parking/reporte/hoy/?date=&format=preview", **MODAL)
        assert response.status_code == 400 and response.json()["ok"] is False

        day = localdate()
        response = admin_client.get(f"/parking/reporte/placa/?plate=PNOEXISTE&start_date={day}&end_date={day}&format=preview", **MODAL)
        assert "No se encontraron registros" in response.json()["error"]

    def test_sin_javascript_la_vista_previa_es_una_pagina(self, admin_client):
        html = admin_client.get(f"/parking/reporte/hoy/?date={localdate()}&format=preview").content.decode()
        assert "<html" in html and "data-report-print" in html
