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

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from parking.models import PlateScan

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


def is_available(parking):
    return bool(settings.ANTHROPIC_API_KEY and parking and parking.plate_scan_enabled)


def remaining_this_month(parking):
    """Escaneos que quedan en el mes, o None si el parqueo no tiene límite."""
    limit = parking.plate_scan_monthly_limit
    if limit is None:
        return None
    return max(0, limit - PlateScan.objects.for_parking(parking).this_month().count())


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


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=20, max_retries=1)


def _cost(input_tokens, output_tokens):
    price_in, price_out = settings.PLATE_SCAN_PRICE_PER_MTOK
    usd = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return Decimal(str(round(usd, 6)))


def read_plate(parking, user, image_data):
    """
    Envía el recorte a Claude, registra la lectura y devuelve las lecturas
    posibles (la más probable primero).
    """
    jpeg = prepare_image(image_data)

    try:
        message = _client().messages.create(
            model=settings.PLATE_SCAN_MODEL,
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
        model=settings.PLATE_SCAN_MODEL,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost=_cost(usage.input_tokens, usage.output_tokens),
    )

    return parse_readings(text)
