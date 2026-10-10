from decimal import Decimal

import pytest
from django.db.models import ProtectedError

from bathrooms.models import BathroomEntry, BathroomFee


@pytest.mark.django_db
def test_no_se_puede_borrar_tarifa_de_bano_con_usos():
    fee = BathroomFee.objects.create(name="Sanitario", amount=Decimal("0.25"))
    BathroomEntry.objects.create(fee=fee)
    with pytest.raises(ProtectedError):
        fee.delete()
    assert BathroomEntry.objects.count() == 1


@pytest.fixture
def bathroom_fee(db):
    return BathroomFee.objects.create(name="Sanitario", amount=Decimal("0.25"))


@pytest.mark.django_db
class TestAccionesSoloPost:
    def test_get_no_registra_uso(self, admin_client, bathroom_fee):
        response = admin_client.get(f"/baños/entradas/registrar/{bathroom_fee.pk}/")
        assert response.status_code == 405
        assert not BathroomEntry.objects.exists()

    def test_post_registra_uso(self, admin_client, bathroom_fee):
        response = admin_client.post(f"/baños/entradas/registrar/{bathroom_fee.pk}/")
        assert response.status_code == 302
        assert BathroomEntry.objects.count() == 1

    def test_post_sin_csrf_es_rechazado(self, django_user_model, bathroom_fee):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(django_user_model.objects.create_superuser("a", "a@a.com", "x"))

        response = client.post(f"/baños/entradas/registrar/{bathroom_fee.pk}/")

        assert response.status_code == 403
        assert not BathroomEntry.objects.exists()

    def test_get_no_cambia_estado_de_tarifa(self, admin_client, bathroom_fee):
        response = admin_client.get(f"/baños/tarifas/estado/{bathroom_fee.pk}/")
        bathroom_fee.refresh_from_db()
        assert response.status_code == 405
        assert bathroom_fee.state is True

    def test_post_cambia_estado_de_tarifa(self, admin_client, bathroom_fee):
        admin_client.post(f"/baños/tarifas/estado/{bathroom_fee.pk}/")
        bathroom_fee.refresh_from_db()
        assert bathroom_fee.state is False

    def test_paginas_muestran_formularios_con_csrf(self, admin_client, bathroom_fee):
        for url in ["/baños/entradas/", "/baños/tarifas/"]:
            html = admin_client.get(url).content.decode()
            assert 'method="post"' in html
            assert "csrfmiddlewaretoken" in html


@pytest.mark.django_db
class TestTarifaInexistente:
    @pytest.mark.parametrize("method,url", [
        ("get", "/baños/tarifas/editar/999999/"),
        ("post", "/baños/tarifas/estado/999999/"),
        ("post", "/baños/entradas/registrar/999999/"),
    ])
    def test_da_404(self, admin_client, method, url):
        assert getattr(admin_client, method)(url).status_code == 404

    def test_no_se_cobra_con_tarifa_inactiva(self, admin_client):
        fee = BathroomFee.objects.create(name="Vieja", amount=Decimal("0.10"), state=False)
        assert admin_client.post(f"/baños/entradas/registrar/{fee.pk}/").status_code == 404
        assert not BathroomEntry.objects.exists()
