from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def perm_required(perm):
    """
    Sin sesión → login (conserva ?next=).
    Con sesión pero sin permiso → 403.
    """

    def decorator(view_func):

        @wraps(view_func)
        def wrapper(request, *args, **kwargs):

            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            if not request.user.has_perm(perm):
                raise PermissionDenied

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def superuser_required(view_func):
    """
    Solo superusuarios (admin root).
    Sin sesión → login; con sesión pero sin ser superusuario → 403.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        if not request.user.is_superuser:
            raise PermissionDenied

        return view_func(request, *args, **kwargs)

    return wrapper
