import pytest


@pytest.fixture
def operator_client(client, django_user_model, member):
    user = member(django_user_model.objects.create_user("operador", password="x"))
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


@pytest.mark.django_db
class TestRedireccionSegura:
    @pytest.fixture
    def user(self, django_user_model, member):
        return member(django_user_model.objects.create_user("u", password="clave-segura-123"))

    def login(self, client, next_url):
        return client.post(f"/login/?next={next_url}", {"username": "u", "password": "clave-segura-123"})

    @pytest.mark.parametrize("next_url", [
        "https://sitio-malicioso.example/",
        "//sitio-malicioso.example/",
        "http://testserver.sitio-malicioso.example/",
    ])
    def test_login_ignora_next_externo(self, client, user, next_url):
        assert self.login(client, next_url).url == "/"

    def test_login_respeta_next_interno(self, client, user):
        assert self.login(client, "/parking/historial/").url == "/parking/historial/"

    def test_salida_ignora_referer_externo(self, admin_client, make_entry):
        entry = make_entry()
        admin_client.get(f"/parking/go-to-departure/{entry.pk}/", HTTP_REFERER="https://sitio-malicioso.example/")
        response = admin_client.post(f"/parking/salida/{entry.pk}")
        assert response.url == "/parking/busqueda/"

    def test_salida_vuelve_a_la_pagina_interna(self, admin_client, make_entry):
        entry = make_entry()
        admin_client.get(f"/parking/go-to-departure/{entry.pk}/", HTTP_REFERER="http://testserver/parking/historial/")
        response = admin_client.post(f"/parking/salida/{entry.pk}")
        assert response.url == "http://testserver/parking/historial/"


def test_todos_los_static_de_las_plantillas_existen():
    """En producción (manifest de WhiteNoise) un static inexistente da error 500."""
    import re
    from pathlib import Path
    from django.conf import settings
    from django.contrib.staticfiles import finders

    pattern = re.compile(r"""{%\s*static\s+['"]([^'"]+)['"]\s*%}""")
    missing = [
        f"{template.relative_to(settings.BASE_DIR)}: {name}"
        for template in Path(settings.BASE_DIR).glob("*/templates/**/*.html")
        for name in pattern.findall(template.read_text())
        if not finders.find(name)
    ]

    assert not missing, "Archivos estáticos inexistentes:\n" + "\n".join(missing)
