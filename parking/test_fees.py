"""Módulo de Tarifas del dueño: crear, editar y activar/desactivar en la modal."""
from decimal import Decimal

import pytest

from parking.forms import EntryEditForm, EntryForm
from parking.models import Fee, Range
from tenants.services import OPERATOR_GROUP, OWNER_GROUP, ensure_role_groups

MODAL = {"HTTP_X_ENTRY_MODAL": "1"}


@pytest.fixture
def make_user(django_user_model, member, db):
    roles = ensure_role_groups()

    def factory(username, role, parking=None):
        user = django_user_model.objects.create_user(username, password="x")
        member(user, to=parking)
        user.groups.add(roles[role])
        return user
    return factory


@pytest.fixture
def owner_client(client, make_user):
    client.force_login(make_user("dueno", OWNER_GROUP))
    return client


def fee_data(ranges, prefix="ranges", initial=0, **extra):
    """POST del formulario: ranges = [(minuto, monto)] o [(id, minuto, monto, borrar)]."""
    data = {"name": "Nocturna", "description": "", "is_active": "on",
            f"{prefix}-TOTAL_FORMS": len(ranges), f"{prefix}-INITIAL_FORMS": initial,
            f"{prefix}-MIN_NUM_FORMS": 0, f"{prefix}-MAX_NUM_FORMS": 1000}
    for i, r in enumerate(ranges):
        pk, minute, amount, delete = r if len(r) == 4 else ("", *r, False)
        data.update({f"{prefix}-{i}-id": pk, f"{prefix}-{i}-start_minute": minute, f"{prefix}-{i}-amount": amount})
        if delete:
            data[f"{prefix}-{i}-DELETE"] = "on"
    data.update(extra)
    return data


@pytest.mark.django_db
class TestTarifas:

    def test_solo_el_dueno_ve_el_modulo(self, client, owner_client, make_user, fee):
        assert "Precios por tiempo" in owner_client.get("/").content.decode()
        html = owner_client.get("/parking/tarifas/").content.decode()
        assert "Normal" in html and f'data-entry-modal="/parking/tarifas/{fee.pk}/"' in html
        assert 'data-entry-modal="/parking/tarifas/nueva/"' in html

        client.force_login(make_user("ana", OPERATOR_GROUP))
        assert "Precios por tiempo" not in client.get("/").content.decode()
        assert client.get("/parking/tarifas/").status_code == 403

    def test_no_ve_tarifas_de_otro_parqueo(self, owner_client, other_parking):
        ajena = Fee.objects.create(parking=other_parking, name="Ajena")
        assert "Ajena" not in owner_client.get("/parking/tarifas/").content.decode()
        assert owner_client.get(f"/parking/tarifas/{ajena.pk}/", **MODAL).status_code == 404
        assert owner_client.post(f"/parking/tarifas/{ajena.pk}/estado/", **MODAL).status_code == 404

    def test_crea_tarifa_en_modal(self, owner_client, parking):
        html = owner_client.get("/parking/tarifas/nueva/", **MODAL).content.decode()
        assert "<html" not in html and 'name="ranges-0-start_minute"' in html

        data = owner_client.post("/parking/tarifas/nueva/", fee_data([(0, "2.00"), (120, "3.50")]), **MODAL).json()

        assert data["ok"] and "Nocturna" in data["message"]
        fee = Fee.objects.get(name="Nocturna")
        assert fee.parking == parking
        assert fee.calculate_fee(30) == Decimal("2.00") and fee.calculate_fee(150) == Decimal("3.50")

    def test_valida_los_rangos(self, owner_client):
        url = "/parking/tarifas/nueva/"
        sin_cero = owner_client.post(url, fee_data([(30, "1.00")]), **MODAL).content.decode()
        assert "minuto 0" in sin_cero and "<html" not in sin_cero
        assert "mismo minuto" in owner_client.post(url, fee_data([(0, "1"), (0, "2")]), **MODAL).content.decode()
        assert "negativos" in owner_client.post(url, fee_data([(0, "-1")]), **MODAL).content.decode()
        assert "al menos un rango" in owner_client.post(url, fee_data([]), **MODAL).content.decode()
        assert not Fee.objects.filter(name="Nocturna").exists()

    def test_nombre_repetido(self, owner_client, fee):
        html = owner_client.post("/parking/tarifas/nueva/", fee_data([(0, "1")], name="normal"), **MODAL).content.decode()
        assert "Ya tienes una tarifa con este nombre" in html

    def test_edita_rangos_y_por_defecto(self, owner_client, fee, parking):
        otra = Fee.objects.create(parking=parking, name="Motos")
        r0, r60, r120 = fee.ranges.order_by("start_minute")
        url = f"/parking/tarifas/{otra.pk}/"

        # Motos pasa a ser la por defecto: Normal deja de serlo
        data = owner_client.post(url, fee_data([(0, "0.50")], name="Motos", default="on"), **MODAL).json()
        assert data["ok"]
        fee.refresh_from_db(); otra.refresh_from_db()
        assert otra.default and not fee.default

        # Editar Normal: cambia un monto, quita un rango y agrega otro
        owner_client.post(f"/parking/tarifas/{fee.pk}/", fee_data([
            (r0.pk, 0, "1.25", False), (r60.pk, 60, "2.00", True), (r120.pk, 120, "3.00", False), ("", 90, "2.50", False),
        ], name="Normal", initial=3), **MODAL)
        assert list(fee.ranges.order_by("start_minute").values_list("start_minute", "amount")) == [
            (0, Decimal("1.25")), (90, Decimal("2.50")), (120, Decimal("3.00")),
        ]

    def test_desactivar_y_activar(self, owner_client, fee, parking):
        otra = Fee.objects.create(parking=parking, name="Motos")
        url = f"/parking/tarifas/{otra.pk}/estado/"
        assert "Sí, desactivar" in owner_client.get(url, **MODAL).content.decode()

        assert owner_client.post(url, **MODAL).json()["ok"]
        otra.refresh_from_db()
        assert not otra.is_active
        assert owner_client.post(url).url == "/parking/tarifas/"   # sin modal
        otra.refresh_from_db()
        assert otra.is_active

    def test_no_desactiva_la_por_defecto(self, owner_client, fee):
        url = f"/parking/tarifas/{fee.pk}/estado/"
        assert "Sí, desactivar" not in owner_client.get(url, **MODAL).content.decode()
        response = owner_client.post(url, **MODAL)
        assert response.status_code == 409 and not response.json()["ok"]
        fee.refresh_from_db()
        assert fee.is_active
        html = owner_client.post(f"/parking/tarifas/{fee.pk}/", fee_data([(0, "1")], name="Normal", default="on", is_active=""), **MODAL).content.decode()
        assert "debe estar activa" in html


@pytest.mark.django_db
class TestTarifaInactivaAlRegistrar:

    def test_no_aparece_al_registrar_pero_si_al_editar_la_entrada(self, fee, parking, make_entry):
        vieja = Fee.objects.create(parking=parking, name="Vieja", is_active=False)
        assert vieja not in EntryForm(parking=parking).fields["fee"].queryset

        entry = make_entry(fee=vieja)
        assert vieja in EntryEditForm(instance=entry).fields["fee"].queryset
        assert vieja not in EntryEditForm(instance=make_entry(plate="P2")).fields["fee"].queryset
