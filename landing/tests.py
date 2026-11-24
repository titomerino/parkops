from decimal import Decimal

import pytest
from django.core.cache import cache

from landing.models import Lead
from payment.models import BillingProfile, Plan
from tenants.models import AiPackage


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def plans(db):
    ia = AiPackage.objects.create(name="IA 5,000", scans=5000, price=Decimal("12"))
    AiPackage.objects.create(name="Recarga 500", scans=500, price=Decimal("3"))
    basico = Plan.objects.create(name="Básico", price=Decimal("35"), show_on_website=True, tagline="Para empezar")
    pro = Plan.objects.create(name="Pro", price=Decimal("45"), ai_package=ia, show_on_website=True, featured=True)
    Plan.objects.create(name="Complemento IA", price=Decimal("12"), ai_package=ia)  # no se publica
    return basico, pro


def lead_data(**extra):
    data = {"business_name": "Parqueo Central", "contact_name": "Ana López", "whatsapp": "7000 1234"}
    data.update(extra)
    return data


@pytest.mark.django_db
class TestPaginaWeb:

    def test_sin_sesion_muestra_la_pagina(self, client, plans):
        html = client.get("/").content.decode()
        assert "Tu parqueo bajo control" in html
        assert "$35" in html and "$45" in html and "Más popular" in html
        assert "5,000 escaneos IA" in html
        assert "Complemento IA" not in html
        assert "500 por $3" in html

    def test_con_sesion_muestra_el_panel(self, admin_client, parking):
        html = admin_client.get("/").content.decode()
        assert "Acciones rápidas" in html
        assert "Tu parqueo bajo control" not in html

    def test_sin_planes_publicados(self, client, db):
        html = client.get("/").content.decode()
        assert "te enviamos los planes" in html

    def test_whatsapp_desde_datos_de_facturacion(self, client, db):
        assert "wa.me" not in client.get("/").content.decode()
        BillingProfile.load()
        BillingProfile.objects.filter(pk=1).update(phone="7123-4567")
        assert "https://wa.me/50371234567" in client.get("/").content.decode()


@pytest.mark.django_db
class TestSolicitud:

    def test_guarda_la_solicitud(self, client, plans):
        _, pro = plans
        response = client.post("/solicitud/", lead_data(plan=pro.pk), HTTP_X_REQUESTED_WITH="fetch")

        assert response.json() == {"ok": True, "business": "Parqueo Central"}
        lead = Lead.objects.get()
        assert lead.whatsapp == "50370001234"
        assert lead.whatsapp_display == "+503 7000 1234"
        assert lead.plan == pro and lead.status == Lead.NEW
        assert lead.ip == "127.0.0.1"

    def test_sin_javascript(self, client, plans):
        response = client.post("/solicitud/", lead_data())
        assert response.status_code == 200
        assert "¡Solicitud recibida!" in response.content.decode()
        assert Lead.objects.count() == 1

    def test_datos_invalidos(self, client, plans):
        response = client.post("/solicitud/", lead_data(whatsapp="123", contact_name=" "), HTTP_X_REQUESTED_WITH="fetch")
        assert response.status_code == 400
        assert set(response.json()["errors"]) == {"whatsapp", "contact_name"}
        assert not Lead.objects.exists()

    def test_plan_no_publicado_no_se_acepta(self, client, plans):
        hidden = Plan.objects.get(name="Complemento IA")
        response = client.post("/solicitud/", lead_data(plan=hidden.pk), HTTP_X_REQUESTED_WITH="fetch")
        assert response.status_code == 400

    def test_bot_no_guarda(self, client, plans):
        response = client.post("/solicitud/", lead_data(website="http://spam"), HTTP_X_REQUESTED_WITH="fetch")
        assert response.json()["ok"] is True
        assert not Lead.objects.exists()

    def test_limite_por_hora(self, client, plans):
        for _ in range(5):
            assert client.post("/solicitud/", lead_data(), HTTP_X_REQUESTED_WITH="fetch").status_code == 200
        response = client.post("/solicitud/", lead_data(), HTTP_X_REQUESTED_WITH="fetch")
        assert response.status_code == 429
        assert Lead.objects.count() == 5

    def test_ip_real_detras_del_proxy(self, client, plans):
        client.post("/solicitud/", lead_data(), HTTP_X_REQUESTED_WITH="fetch", HTTP_X_FORWARDED_FOR="200.1.2.3, 10.0.0.1")
        assert Lead.objects.get().ip == "200.1.2.3"

    def test_solo_post(self, client, db):
        assert client.get("/solicitud/").status_code == 405


@pytest.mark.django_db
def test_admin_enlace_de_whatsapp(admin_client, plans):
    Lead.objects.create(business_name="Parqueo Sur", contact_name="Luis", whatsapp="50370001234")
    html = admin_client.get("/admin/landing/lead/").content.decode()
    assert "https://wa.me/50370001234?text=" in html and "+503 7000 1234" in html


@pytest.mark.django_db
def test_login_lleva_al_formulario_de_prueba(client):
    html = client.get("/login/").content.decode()
    assert 'href="/#registro"' in html and "Solicitar prueba gratis" in html
