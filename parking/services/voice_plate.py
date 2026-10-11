"""
Interpreta una placa dictada por voz.

El reconocimiento de voz del navegador devuelve texto como
"pe ciento setenta y uno setecientos treinta y siete", "P 171 737"
o "placa eme cuatro cero ocho". Este módulo lo convierte en "P171737"
y busca placas conocidas parecidas para confirmar.
"""
import re
import unicodedata
from difflib import SequenceMatcher

from parking.models import Entry, PlatePolicy

# Formato flexible: 1 a 3 letras de prefijo y 2 a 7 caracteres.
# Las placas 2011 conviven con numeración alfanumérica (p. ej. P8E98).
PLATE_RE = re.compile(r"^[A-Z]{1,3}[A-Z0-9]{2,7}$")

LETTERS = {
    "a": "A", "be": "B", "ve": "V", "uve": "V", "ce": "C", "se": "C",
    "de": "D", "e": "E", "efe": "F", "ge": "G", "hache": "H", "i": "I",
    "jota": "J", "ka": "K", "ca": "K", "ele": "L", "eme": "M", "ene": "N",
    "o": "O", "pe": "P", "cu": "Q", "erre": "R", "ere": "R", "ese": "S",
    "te": "T", "u": "U", "equis": "X", "ye": "Y", "zeta": "Z", "seta": "Z",
}

UNITS = {
    "uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
}
TEENS = {
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
TENS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
HUNDREDS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}

# Letras dichas con dos palabras
LETTER_PAIRS = {
    ("i", "griega"): "Y",
    ("doble", "ve"): "W", ("doble", "u"): "W", ("doble", "uve"): "W",
}

# Palabras que no forman parte de la placa
FILLER = {
    "placa", "la", "el", "es", "numero", "num", "del", "vehiculo", "carro",
    "moto", "entrada", "salida", "entra", "sale", "ingresa", "guion",
    "espacio", "por", "favor",
}


def _normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).split()


def _read_number(tokens, i):
    """
    Lee un número dicho en palabras a partir de tokens[i].
    Devuelve (dígitos, siguiente índice) o (None, i) si no hay número.

    Un número termina cuando la palabra siguiente no puede continuarlo:
    "ciento setenta y uno setecientos" -> "171", y sigue en "setecientos".
    """
    word = tokens[i]

    if word == "cero":
        return "0", i + 1

    total, j = 0, i

    if tokens[j] == "mil":
        total, j = 1000, j + 1
    elif j + 1 < len(tokens) and tokens[j + 1] == "mil" and tokens[j] in UNITS | TEENS | TENS | HUNDREDS:
        total = (UNITS | TEENS | TENS | HUNDREDS)[tokens[j]] * 1000
        j += 2

    hundreds = tens = units = None

    if j < len(tokens) and tokens[j] in HUNDREDS:
        hundreds, j = HUNDREDS[tokens[j]], j + 1

    if j < len(tokens) and tokens[j] in TEENS:
        units, j = TEENS[tokens[j]], j + 1
    elif j < len(tokens) and tokens[j] in TENS:
        tens, j = TENS[tokens[j]], j + 1
        if j + 1 < len(tokens) and tokens[j] == "y" and tokens[j + 1] in UNITS:
            units, j = UNITS[tokens[j + 1]], j + 2
    elif j < len(tokens) and tokens[j] in UNITS:
        units, j = UNITS[tokens[j]], j + 1

    if j == i:
        return None, i

    total += (hundreds or 0) + (tens or 0) + (units or 0)
    return str(total), j


