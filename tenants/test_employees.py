"""Mi cuenta (cambio de contraseña) y el módulo de Empleados del dueño."""
import pytest
from django.contrib.auth.models import Group, Permission

from tenants.employees import generate_temp_password
from tenants.models import ParkingMember
from tenants.services import OPERATOR_GROUP, OWNER_GROUP, ensure_role_groups


@pytest.fixture
def roles(db):
    return ensure_role_groups()


@pytest.fixture
def make_user(django_user_model, member, roles):
    def factory(username, role=None, parking=None, password="Clave-inicial-123", **extra):
        user = django_user_model.objects.create_user(username, password=password, **extra)
        member(user, to=parking)
        if role:
            user.groups.add(roles[role])
        return user
    return factory


@pytest.fixture
def owner(make_user):
    return make_user("dueno", OWNER_GROUP, first_name="Carlos")


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


def employee_data(**extra):
    data = {"first_name": "Ana", "last_name": "López", "username": "ana", "email": "", "is_active": "on"}
    data.update(extra)
    return data


# ---------------------------------------------------------------- Mi cuenta

@pytest.mark.django_db
class TestMiCuenta:

    def test_cambia_su_contrasena_sin_cerrar_sesion(self, client, make_user):
        user = make_user("ana", OPERATOR_GROUP)
        client.force_login(user)

        response = client.post("/cuenta/", {
            "old_password": "Clave-inicial-123", "new_password1": "Nueva-clave-456", "new_password2": "Nueva-clave-456",
        })

        assert response.url == "/"
        user.refresh_from_db()
        assert user.check_password("Nueva-clave-456")
        assert client.get("/parking/busqueda/").status_code == 200

    def test_errores_en_espanol(self, client, make_user):
        client.force_login(make_user("ana", OPERATOR_GROUP))
        html = client.post("/cuenta/", {
            "old_password": "mala", "new_password1": "123", "new_password2": "456",
        }).content.decode()
        assert "Su contraseña antigua es incorrecta" in html or "contraseña antigua" in html.lower()
        assert "no coinciden" in html

    def test_menu_del_usuario_tiene_mi_cuenta(self, owner_client):
        html = owner_client.get("/").content.decode()
        assert 'href="/cuenta/"' in html


@pytest.mark.django_db
class TestContrasenaTemporal:

    def test_no_puede_usar_la_app_hasta_cambiarla(self, client, make_user):
        user = make_user("ana", OPERATOR_GROUP)
        ParkingMember.objects.filter(user=user).update(must_change_password=True)
        client.force_login(user)

        assert client.get("/parking/busqueda/").url == "/cuenta/"
        assert "Crea tu propia contraseña" in client.get("/cuenta/").content.decode()

        client.post("/cuenta/", {
            "old_password": "Clave-inicial-123", "new_password1": "Nueva-clave-456", "new_password2": "Nueva-clave-456",
        })
        assert client.get("/parking/busqueda/").status_code == 200
        assert not ParkingMember.objects.get(user=user).must_change_password

    def test_admin_cambia_la_contrasena_de_otro(self, admin_client, make_user):
        user = make_user("dueno", OWNER_GROUP)
        admin_client.post(f"/admin/auth/user/{user.pk}/password/", {
            "password1": "Temporal-789-x", "password2": "Temporal-789-x", "usable_password": "true",
        })
        assert ParkingMember.objects.get(user=user).must_change_password

    def test_contrasena_temporal_legible(self):
        password = generate_temp_password()
        assert len(password) == 9 and password[4] == "-"
        assert not set(password) & set("01OIL")


# ---------------------------------------------------------------- Empleados

