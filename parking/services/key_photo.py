"""Foto de la llave en custodia: se valida y se deja liviana antes de guardarla."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

# El celular ya la reduce; esto es el respaldo del servidor
MAX_SIDE = 1024
QUALITY = 75
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class KeyPhotoError(Exception):
    """Error mostrable al usuario."""


def optimize(data):
    """Devuelve la foto en JPEG con lado mayor ≤ MAX_SIDE (normalmente 40–100 KB)."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise KeyPhotoError("La foto está vacía o es demasiado grande.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise KeyPhotoError("El archivo no es una imagen válida.")

    # Respeta la orientación con la que se tomó la foto
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=QUALITY, optimize=True)
    return out.getvalue()
