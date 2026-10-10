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


@pytest.mark.django_db(transaction=True)
class TestUniqueActiveEntry:
    def test_base_de_datos_impide_dos_entradas_activas(self, fee):
        from django.db import IntegrityError

        Entry.objects.bulk_create([Entry(plate="P555555", fee=fee)])
        with pytest.raises(IntegrityError):
            Entry.objects.bulk_create([Entry(plate="P555555", fee=fee)])

    def test_save_traduce_el_error_a_mensaje_claro(self, make_entry):
        make_entry(plate="P555555")
        with pytest.raises(ValueError, match="Ya existe una entrada activa"):
            make_entry(plate="P555555")

    def test_misma_placa_puede_tener_varias_entradas_cerradas(self, make_entry):
        make_entry(plate="P555555", minutes_ago=300, duration=30)
        make_entry(plate="P555555", minutes_ago=200, duration=30)
        make_entry(plate="P555555")
        assert Entry.objects.filter(plate="P555555").count() == 3


@pytest.mark.django_db
def test_excel_deja_vacia_la_salida_de_entradas_activas(admin_client, make_entry):
    from io import BytesIO
    from openpyxl import load_workbook

    make_entry(plate="PACTIVA", minutes_ago=30)
    make_entry(plate="PCERRADA", minutes_ago=200, duration=60)

    response = admin_client.get(f"/parking/reporte/hoy/?date={now_local()}&format=xlsx")
    rows = {r[0]: r for r in load_workbook(BytesIO(response.content)).active.iter_rows(min_row=4, values_only=True)}

    assert rows["PACTIVA"][2] in ("", None)
    assert rows["PCERRADA"][2]


@pytest.mark.django_db
class TestTicket:
    @pytest.mark.parametrize("query", ["", "?entry_id=", "?entry_id=abc", "?entry_id=999999"])
    def test_ticket_invalido_da_404(self, admin_client, query):
        assert admin_client.get(f"/parking/ticket/{query}").status_code == 404

    def test_ticket_valido(self, admin_client, make_entry):
        entry = make_entry()
        assert admin_client.get(f"/parking/ticket/?entry_id={entry.pk}").status_code == 200

    def test_ticket_requiere_permiso(self, client, django_user_model, make_entry):
        client.force_login(django_user_model.objects.create_user("sin_permiso", password="x"))
        assert client.get(f"/parking/ticket/?entry_id={make_entry().pk}").status_code == 403


class TestPdfStaticFiles:
    def test_css_se_lee_de_disco_sin_peticion_http(self):
        from pathlib import Path
        from django.conf import settings
        from parking.utils import StaticFilesURLFetcher

        fetcher = StaticFilesURLFetcher("http://servidor-inexistente.invalid/")
        response = fetcher.fetch("http://servidor-inexistente.invalid/static/css/styles.css")
        body = response.read()

        assert body == (Path(settings.BASE_DIR) / "static/css/styles.css").read_bytes()
        assert response.headers.get_content_type() == "text/css"

    def test_estatico_inexistente_falla_sin_ir_a_la_red(self):
        from parking.utils import StaticFilesURLFetcher

        fetcher = StaticFilesURLFetcher("http://servidor-inexistente.invalid/")
        with pytest.raises(FileNotFoundError):
            fetcher.fetch("http://servidor-inexistente.invalid/static/no-existe.css")


