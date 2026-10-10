from functools import wraps

from django.http import Http404


def bathrooms_enabled_required(view_func):
    """El módulo de baños solo existe para parqueos que lo tienen activado."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        parking = getattr(request, "parking", None)

        if parking is None or not parking.bathrooms_enabled:
            raise Http404("Módulo de baños no disponible")

        return view_func(request, *args, **kwargs)

    return wrapper