@pytest.mark.django_db
class TestEmpleados:

    def test_solo_el_dueno_ve_el_modulo(self, client, owner_client, make_user):
        assert "Usuarios y accesos" in owner_client.get("/").content.decode()

        client.force_login(make_user("ana", OPERATOR_GROUP))
        assert "Usuarios y accesos" not in client.get("/").content.decode()
        assert client.get("/cuenta/empleados/").status_code == 403

    def test_lista_solo_sus_empleados(self, owner_client, make_user, other_parking):
        make_user("ana", OPERATOR_GROUP, first_name="Ana")
        make_user("luis", OPERATOR_GROUP, parking=other_parking, first_name="Luis")
        make_user("socio", OWNER_GROUP, first_name="Socio")

        html = owner_client.get("/cuenta/empleados/").content.decode()
        assert "Ana" in html
        assert "Luis" not in html                       # otro parqueo
        assert "Socio" in html and "no se editan" in html  # otro dueño: solo se muestra

    def test_crea_empleado_con_contrasena_temporal(self, owner_client, roles, parking):
        response = owner_client.post("/cuenta/empleados/nuevo/", employee_data(role=roles[OPERATOR_GROUP].pk))

        html = response.content.decode()
        assert "Empleado creado" in html
        from django.contrib.auth import get_user_model
        ana = get_user_model().objects.get(username="ana")
        password = response.context["password"]
        assert ana.check_password(password) and password in html
        assert ana.parking_membership.parking == parking
        assert ana.parking_membership.must_change_password
        assert list(ana.groups.all()) == [roles[OPERATOR_GROUP]]
        assert response["Cache-Control"].startswith("max-age=0")

    def test_edita_datos_y_quita_el_acceso(self, owner_client, make_user, roles):
        ana = make_user("ana", OPERATOR_GROUP)

        response = owner_client.post(f"/cuenta/empleados/{ana.pk}/", employee_data(
            first_name="Ana María", role=roles[OPERATOR_GROUP].pk, is_active="",
        ))

        assert response.url == "/cuenta/empleados/"
        ana.refresh_from_db()
        assert ana.first_name == "Ana María" and not ana.is_active

    def test_no_puede_editar_empleados_de_otro_parqueo_ni_dueños(self, owner_client, owner, make_user, other_parking):
        foreign = make_user("luis", OPERATOR_GROUP, parking=other_parking)
        partner = make_user("socio", OWNER_GROUP)

        for user in (foreign, partner, owner):
            assert owner_client.get(f"/cuenta/empleados/{user.pk}/").status_code == 404
            assert owner_client.post(f"/cuenta/empleados/{user.pk}/contrasena/").status_code == 404

    def test_no_puede_dar_rol_de_dueno(self, owner_client, make_user, roles):
        ana = make_user("ana", OPERATOR_GROUP)
        response = owner_client.post(f"/cuenta/empleados/{ana.pk}/", employee_data(role=roles[OWNER_GROUP].pk))

        assert response.status_code == 200 and response.context["form"].errors["role"]
        assert not ana.groups.filter(name=OWNER_GROUP).exists()

    def test_no_puede_dar_permisos_que_no_tiene(self, owner_client, make_user):
        poderoso = Group.objects.create(name="Contador")
        poderoso.permissions.add(Permission.objects.get(codename="delete_plan"))
        ana = make_user("ana", OPERATOR_GROUP)

        response = owner_client.post(f"/cuenta/empleados/{ana.pk}/", employee_data(role=poderoso.pk))
        assert response.context["form"].errors["role"]

    def test_conserva_roles_que_no_administra(self, owner_client, make_user, roles):
        especial = Group.objects.create(name="Especial")
        especial.permissions.add(Permission.objects.get(codename="delete_plan"))
        ana = make_user("ana", OPERATOR_GROUP)
        ana.groups.add(especial)

        owner_client.post(f"/cuenta/empleados/{ana.pk}/", employee_data(role=roles[OPERATOR_GROUP].pk))
        assert set(ana.groups.values_list("name", flat=True)) == {OPERATOR_GROUP, "Especial"}

    def test_permiso_de_eliminar_entradas_solo_si_el_dueno_lo_tiene(self, owner_client, owner, make_user, roles):
        ana = make_user("ana", OPERATOR_GROUP)
        url = f"/cuenta/empleados/{ana.pk}/"
        assert "can_delete_entries" not in owner_client.get(url).context["form"].fields

        owner.user_permissions.add(Permission.objects.get(codename="delete_entry"))
        owner_client.post(url, employee_data(role=roles[OPERATOR_GROUP].pk, can_delete_entries="on"))
        ana = type(ana).objects.get(pk=ana.pk)
        assert ana.has_perm("parking.delete_entry")

    def test_genera_contrasena_temporal(self, owner_client, make_user):
        ana = make_user("ana", OPERATOR_GROUP)

        response = owner_client.post(f"/cuenta/empleados/{ana.pk}/contrasena/")

        ana.refresh_from_db()
        assert ana.check_password(response.context["password"])
        assert not ana.check_password("Clave-inicial-123")
        assert ana.parking_membership.must_change_password

    def test_usuario_repetido(self, owner_client, make_user, roles):
        make_user("ana", OPERATOR_GROUP)
        response = owner_client.post("/cuenta/empleados/nuevo/", employee_data(role=roles[OPERATOR_GROUP].pk))
        assert "Ya existe un usuario con este nombre" in response.content.decode()

    def test_sin_acceso_no_puede_entrar(self, client, owner_client, make_user, roles):
        ana = make_user("ana", OPERATOR_GROUP)
        owner_client.post(f"/cuenta/empleados/{ana.pk}/", employee_data(role=roles[OPERATOR_GROUP].pk, is_active=""))

        client.logout()  # owner_client es este mismo cliente
        response = client.post("/login/", {"username": "ana", "password": "Clave-inicial-123"})
        assert "Usuario o contraseña incorrectos" in response.content.decode()
        assert client.get("/parking/busqueda/").status_code == 302


