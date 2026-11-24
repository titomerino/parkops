"""Auditoría: cada acción deja quién la hizo, y el dueño solo ve la de su parqueo."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import localtime, now
from PIL import Image

from audit.models import AuditEvent
from audit.services import purge_old
from bathrooms.models import BathroomFee
from parking.models import Entry, Fee, KeyDeposit, PlatePolicy
from tenants.services import OPERATOR_GROUP, OWNER_GROUP, ensure_role_groups

A = AuditEvent.Action


def last(action):
    return AuditEvent.objects.filter(action=action).latest("created_at")


@pytest.fixture
def make_user(django_user_model, member, db):
    roles = ensure_role_groups()

    def factory(username, role, parking=None, password="x"):
        user = django_user_model.objects.create_user(username, password=password)
        member(user, to=parking)
        user.groups.add(roles[role])
        return user
    return factory


@pytest.fixture
def owner(make_user, parking):
    parking.keys_enabled = True
    parking.bathrooms_enabled = True
    parking.save()
    return make_user("dueno", OWNER_GROUP)


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    AuditEvent.objects.all().delete()  # sin el inicio de sesión de force_login
    return client


def jpeg():
    buffer = BytesIO()
    Image.new("RGB", (40, 40), "red").save(buffer, "JPEG")
    return SimpleUploadedFile("llave.jpg", buffer.getvalue(), content_type="image/jpeg")


@pytest.mark.django_db
class TestEntradas:

    def test_registrar_y_dar_salida_guarda_quien(self, owner_client, owner, fee, parking):
        owner_client.post("/parking/registro/P777777", {"plate": "P777777", "fee": fee.pk})
        entry = Entry.objects.get(plate="P777777")
        assert entry.created_by == owner
        event = last(A.ENTRY_CREATED)
        assert event.user == owner and event.parking == parking and event.target == "P777777"
        assert "tarifa Normal" in event.summary

        KeyDeposit.objects.create(parking=parking, entry=entry, hook="12", photo=b"x", created_by=owner)
        owner_client.post(f"/parking/salida/{entry.pk}")
        entry.refresh_from_db()
        assert entry.departure_by == owner
        summary = last(A.ENTRY_DEPARTURE).summary
        assert "cobró $1.00" in summary and "entregó la llave (gancho 12)" in summary

    def test_editar_guarda_antes_y_despues(self, owner_client, make_entry):
        entry = make_entry(plate="P111111", duration=30)
        owner_client.post(f"/parking/editar/{entry.pk}/", {
            "plate": "P222222",
            "entry_date_hour": localtime(entry.entry_date_hour).strftime("%Y-%m-%dT%H:%M"),
            "departure_date_hour": localtime(entry.departure_date_hour).strftime("%Y-%m-%dT%H:%M"),
            "fee": entry.fee_id,
        }, HTTP_X_ENTRY_MODAL="1")

        event = last(A.ENTRY_EDITED)
        plate_change = next(c for c in event.changes if c["field"] == "Placa")
        assert (plate_change["before"], plate_change["after"]) == ("P111111", "P222222")
        # Minutos redondeados del formulario: puede cambiar el monto, pero nunca aparece lo que no cambió
        assert not any(c["field"] == "Tarifa" for c in event.changes)

    def test_eliminar(self, owner_client, owner, make_entry):
        owner.user_permissions.add(Permission.objects.get(codename="delete_entry"))
        entry = make_entry(plate="P333333", duration=30)
        owner_client.post(f"/parking/eliminar/{entry.pk}/")
        assert "Placa P333333" in last(A.ENTRY_DELETED).summary

    def test_llave_recibida_y_actualizada(self, owner_client, make_entry):
        entry = make_entry(plate="P444444")
        owner_client.post(f"/parking/llaves/{entry.pk}/", {"photo": jpeg(), "hook": "7"})
        assert "gancho 7" in last(A.KEY_RECEIVED).summary
        owner_client.post(f"/parking/llaves/{entry.pk}/", {"hook": "9"})
        assert last(A.KEY_UPDATED).changes == [{"field": "Gancho", "before": "7", "after": "9"}]


@pytest.mark.django_db
class TestTarifasSuscripcionesYBanos:

    def test_tarifa_precios_antes_y_despues(self, owner_client, fee, parking):
        ranges = list(fee.ranges.order_by("start_minute"))
        data = {"name": "Normal", "description": "", "default": "on", "is_active": "on",
                "ranges-TOTAL_FORMS": 3, "ranges-INITIAL_FORMS": 3, "ranges-MIN_NUM_FORMS": 0, "ranges-MAX_NUM_FORMS": 1000}
        for i, (r, amount) in enumerate(zip(ranges, ["1.00", "2.50", "3.00"])):
            data.update({f"ranges-{i}-id": r.pk, f"ranges-{i}-start_minute": r.start_minute, f"ranges-{i}-amount": amount})
        owner_client.post(f"/parking/tarifas/{fee.pk}/", data, HTTP_X_ENTRY_MODAL="1")

        change = last(A.FEE_EDITED).changes[0]
        assert change["field"] == "Precios"
        assert "1 h $2.00" in change["before"] and "1 h $2.50" in change["after"]

        otra = Fee.objects.create(parking=parking, name="Motos")
        owner_client.post(f"/parking/tarifas/{otra.pk}/estado/")
        assert last(A.FEE_STATUS).summary == "Desactivó la tarifa Motos"

    def test_suscripciones(self, owner_client):
        owner_client.post("/parking/suscripciones/registrar", {
            "plate": "P555555", "owner_name": "Ana", "billing_type": "MONTHLY", "amount": "40", "active": "on",
        })
        assert "P555555" in last(A.SUBSCRIPTION_CREATED).summary
        policy = PlatePolicy.objects.get(plate="P555555")

        owner_client.post(f"/parking/suscripciones/{policy.pk}", {
            "plate": "P555555", "owner_name": "Ana", "billing_type": "MONTHLY", "amount": "45", "active": "on",
        })
        assert last(A.SUBSCRIPTION_EDITED).changes == [{"field": "Monto", "before": "$40.00", "after": "$45.00"}]

        owner_client.post(f"/parking/suscripciones/estado/{policy.pk}")
        assert last(A.SUBSCRIPTION_STATUS).summary == "Desactivó la suscripción de P555555"

    def test_banos(self, owner_client, parking):
        bath = BathroomFee.objects.create(parking=parking, name="Baño", amount=Decimal("0.25"))
        owner_client.post(f"/baños/entradas/registrar/{bath.pk}/")
        assert last(A.BATHROOM_ENTRY).summary == "Cobró baño · Baño $0.25"


@pytest.mark.django_db
class TestEmpleadosYSesiones:

    def test_empleados(self, owner_client, make_user):
        roles = ensure_role_groups()
        owner_client.post("/cuenta/empleados/nuevo/", {
            "first_name": "Ana", "last_name": "", "username": "ana", "email": "", "is_active": "on",
            "role": roles[OPERATOR_GROUP].pk,
        })
        assert "Ana (@ana) · Operador" in last(A.EMPLOYEE_CREATED).summary

        from django.contrib.auth import get_user_model
        ana = get_user_model().objects.get(username="ana")
        owner_client.post(f"/cuenta/empleados/{ana.pk}/", {
            "first_name": "Ana María", "last_name": "", "username": "ana", "email": "", "is_active": "on",
            "role": roles[OPERATOR_GROUP].pk,
        })
        assert last(A.EMPLOYEE_EDITED).changes == [{"field": "Nombre", "before": "Ana", "after": "Ana María"}]

        owner_client.post(f"/cuenta/empleados/{ana.pk}/acceso/")
        assert last(A.EMPLOYEE_ACCESS).summary == "Desactivó al empleado Ana María"
        owner_client.post(f"/cuenta/empleados/{ana.pk}/contrasena/")
        assert last(A.EMPLOYEE_PASSWORD).target == "ana"

    def test_inicio_cierre_y_fallidos(self, client, make_user, parking):
        make_user("ana", OPERATOR_GROUP, password="Clave-123")

        client.post("/login/", {"username": "ana", "password": "mala"})
        failed = last(A.LOGIN_FAILED)
        assert failed.username == "ana" and failed.parking == parking and failed.user is None

        client.post("/login/", {"username": "nadie", "password": "x"})
        assert last(A.LOGIN_FAILED).parking is None  # solo se ve en el admin

        client.post("/login/", {"username": "ana", "password": "Clave-123"})
        assert last(A.LOGIN).parking == parking
        client.post("/logout/")
        assert last(A.LOGOUT).username == "ana"

    def test_cambio_de_su_contrasena(self, client, make_user):
        user = make_user("ana", OPERATOR_GROUP, password="Clave-inicial-123")
        client.force_login(user)
        client.post("/cuenta/", {"old_password": "Clave-inicial-123", "new_password1": "Nueva-clave-456", "new_password2": "Nueva-clave-456"})
        assert last(A.PASSWORD_CHANGED).user == user


@pytest.mark.django_db
class TestPantallaDeAuditoria:

    def test_solo_el_dueno_y_solo_su_parqueo(self, client, owner_client, make_user, parking, other_parking):
        AuditEvent.objects.create(parking=parking, username="ana", action=A.ENTRY_CREATED, target="P1", summary="Registró entrada de P1")
        AuditEvent.objects.create(parking=other_parking, username="luis", action=A.ENTRY_CREATED, target="P9", summary="Registró entrada de P9")

        assert "Quién hizo qué" in owner_client.get("/").content.decode()
        html = owner_client.get("/auditoria/").content.decode()
        assert "Registró entrada de P1" in html and "P9" not in html and "luis" not in html

        client.force_login(make_user("op", OPERATOR_GROUP))
        assert client.get("/auditoria/").status_code == 403
        assert "Quién hizo qué" not in client.get("/").content.decode()

    def test_filtros(self, owner_client, parking):
        AuditEvent.objects.create(parking=parking, username="ana", action=A.ENTRY_CREATED, target="P111222", summary="Registró entrada de P111222")
        AuditEvent.objects.create(parking=parking, username="luis", action=A.FEE_STATUS, target="Motos", summary="Desactivó la tarifa Motos")
        AuditEvent.objects.create(parking=parking, username="ana", action=A.ENTRY_CREATED, target="P1", summary="Vieja",
                                  created_at=now() - timedelta(days=30))

        def summaries(query):
            return [e.summary for e in owner_client.get("/auditoria/" + query).context["page"]]

        assert summaries("") == ["Desactivó la tarifa Motos", "Registró entrada de P111222"]  # últimos 7 días
        assert summaries("?usuario=luis") == ["Desactivó la tarifa Motos"]
        assert summaries("?tipo=fees") == ["Desactivó la tarifa Motos"]
        assert summaries("?buscar=P111 222") == ["Registró entrada de P111222"]
        old = (now() - timedelta(days=31)).date()
        assert "Vieja" in summaries(f"?desde={old}")

    def test_se_borran_despues_de_12_meses(self, parking):
        AuditEvent.objects.create(parking=parking, action=A.LOGIN, summary="vieja", created_at=now() - timedelta(days=400))
        AuditEvent.objects.create(parking=parking, action=A.LOGIN, summary="reciente")
        assert purge_old() == 1
        assert list(AuditEvent.objects.values_list("summary", flat=True)) == ["reciente"]
