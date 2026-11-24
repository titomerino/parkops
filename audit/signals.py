"""Inicios de sesión, cierres e intentos fallidos."""
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from audit.services import Action, record


def _parking_of(user):
    membership = getattr(user, "parking_membership", None) if user else None
    return membership.parking if membership else None


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record(request, Action.LOGIN, "Inició sesión", user=user, parking=_parking_of(user))


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record(request, Action.LOGOUT, "Cerró sesión", user=user, parking=_parking_of(user))


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get("username", "")[:150]
    # Solo se asocia al parqueo si el usuario existe; los nombres inventados quedan solo en el admin
    user = get_user_model().objects.filter(username=username).select_related("parking_membership__parking").first()
    record(
        request, Action.LOGIN_FAILED, "Contraseña incorrecta" if user else "Usuario que no existe",
        target=username, parking=_parking_of(user), username=username,
    )