def parse_plate(text):
    """Convierte el texto dictado en una placa sin espacios (o "" si no hay)."""

    tokens = _normalize(text)
    parts = []
    i = 0

    while i < len(tokens):
        word = tokens[i]

        # Relleno solo antes de empezar la placa ("la placa es ...")
        if not parts and word in FILLER:
            i += 1
            continue

        if word in ("guion", "espacio"):
            i += 1
            continue

        pair = LETTER_PAIRS.get(tuple(tokens[i:i + 2]))
        if pair:
            parts.append(pair)
            i += 2
            continue

        # «letra e», «letra de»: la palabra siguiente es una letra. Decir
        # «letra» ayuda a que el dictado no omita una vocal suelta al final.
        if word == "letra" and i + 1 < len(tokens):
            nxt_word = tokens[i + 1]
            if nxt_word in LETTERS or re.fullmatch(r"[a-z]", nxt_word):
                parts.append(LETTERS.get(nxt_word, nxt_word.upper()))
                i += 2
                continue

        digits, nxt = _read_number(tokens, i)
        if digits is not None:
            parts.append(digits)
            i = nxt
            continue

        if word in LETTERS:
            parts.append(LETTERS[word])
        elif re.fullmatch(r"[a-z0-9]+", word) and (len(word) <= 3 or re.search(r"\d", word)):
            # El navegador ya entregó letras o dígitos: "p", "ab", "171", "p171737".
            # Palabras largas sin dígitos ("hola", "buenos") no son parte de una placa.
            parts.append(word.upper())
        i += 1

    return "".join(parts)[:10]


def is_valid_plate(plate):
    # Toda placa tiene al menos un dígito
    return bool(PLATE_RE.match(plate)) and any(c.isdigit() for c in plate)


def _similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def find_candidates(parking, plate, limit=3):
    """
    Placas conocidas parecidas: vehículos dentro del parqueo y suscripciones.
    En la salida la placa casi siempre está entre los vehículos activos.
    """
    entries = Entry.objects.for_parking(parking)
    policies = PlatePolicy.objects.for_parking(parking)

    active = {
        e.plate: e for e in entries.filter(state=True).only("plate", "entry_date_hour")
    }
    subscribed = set(policies.active().values_list("plate", flat=True))

    scored = [
        (_similarity(plate, known), known)
        for known in active.keys() | subscribed
        if known != plate
    ]
    scored = sorted((s for s in scored if s[0] >= 0.75), reverse=True)[:limit]

    return [
        {"plate": known, "active": known in active, "subscribed": known in subscribed}
        for _, known in scored
    ]


def _complete(prefix, plate):
    """
    Si ya hay una placa y lo nuevo dictado son solo letras (la letra final
    que faltó), las agrega al final: «P11017» + «E» → «P11017E».
    """
    if prefix and re.fullmatch(r"[A-Z]{1,3}", plate) and is_valid_plate(prefix + plate):
        return prefix + plate
    return plate


def interpret(parking, alternatives, prefix=""):
    """
    Recibe las alternativas del reconocimiento de voz (la primera es la más
    probable) y devuelve la placa elegida con sugerencias.

    Se prefiere la primera alternativa que coincida con una placa conocida;
    si ninguna coincide, la primera que tenga formato válido.

    `prefix` es la placa ya mostrada: permite dictar solo la letra que faltó.
    """
    prefix = prefix if is_valid_plate(prefix or "") else ""
    parsed = [
        (text, _complete(prefix, parse_plate(text)))
        for text in alternatives if text and text.strip()
    ]
    valid = [(text, plate) for text, plate in parsed if is_valid_plate(plate)]

    if not valid:
        heard = parsed[0][0] if parsed else ""
        return {"ok": False, "heard": heard, "plate": parsed[0][1] if parsed else ""}

    entries = Entry.objects.for_parking(parking)
    policies = PlatePolicy.objects.for_parking(parking)

    known = set(entries.filter(state=True, plate__in=[p for _, p in valid]).values_list("plate", flat=True))
    known |= set(policies.active().filter(plate__in=[p for _, p in valid]).values_list("plate", flat=True))

    heard, plate = next(((t, p) for t, p in valid if p in known), valid[0])

    active_entry = entries.filter(plate=plate, state=True).only("entry_date_hour").first()

    # Otras lecturas del dictado (p. ej. con la letra final que la primera
    # omitió) se ofrecen junto a las placas conocidas parecidas
    candidates = find_candidates(parking, plate)
    offered = {plate} | {c["plate"] for c in candidates}
    for _, other in valid:
        if other not in offered and len(candidates) < 5:
            offered.add(other)
            candidates.append({"plate": other, "active": other in known, "subscribed": False})

    return {
        "ok": True,
        "heard": heard,
        "plate": plate,
        "action": "salida" if active_entry else "entrada",
        "entry_date_hour": active_entry.entry_date_hour if active_entry else None,
        "candidates": candidates,
    }
