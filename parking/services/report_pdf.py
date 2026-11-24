"""PDF de los reportes de parqueo con ReportLab.

Antes se generaban con WeasyPrint (HTML → PDF): un mes de ~4,200 entradas tardaba
~11 s y usaba ~880 MB de memoria por petición. ReportLab dibuja el mismo PDF en
menos de 1 s con ~40 MB. WeasyPrint se sigue usando para las facturas (una página).

Recibe el mismo contexto que arma report_service (generate_*_report).
"""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils.timezone import localtime
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

BLUE = colors.HexColor("#0d6efd")
DARK = colors.HexColor("#212529")
GREY = colors.HexColor("#cccccc")
ZEBRA = colors.HexColor("#f4f5f7")
MUTED = colors.HexColor("#444444")

STYLES = {
    "brand": ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=16, textColor=DARK),
    "header": ParagraphStyle("header", fontName="Helvetica", fontSize=9, leading=12, alignment=TA_RIGHT),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=14, alignment=TA_CENTER, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica-Oblique", fontSize=10, alignment=TA_CENTER, spaceAfter=10),
    "total": ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=13, alignment=TA_RIGHT, spaceBefore=4, spaceAfter=8),
    "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=4),
    "box": ParagraphStyle("box", fontName="Helvetica", fontSize=9, leading=13, alignment=TA_CENTER),
    "note": ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8.5, leading=11, textColor=MUTED, spaceBefore=10),
}

NOTES = {
    "day": (
        "Las entradas por suscripción mensual y las entradas sin salida registrada se consideran "
        "con un monto de $0; por tanto, no contribuyen al total de ingresos del día."
    ),
    "month": (
        "Las entradas por suscripción mensual se registran con un monto de $0, pero el valor de la "
        "suscripción se agrega a los ingresos totales.<br/>Las entradas sin salida registrada se "
        "consideran con un monto de $0."
    ),
    "plate": (
        "<b>Tipo de contrato</b> es el contrato vigente al generar el reporte (si hay montos que no "
        "corresponden al contrato, posiblemente se modificó recientemente).<br/>Si la placa tiene un "
        "contrato mensual vigente, sus entradas se registran con $0 y el valor de la suscripción se "
        "muestra en el resumen, pero no se suma al total del reporte.<br/>Las entradas sin salida "
        "registrada se consideran con un monto de $0."
    ),
}


def money(value):
    return f"${value or 0:,.2f}"


def long_date(value):
    """24 de noviembre de 2026 - 02:52 PM (sin depender del idioma del sitio)."""
    value = localtime(value)
    return f"{value.day} de {MONTHS[value.month - 1]} de {value.year} - {value:%I:%M %p}"


def short_datetime(value):
    return localtime(value).strftime("%d/%m - %I:%M %p") if value else "—"


