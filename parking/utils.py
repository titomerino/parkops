def minutes_to_hours_and_minutes(total_minutes: int):
    hours = total_minutes // 60
    minutes = total_minutes % 60

    return f"{hours:02d}", f"{minutes:02d}"


def format_plate(plate: str) -> str:
    """
    Formatea una placa así:
    - Primera letra sola
    - El resto agrupado de derecha a izquierda en bloques de 3

    Ej:
    P40807  -> P 40 807
    P8E98   -> P 8 E98
    P911116 -> P 911 116
    """

    if not plate:
        return ""

    plate = plate.strip().upper()

    if len(plate) <= 1:
        return plate

    first = plate[0]
    rest = plate[1:]

    # Calcular tamaño del primer grupo (lo que sobra al dividir entre 3)
    remainder = len(rest) % 3

    groups = []

    if remainder:
        groups.append(rest[:remainder])

    for i in range(remainder, len(rest), 3):
        groups.append(rest[i:i+3])

    return f"{first} {' '.join(groups)}"