@pytest.mark.django_db
class TestConsultasConstantes:
    """El número de consultas no debe crecer con la cantidad de registros (N+1)."""

    def count_queries(self, client, url):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            assert client.get(url).status_code == 200
        return len(ctx.captured_queries)

    def add_entries(self, make_entry, prefix, n):
        for i in range(n):
            make_entry(plate=f"{prefix}{i}", minutes_ago=300 - i, duration=60 if i % 2 else None)

    @pytest.mark.parametrize("url", [
        "/parking/historial/",
        "/parking/reporte/hoy/?date={d}&format=xlsx",
        "/parking/reporte/periodo/?period_start_date={d}&period_end_date={d}&format=xlsx",
    ])
    def test_parqueo(self, admin_client, make_entry, url):
        url = url.format(d=now_local())
        self.add_entries(make_entry, "PA", 2)
        few = self.count_queries(admin_client, url)

        self.add_entries(make_entry, "PB", 10)
        many = self.count_queries(admin_client, url)

        assert many == few

    def test_historial_muestra_lo_cobrado_aunque_cambie_la_tarifa(self, admin_client, make_entry, fee):
        entry = make_entry(minutes_ago=200, duration=90)
        fee.ranges.update(amount=Decimal("99.00"))

        response = admin_client.get("/parking/historial/")
        shown = next(e for e in response.context["entries"] if e.pk == entry.pk)

        assert shown.amount == Decimal("2.00")


@pytest.mark.django_db
def test_activar_y_desactivar_suscripcion(admin_client, monthly_policy):
    url = f"/parking/suscripciones/estado/{monthly_policy.pk}"

    admin_client.post(url)
    monthly_policy.refresh_from_db()
    assert monthly_policy.active is False

    admin_client.post(url)
    monthly_policy.refresh_from_db()
    assert monthly_policy.active is True


class TestDictadoPlaca:
    @pytest.mark.parametrize("dicho,placa", [
        # Palabras agrupadas como se lee la placa
        ("pe ciento setenta y uno setecientos treinta y siete", "P171737"),
        ("pe cuarenta ochocientos siete", "P40807"),
        ("eme novecientos once ciento dieciséis", "M911116"),
        ("ce veintidós cero cero cinco", "C22005"),
        # Dígito por dígito
        ("pe uno siete uno siete tres siete", "P171737"),
        ("pe cero cero uno", "P001"),
        # El navegador ya entrega dígitos o letras
        ("P 171 737", "P171737"),
        ("p171737", "P171737"),
        ("P-40807", "P40807"),
        ("pe 171737", "P171737"),
        # Placas alfanuméricas y prefijos de dos letras
        ("pe ocho e noventa y ocho", "P8E98"),
        ("a be cien", "AB100"),
        ("a b 100", "AB100"),
        # Relleno, acentos y mayúsculas
        ("la placa es pe cuatro cero ocho cero siete", "P40807"),
        ("Placa número PE 40 807", "P40807"),
        ("pe cuatro mil ochocientos siete", "P4807"),
    ])
    def test_interpreta_lo_dicho(self, dicho, placa):
        from parking.services.voice_plate import parse_plate
        assert parse_plate(dicho) == placa

    @pytest.mark.parametrize("dicho", ["", "hola", "ciento setenta", "pe"])
    def test_texto_sin_placa_valida(self, dicho):
        from parking.services.voice_plate import is_valid_plate, parse_plate
        assert not is_valid_plate(parse_plate(dicho))