class NumberedCanvas(canvas.Canvas):
    """Pie «página n / N»: guarda las páginas y las numera al final."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for page in self._pages:
            self.__dict__.update(page)
            self.setFont("Helvetica", 8)
            self.setFillColor(MUTED)
            self.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"{self._pageNumber} / {total}")
            super().showPage()
        super().save()


def _header(context):
    parking = context.get("parking")
    lines = [f"<b>{escape(parking.name if parking else 'ParkOps')}</b>"]
    if parking and parking.address:
        lines.append(escape(parking.address))
    lines.append(long_date(context["today"]))
    table = Table(
        [[Paragraph("ParkOps", STYLES["brand"]), Paragraph("<br/>".join(lines), STYLES["header"])]],
        colWidths=["40%", "60%"],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 2, BLUE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [table, Spacer(1, 14)]


def _summary(summary):
    cells = []
    for item in summary:
        if "text" in item:
            body = f"<b>{escape(item['title'])}</b><br/>{escape(str(item['text']))}"
        else:
            body = f"<b>{escape(item['title'])}</b><br/>Total: {item['count']}<br/><b>Ingresos: {money(item['income'])}</b>"
        cells.append(Paragraph(body, STYLES["box"]))
    table = Table([cells], colWidths=[f"{100 / len(cells):.4f}%"] * len(cells))
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [table, Spacer(1, 6)]


def _grid(rows, col_widths, right_cols=(), total_row=False):
    """Tabla con encabezado oscuro que se repite en cada página."""
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for col in right_cols:
        style.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
    if total_row:
        style += [
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e9ecef")),
        ]
    table.setStyle(TableStyle(style))
    return table


def _detail(context):
    with_type = not context.get("policy")
    head = ["Placa", "Entrada", "Salida", "Tiempo"] + (["Tipo de cobro"] if with_type else []) + ["Monto"]
    rows = [head]
    for entry in context["entries"]:
        row = [entry.plate, short_datetime(entry.entry_date_hour), short_datetime(entry.departure_date_hour), entry.duration]
        if with_type:
            row.append(f"{entry.type}{f' - {entry.fee.name}' if entry.fee else ''}")
        row.append(money(entry.final_amount))
        rows.append(row)
    if len(rows) == 1:
        rows.append(["No hay entradas para mostrar"] + [""] * (len(head) - 1))
    # Ancho útil: 18 cm (A4 con márgenes de 1.5 cm) menos el relleno del marco ≈ 17.6 cm
    if with_type:
        widths = [2.5 * cm, 3.2 * cm, 3.2 * cm, 1.7 * cm, 4.9 * cm, 2.1 * cm]
    else:
        widths = [3.1 * cm, 4.5 * cm, 4.5 * cm, 2.4 * cm, 3.1 * cm]
    table = _grid(rows, widths, right_cols=(len(head) - 1,))
    if len(rows) == 2 and rows[1][0].startswith("No hay"):
        table.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1)), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Oblique")]))
    return [table]


def _days(context):
    rows = [["Día", "Entradas", "Tarifas", "Suscripción diaria", "Total"]]
    for day in context["days"]:
        rows.append([day["label"], day["count"], money(day["normal"]), money(day["daily"]), money(day["total"])])
    count = sum(day["count"] for day in context["days"])
    rows.append(["Total", count, money(sum(d["normal"] for d in context["days"])),
                 money(sum(d["daily"] for d in context["days"])), money(sum(d["total"] for d in context["days"]))])
    story = [Paragraph("Ingresos por día", STYLES["section"]),
             _grid(rows, [3.3 * cm, 2.6 * cm, 3.9 * cm, 4.3 * cm, 3.5 * cm], right_cols=(2, 3, 4), total_row=True)]
    if context.get("monthly_income"):
        story.append(Paragraph(
            f"Más suscripciones mensuales del mes: <b>{money(context['monthly_income'])}</b>",
            ParagraphStyle("monthly", parent=STYLES["box"], alignment=TA_RIGHT, spaceBefore=4),
        ))
    return story


def build_report_pdf(kind, context, include_detail=True):
    """kind: "day", "month" o "plate". El mes lleva el resumen por día; el detalle es opcional."""
    titles = {
        "day": ("Reporte de ingresos del día", f"Día: {context.get('date', '')}"),
        "month": ("Reporte de ingresos del mes", f"Mes: {context.get('date', '')}"),
        "plate": (f"Reporte de ingresos de la placa {context.get('plate', '')}",
                  f"Período: {context.get('start_date', '')} - {context.get('end_date', '')}"),
    }
    title, subtitle = titles[kind]

    story = _header(context)
    story += [
        Paragraph(escape(title).upper(), STYLES["title"]),
        Paragraph(escape(subtitle), STYLES["subtitle"]),
        Paragraph(f"Total ingresos: {money(context['total_income'])}", STYLES["total"]),
    ]
    story += _summary(context["summary"])
    if kind == "month":
        story += _days(context)
    if include_detail:
        if kind == "month":
            story.append(Paragraph(f"Detalle de entradas ({len(context['entries'])})", STYLES["section"]))
        story += _detail(context)
        story.append(Paragraph(f"Total ingresos: {money(context['total_income'])}", STYLES["total"]))
    story.append(Paragraph(f"Notas:<br/>{NOTES[kind]}", STYLES["note"]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=title, author="ParkOps",
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
