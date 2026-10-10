import pytest


@pytest.fixture
def operator_client(client, django_user_model):
    user = django_user_model.objects.create_user("operador", password="x")
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestPermisos:
    @pytest.mark.parametrize("url", [
        "/parking/historial/",
        "/parking/reportes/",
        "/baños/tarifas/",
    ])
    def test_anonimo_va_al_login_conservando_la_pagina(self, client, url):
        response = client.get(url)

        assert response.status_code == 302
        assert response.url.startswith("/login/?next=")

    def test_usuario_sin_permiso_recibe_403(self, operator_client):
        assert operator_client.get("/parking/historial/").status_code == 403

    def test_usuario_con_permiso_entra(self, admin_client):
        assert admin_client.get("/parking/historial/").status_code == 200


@pytest.mark.django_db
class TestLogout:
    def test_get_no_cierra_sesion(self, admin_client):
        assert admin_client.get("/logout/").status_code == 405
        assert admin_client.get("/").status_code == 200

    def test_post_cierra_sesion(self, admin_client):
        response = admin_client.post("/logout/")
        assert response.url == "/login/"
        assert admin_client.get("/").status_code == 302