@pytest.mark.django_db
class TestDictadoEndpoint:
    url = "/parking/busqueda/voz/"

    def post(self, client, alternatives):
        import json
        return client.post(self.url, json.dumps({"alternatives": alternatives}), content_type="application/json")

    def test_placa_nueva_registrara_entrada(self, admin_client, fee):
        data = self.post(admin_client, ["pe ciento setenta y uno setecientos treinta y siete"]).json()

        assert data["ok"] is True
        assert data["plate"] == "P171737"
        assert data["formatted"] == "P 171 737"
        assert data["action"] == "entrada"

    def test_placa_adentro_registrara_salida(self, admin_client, make_entry):
        make_entry(plate="P171737")
        data = self.post(admin_client, ["P 171 737"]).json()

        assert data["action"] == "salida"
        assert data["entry_time"]

    def test_sugiere_placa_parecida_que_esta_adentro(self, admin_client, make_entry):
        make_entry(plate="P171737")
        data = self.post(admin_client, ["P 171 787"]).json()

        assert data["plate"] == "P171787"
        assert data["candidates"][0]["plate"] == "P171737"
        assert data["candidates"][0]["active"] is True

    def test_prefiere_la_alternativa_que_es_placa_conocida(self, admin_client, make_entry):
        make_entry(plate="P171737")
        data = self.post(admin_client, ["pe ciento setenta y uno setecientos ochenta y siete", "P 171 737"]).json()

        assert data["plate"] == "P171737"
        assert data["action"] == "salida"

    def test_texto_sin_placa(self, admin_client):
        data = self.post(admin_client, ["buenos días"]).json()
        assert data["ok"] is False

    @pytest.mark.parametrize("body", ["no es json", '{"alternatives": "texto"}'])
    def test_solicitud_invalida(self, admin_client, body):
        response = admin_client.post(self.url, body, content_type="application/json")
        assert response.status_code == 400

    def test_requiere_permiso(self, client, django_user_model):
        client.force_login(django_user_model.objects.create_user("sin_permiso", password="x"))
        assert self.post(client, ["P 171 737"]).status_code == 403

    def test_requiere_csrf(self, django_user_model):
        import json
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(django_user_model.objects.create_superuser("a", "a@a.com", "x"))
        response = client.post(self.url, json.dumps({"alternatives": ["P1"]}), content_type="application/json")

        assert response.status_code == 403

    def test_pantalla_de_busqueda_tiene_boton_y_modal(self, admin_client):
        html = admin_client.get("/parking/busqueda/").content.decode()

        assert "Escanear ticket" in html
        assert "Dictar placa" in html
        assert 'id="voicePlateModal"' in html
        assert 'id="plateInput"' in html


@pytest.mark.django_db
class TestEliminarEntrada:
    def url(self, entry):
        return f"/parking/eliminar/{entry.pk}/"

    def test_superusuario_elimina_y_queda_registro(self, admin_client, make_entry):
        from django.contrib.admin.models import DELETION, LogEntry

        entry = make_entry(plate="P171737", minutes_ago=120, duration=60)
        response = admin_client.post(self.url(entry))

        assert response.status_code == 302
        assert response.url == "/parking/historial/"
        assert not Entry.objects.filter(pk=entry.pk).exists()

        log = LogEntry.objects.get(action_flag=DELETION)
        assert log.user.username == "admin"
        assert log.object_id == str(entry.pk)
        assert "P171737" in log.change_message
        assert "$2.00" in log.change_message

    def test_staff_con_todos_los_permisos_no_puede(self, client, django_user_model, make_entry):
        from django.contrib.auth.models import Permission

        user = django_user_model.objects.create_user("jefe", password="x", is_staff=True)
        user.user_permissions.set(Permission.objects.filter(content_type__app_label="parking"))
        client.force_login(user)
        entry = make_entry()

        assert client.post(self.url(entry)).status_code == 403
        assert Entry.objects.filter(pk=entry.pk).exists()

    def test_get_no_elimina(self, admin_client, make_entry):
        entry = make_entry()
        assert admin_client.get(self.url(entry)).status_code == 405
        assert Entry.objects.filter(pk=entry.pk).exists()

    def test_anonimo_va_al_login(self, client, make_entry):
        entry = make_entry()
        response = client.post(self.url(entry))
        assert response.status_code == 302 and response.url.startswith("/login/")
        assert Entry.objects.filter(pk=entry.pk).exists()

    def test_entrada_inexistente(self, admin_client):
        assert admin_client.post("/parking/eliminar/999999/").status_code == 404

    def test_boton_solo_visible_para_superusuario(self, admin_client, client, django_user_model, make_entry):
        from django.contrib.auth.models import Permission

        entry = make_entry()
        assert "Eliminar entrada" in admin_client.get(f"/parking/editar/{entry.pk}/").content.decode()

        user = django_user_model.objects.create_user("editor", password="x")
        user.user_permissions.add(Permission.objects.get(codename="change_entry"))
        client.force_login(user)
        html = client.get(f"/parking/editar/{entry.pk}/").content.decode()
        assert "Eliminar entrada" not in html
        assert "deleteEntryModal" not in html
