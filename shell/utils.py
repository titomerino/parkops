from django.utils.http import url_has_allowed_host_and_scheme


def safe_redirect_url(request, url):
    """Devuelve la URL solo si apunta a este mismo sitio; si no, None."""

    if url and url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return url

    return None