@pytest.mark.django_db
class TestEmpleadosEnModal:
    MODAL = {"HTTP_X_ENTRY_MODAL": "1"}

    def test_la_tarjeta_despliega_sus_acciones_en_modal(self, owner_client, make_user):
        ana = make_user("ana", OPERATOR_GROUP, first_name="Ana")
        html = owner_client.get("/cuenta/empleados/").content.decode()
        assert f'data-bs-target="#employee-{ana.pk}"' in html          # se despliega en la lista
        assert f'data-entry-modal="/cuenta/empleados/{ana.pk}/"' in html
        assert f'data-entry-modal="/cuenta/empleados/{ana.pk}/contrasena/"' in html
        assert f'data-entry-modal="/cuenta/empleados/{ana.pk}/acceso/"' in html
        assert 'data-entry-modal="/cuenta/empleados/nuevo/"' in html

    def test_confirmaciones_en_modal(self, owner_client, make_user):
        ana = make_user("ana", OPERATOR_GROUP)
        html = owner_client.get(f"/cuenta/empleados/{ana.pk}/acceso/", **self.MODAL).content.decode()
        assert "<html" not in html and "Sí, desactivar" in html
        html = owner_client.get(f"/cuenta/empleados/{ana.pk}/contrasena/", **self.MODAL).content.decode()
        assert "<html" not in html and "Sí, generar contraseña" in html

        ana.refresh_from_db()
        assert ana.is_active and ana.check_password("Clave-inicial-123")  # abrir no cambia nada
        # Sin modal, el GET lleva a la ficha del empleado
        assert owner_client.get(f"/cuenta/empleados/{ana.pk}/acceso/").url == f"/cuenta/empleados/{ana.pk}/"

    def test_acciones_de_otro_parqueo_no_existen(self, owner_client, make_user, other_parking):
        luis = make_user("luis", OPERATOR_GROUP, parking=other_parking)
        assert owner_client.get(f"/cuenta/empleados/{luis.pk}/acceso/", **self.MODAL).status_code == 404
        assert owner_client.post(f"/cuenta/empleados/{luis.pk}/acceso/", **self.MODAL).status_code == 404

    def test_quita_y_devuelve_el_acceso(self, owner_client, make_user):
        ana = make_user("ana", OPERATOR_GROUP, first_name="Ana")
        url = f"/cuenta/empleados/{ana.pk}/acceso/"

        data = owner_client.post(url, **self.MODAL).json()
        ana.refresh_from_db()
        assert data["ok"] and "ya no puede entrar" in data["message"] and not ana.is_active
        assert "Sí, activar" in owner_client.get(url, **self.MODAL).content.decode()

        response = owner_client.post(url)  # sin modal: vuelve a la lista
        ana.refresh_from_db()
        assert response.url == "/cuenta/empleados/" and ana.is_active

    def test_editar_en_modal(self, owner_client, make_user, roles):
        ana = make_user("ana", OPERATOR_GROUP)
        url = f"/cuenta/empleados/{ana.pk}/"

        html = owner_client.get(url, **self.MODAL).content.decode()
        assert "<html" not in html and f'action="{url}"' in html
        assert "Generar contraseña temporal" not in html  # está en las opciones

        invalid = owner_client.post(url, employee_data(first_name="", role=roles[OPERATOR_GROUP].pk), **self.MODAL)
        assert invalid["Content-Type"].startswith("text/html") and "<html" not in invalid.content.decode()

        data = owner_client.post(url, employee_data(first_name="Ana María", role=roles[OPERATOR_GROUP].pk), **self.MODAL).json()
        ana.refresh_from_db()
        assert data["ok"] and ana.first_name == "Ana María"

    def test_agregar_y_contrasena_en_modal(self, owner_client, roles):
        response = owner_client.post("/cuenta/empleados/nuevo/", employee_data(role=roles[OPERATOR_GROUP].pk), **self.MODAL)
        html = response.content.decode()
        assert "<html" not in html and "Empleado creado" in html and "data-modal-dirty" in html
        assert response.context["password"] in html

        from django.contrib.auth import get_user_model
        ana = get_user_model().objects.get(username="ana")
        response = owner_client.post(f"/cuenta/empleados/{ana.pk}/contrasena/", **self.MODAL)
        assert "<html" not in response.content.decode() and "Contraseña temporal lista" in response.content.decode()
        ana.refresh_from_db()
        assert ana.check_password(response.context["password"])
