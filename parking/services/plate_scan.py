"""
Lee la placa de una foto con la API de Anthropic (Claude).

La foto llega ya recortada al recuadro de la placa desde el navegador.
Aquí se valida, se limita el tamaño (el costo depende de los píxeles,
no del peso del archivo) y se registra cada lectura con su costo.
"""
import base64
import io
import re
from decimal import Decimal

from django.db.models import Sum
from django.utils.timezone import localdate
from PIL import Image, UnidentifiedImageError

from parking.models import PlateScan
from tenants.models import AiSettings, AiTopUp

# Lado mayor máximo que se envía: el recorte de la placa no necesita más
MAX_SIDE = 800
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
NONE_WORD = "NINGUNA"

PROMPT = (
    "Lee la placa de vehículo (El Salvador) en la imagen. "
    "Responde solo los caracteres de la placa, sin espacios ni guiones (ej.: P123456, P11017E). "
    "Si dudas entre caracteres parecidos (0/O, 8/B, 1/I, 5/S), da hasta 3 lecturas "
    "separadas por coma, la más probable primero. "
    f"Si no hay una placa legible responde {NONE_WORD}."
)


class PlateScanError(Exception):
    """Error mostrable al usuario."""


# Con este porcentaje usado se avisa al administrador que el paquete se acaba
LOW_QUOTA_RATIO = 0.8


def included_scans(parking):
    """Escaneos que incluyen los planes activos del parqueo (Suscripción → Plan → IA)."""
    from payment.models import Subscription

    return (
        Subscription.objects.filter(parking=parking, active=True, plan__ai_package__isnull=False)
        .aggregate(total=Sum("plan__ai_package__scans"))["total"] or 0
    )


def top_up_scans(parking, month=None):
    month = month or localdate().replace(day=1)
    return (
        AiTopUp.objects.filter(parking=parking, month=month)
        .aggregate(total=Sum("scans"))["total"] or 0
    )


def is_enabled(parking):
    """
    El parqueo tiene IA (en su plan o con una recarga del mes) y hay una
    API key configurada.
    """
    if not parking or not AiSettings.load().effective_api_key:
        return False
    return included_scans(parking) > 0 or top_up_scans(parking) > 0


def quota(parking):
    """Uso del mes: IA incluida en el plan + recargas del mes."""
    used = PlateScan.objects.for_parking(parking).this_month().count()
    limit = included_scans(parking) + top_up_scans(parking)
    remaining = max(0, limit - used)

    return {
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "exhausted": remaining == 0,
        "low": 0 < remaining and used >= limit * LOW_QUOTA_RATIO,
    }


def prepare_image(data):
    """Valida la imagen y la deja en JPEG de lado mayor ≤ MAX_SIDE."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise PlateScanError("La imagen está vacía o es demasiado grande.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise PlateScanError("El archivo no es una imagen válida.")

    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def parse_readings(text):
    """«P11O17E, P11017E» → ["P11O17E", "P11017E"]; NINGUNA → []."""
    readings = []
    for part in re.split(r"[,\n;/]+", text.upper()):
        plate = re.sub(r"[^A-Z0-9]", "", part)
        if plate and plate != NONE_WORD and plate not in readings:
            readings.append(plate[:10])
    return readings[:3]


def _client(api_key):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, timeout=20, max_retries=1)


def _cost(config, input_tokens, output_tokens):
    usd = (input_tokens * config.price_input + output_tokens * config.price_output) / Decimal(1_000_000)
    return usd.quantize(Decimal("0.000001"))


def read_plate(parking, user, image_data):
    """
    Envía el recorte a Claude, registra la lectura y devuelve las lecturas
    posibles (la más probable primero).
    """
    jpeg = prepare_image(image_data)
    config = AiSettings.load()

    try:
        message = _client(config.effective_api_key).messages.create(
            model=config.model,
            max_tokens=40,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.b64encode(jpeg).decode(),
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
    except Exception as error:  # red, clave inválida, límite de la API...
        raise PlateScanError("No se pudo leer la placa en este momento. Intenta de nuevo.") from error

    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    usage = message.usage

    PlateScan.objects.create(
        parking=parking,
        user=user if user and user.is_authenticated else None,
        plate=text.strip()[:50],
        model=config.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost=_cost(config, usage.input_tokens, usage.output_tokens),
    )

    return parse_readings(text)
