"""Exporta el borrador KYC a Word (.docx) con el manual de marca de la firma.

Solo da formato a un resultado ya calculado: no llama al modelo ni cuesta API.

Manual de marca aplicado:
- Tonos neutros como base (Graphite, Steel y sus transparencias); Gold solo como acento.
- Inter para títulos y Open Sans para el texto. Si la computadora no tiene esas
  fuentes instaladas, Word las reemplaza por una sans similar.
- Colores secundarios solo para el semáforo de riesgo, siempre con texto legible.
- Bloque de decisión y firmas: elaborado, revisado y aprobado.
"""

from __future__ import annotations

import io

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .pipeline import KycResult
from .risk import classify

# ---- Manual de marca ----
GOLD, SAND, GRAPHITE, STEEL, INK = "FACB00", "998867", "424242", "686B6B", "212121"
STEEL_10, STEEL_20, ORANGE_15 = "F0F0F0", "E1E1E1", "F9EFDC"
WHITE = "FFFFFF"
HEADING_FONT, BODY_FONT = "Inter", "Open Sans"
# Semáforo (fondo, texto): secundarios del manual con texto oscuro; blanco solo sobre negro
LEVEL_STYLE = {"bajo": ("4DB58D", INK), "medio": ("D59413", INK), "alto": ("E94843", INK),
               "crítico": (INK, WHITE)}
SIGNERS = [("Elaborado por", "Back Office"), ("Revisado por", "Oficial de cumplimiento"),
           ("Aprobado por", "Gerencia")]
DECISIONS = ["Aprobar", "Aprobar con DD reforzada", "Solicitar más información", "Rechazar"]


def money(x: float) -> str:
    return f"S/ {x:,.0f}"


# ---------------- Utilidades de formato ----------------

def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def _set_font(font, name: str, element=None) -> None:
    font.name = name
    if element is not None:  # para que Word respete la fuente en todos los alfabetos
        rpr = element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), name)
        # Las fuentes del tema de Word (p. ej. en "Heading 1") tienen prioridad: se quitan
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            rfonts.attrib.pop(qn(attr), None)


# Panose de cada fuente: le dice a Word que son sans serif
FONT_PANOSE = {HEADING_FONT: "020B0502030000000004", BODY_FONT: "020B0606030504020204"}


def _register_fonts(doc: Document) -> None:
    """Declara Inter y Open Sans como sans serif, con Arial de alternativa.

    Si la computadora no las tiene instaladas, Word las reemplaza por una sans y no por una serif.
    """
    for part in doc.part.package.parts:
        if str(part.partname) == "/word/fontTable.xml":
            xml = part.blob.decode("utf-8")
            extra = "".join(
                f'<w:font w:name="{name}"><w:altName w:val="Arial"/><w:panose1 w:val="{panose}"/>'
                '<w:charset w:val="00"/><w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>'
                for name, panose in FONT_PANOSE.items() if f'w:name="{name}"' not in xml)
            part._blob = xml.replace("</w:fonts>", extra + "</w:fonts>").encode("utf-8")


def _run(paragraph, text: str, *, size: float | None = None, bold: bool = False, italic: bool = False,
         color: str = INK, font: str | None = None):
    run = paragraph.add_run(text)
    run.bold, run.italic = bold, italic
    run.font.color.rgb = _rgb(color)
    if size:
        run.font.size = Pt(size)
    if font:
        _set_font(run.font, font, run._element)
    return run


def _shade(cell, fill: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def _borders(table, color: str = STEEL_20, size: int = 4) -> None:
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single" if size else "nil")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblpr.append(borders)


def _bottom_rule(paragraph, color: str = STEEL_20, size: int = 6) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", str(size)), ("w:space", "2"), ("w:color", color)):
        bottom.set(qn(k), v)
    pbdr.append(bottom)
    ppr.append(pbdr)


def _field(paragraph, instruction: str, color: str = STEEL) -> None:
    """Campo de Word (número de página, total de páginas)."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instruction)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    col = OxmlElement("w:color")
    col.set(qn("w:val"), color)
    rpr.append(col)
    run.append(rpr)
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def _cell_text(cell, text: str, *, bold: bool = False, color: str = INK, size: float | None = None,
               font: str | None = None) -> None:
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    _run(p, text, bold=bold, color=color, size=size, font=font)


def _kv_table(doc: Document, rows: list[tuple[str, str]], label_cm: float = 5.0) -> None:
    """Tabla de dos columnas: etiqueta en Steel al 10 %, valor sobre blanco."""
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    _borders(t)
    for k, v in rows:
        cells = t.add_row().cells
        cells[0].width, cells[1].width = Cm(label_cm), Cm(16.5 - label_cm)
        _shade(cells[0], STEEL_10)
        _cell_text(cells[0], k, bold=True, color=GRAPHITE)
        _cell_text(cells[1], v)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def _heading(doc: Document, text: str) -> None:
    p = doc.add_heading(level=1)
    _run(p, text, color=GRAPHITE, bold=True)
    _bottom_rule(p)


def _setup(doc: Document) -> None:
    _register_fonts(doc)
    normal = doc.styles["Normal"]
    _set_font(normal.font, BODY_FONT, normal.element)
    normal.font.size = Pt(10)
    normal.font.color.rgb = _rgb(INK)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.15
    h1 = doc.styles["Heading 1"]
    _set_font(h1.font, HEADING_FONT, h1.element)
    h1.font.size = Pt(12.5)
    h1.font.bold = True
    h1.font.color.rgb = _rgb(GRAPHITE)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)
    h1.paragraph_format.keep_with_next = True

    section = doc.sections[0]
    section.left_margin = section.right_margin = Cm(2.2)
    section.top_margin, section.bottom_margin = Cm(2.0), Cm(1.8)
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(header, "KYC OSINT", size=8, bold=True, color=GRAPHITE, font=HEADING_FONT)
    _run(header, "  ·  Borrador confidencial para revisión de cumplimiento", size=8, color=STEEL)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(footer, "Página ", size=8, color=STEEL)
    _field(footer, "PAGE")
    _run(footer, " de ", size=8, color=STEEL)
    _field(footer, "NUMPAGES")


def _brand_band(doc: Document, r: KycResult) -> None:
    """Banda Graphite con KYC en blanco y OSINT en Gold (combinación correcta del manual)."""
    band = doc.add_table(rows=1, cols=1)
    _borders(band, size=0)
    cell = band.rows[0].cells[0]
    _shade(cell, GRAPHITE)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.left_indent = Cm(0.3)
    _run(p, "KYC ", size=20, bold=True, color=WHITE, font=HEADING_FONT)
    _run(p, "OSINT", size=20, bold=True, color=GOLD, font=HEADING_FONT)
    sub = cell.add_paragraph()
    sub.paragraph_format.left_indent = Cm(0.3)
    sub.paragraph_format.space_after = Pt(8)
    _run(sub, f"Borrador de debida diligencia · modo {r.mode} · {r.generated_at}", size=9, color=STEEL_20)

    title = doc.add_paragraph()
    title.paragraph_format.space_before = Pt(12)
    title.paragraph_format.space_after = Pt(2)
    _run(title, "Borrador KYC: ", size=18, bold=True, color=GRAPHITE, font=HEADING_FONT)
    _run(title, r.profile.full_name, size=18, bold=True, color=INK, font=HEADING_FONT)
    note = doc.add_paragraph()
    _run(note, "Borrador para revisión del oficial de cumplimiento: no constituye una decisión de aceptación. "
               "Solo fuentes públicas; cada afirmación lleva su fuente [n].", size=9, italic=True, color=STEEL)


def _callout(doc: Document, text: str, fill: str = ORANGE_15) -> None:
    t = doc.add_table(rows=1, cols=1)
    _borders(t, size=0)
    cell = t.rows[0].cells[0]
    _shade(cell, fill)
    _cell_text(cell, text, bold=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def _risk_summary(doc: Document, r: KycResult) -> None:
    bg, fg = LEVEL_STYLE.get(r.risk.level, (STEEL_20, INK))
    t = doc.add_table(rows=1, cols=2)
    _borders(t, size=0)
    left, right = t.rows[0].cells
    left.width, right.width = Cm(4.0), Cm(12.5)
    _shade(left, bg)
    _cell_text(left, "RIESGO", size=8, bold=True, color=fg, font=HEADING_FONT)
    _run(left.add_paragraph(), r.risk.level.upper(), size=16, bold=True, color=fg, font=HEADING_FONT)
    _shade(right, STEEL_10)
    _cell_text(right, f"Debida diligencia {r.risk.dd_type} · puntaje {r.risk.score}", bold=True,
               color=GRAPHITE, font=HEADING_FONT)
    _run(right.add_paragraph(), r.risk.recommendation)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def _signatures(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    _run(p, "Decisión:   ", bold=True, color=GRAPHITE, font=HEADING_FONT)
    _run(p, "     ".join(f"☐ {d}" for d in DECISIONS))
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    _run(p, "Comentarios: ", bold=True, color=GRAPHITE, font=HEADING_FONT)
    _run(p, "_" * 92, color=STEEL_20)

    t = doc.add_table(rows=5, cols=3)
    t.style = "Table Grid"
    _borders(t)
    for j, (title, role) in enumerate(SIGNERS):
        head = t.rows[0].cells[j]
        _shade(head, GRAPHITE)
        _cell_text(head, title, bold=True, color=WHITE, font=HEADING_FONT)
        role_cell = t.rows[1].cells[j]
        _shade(role_cell, STEEL_10)
        _cell_text(role_cell, role, size=9, color=STEEL)
        for i, label in ((2, "Nombre:"), (3, "Firma:"), (4, "Fecha:")):
            _cell_text(t.rows[i].cells[j], label, size=9, color=STEEL)
    t.rows[3].height = Cm(1.6)
    t.rows[3].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    # El bloque de firmas no se parte entre dos páginas
    for i, row in enumerate(t.rows):
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if i < len(t.rows) - 1:
            for cell in row.cells:
                for par in cell.paragraphs:
                    par.paragraph_format.keep_with_next = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ---------------- Documento ----------------

def to_docx(r: KycResult) -> bytes:
    p = r.profile
    doc = Document()
    doc.core_properties.title = f"Borrador KYC: {p.full_name}"
    doc.core_properties.author = "KYC OSINT"
    _setup(doc)
    _brand_band(doc, r)
    if r.amount_note:
        _callout(doc, r.amount_note)

    _heading(doc, "1. Identificación del cliente")
    _kv_table(doc, [
        ("Nombre", p.full_name), ("DNI", p.dni or "no declarado"),
        ("Edad", str(p.age) if p.age else "no declarada"), ("Ciudad", p.city or "no declarada"),
        ("Ocupación declarada", p.declared_occupation or "no declarada"),
        ("Empleador declarado", p.employer or "no declarado"),
        ("Monto a invertir", f"{p.currency} {p.amount:,.0f} ({money(r.wealth.declared_pen)})"),
        ("Fuente de fondos declarada", p.declared_source_of_funds or "no declarada"),
        ("Vía empresa", f"Sí: {p.company_name}" if p.via_company else "No"),
        ("Fondos del exterior", "Sí" if p.funds_from_abroad else "No"),
    ])

    _heading(doc, "2. Resumen de riesgo")
    _risk_summary(doc, r)
    if r.risk.factors:
        _kv_table(doc, [(f"{x.rule} (+{x.points})", x.detail) for x in r.risk.factors])
    else:
        doc.add_paragraph("No se activó ninguna regla de riesgo.")

    _heading(doc, "3. Perfil profesional")
    doc.add_paragraph(r.narrative.perfil_profesional)

    _heading(doc, "4. Exposición política (PEP)")
    doc.add_paragraph(r.narrative.exposicion_politica)

    _heading(doc, "5. Listas de sanciones")
    if r.hits:
        _kv_table(doc, [(f"{h.source} · {h.strength} ({h.score:.0f})",
                         f"{h.listed_name} · {h.kind} · programa {h.program}") for h in r.hits])
    else:
        doc.add_paragraph(f"Sin coincidencias en OFAC SDN ni en la lista consolidada de la ONU "
                          f"(listas descargadas el {r.lists_date}).")

    _heading(doc, "6. Noticias adversas")
    doc.add_paragraph(r.narrative.noticias_adversas)

    _heading(doc, "7. Origen de la riqueza y de los fondos")
    doc.add_paragraph(r.narrative.origen_riqueza_y_fondos)
    w = r.wealth
    _kv_table(doc, [
        ("Monto tope plausible", f"{money(w.tope_pen)} (ahorro acumulado máximo, no sueldo)"),
        ("Rango base → tope", f"{money(w.base_pen)} → {money(w.tope_pen)}"),
        ("Monto declarado / tope", f"{w.ratio:.2f}" if w.ratio is not None else "sin base"),
        ("Coherencia", w.coherence.replace("_", " ")),
        ("Componente laboral (tope)", f"{money(w.labor_tope)} · {w.occupation} · {w.career_years} años · {w.percentile_tope}"),
        ("Componente empresarial (tope)", money(w.business_tope)),
        ("Eventos de liquidez publicados", money(w.events_pen)),
    ])
    _run(doc.add_paragraph(), "Supuestos: " + "; ".join(w.assumptions) + ". La ENAHO subestima los ingresos "
         "altos: el tope es una señal para pedir sustento, no un criterio de rechazo.", size=9, italic=True,
         color=STEEL)

    _heading(doc, "8. Evidencia evaluada")
    rows = []
    for e in sorted(r.findings.evidence, key=lambda x: (-x.identity_score * x.relevance_score)):
        rows.append((f"[{e.source_id}] {classify(e)}",
                     f"{e.summary} (identidad {e.identity_score:.2f}, relevancia {e.relevance_score:.2f})"))
    if rows:
        _kv_table(doc, rows, label_cm=3.6)
    doc.add_paragraph(f"Homónimos: {r.findings.homonyms_note}")

    _heading(doc, "9. Conclusión")
    doc.add_paragraph(r.narrative.conclusion)
    if r.narrative.documentos_a_solicitar:
        _run(doc.add_paragraph(), "Documentos a solicitar:", bold=True, color=GRAPHITE, font=HEADING_FONT)
        for d in r.narrative.documentos_a_solicitar:
            doc.add_paragraph(d, style="List Bullet")

    _heading(doc, "10. Decisión y firmas")
    _signatures(doc)

    _heading(doc, "Anexo: fuentes")
    _run(doc.add_paragraph(), f"Fuentes consultadas al generar el informe ({r.generated_at}).", size=9,
         italic=True, color=STEEL)
    for s in r.sources:
        doc.add_paragraph(f"[{s.id}] {s.title}. {s.url}" + (f" ({s.date})" if s.date else ""))

    _run(doc.add_paragraph(), f"Costo de este informe: US$ {r.usage.cost_usd():.2f} "
         f"({r.usage.input_tokens:,} tokens de entrada, {r.usage.output_tokens:,} de salida, "
         f"{r.usage.web_searches} búsquedas) · {r.seconds:.0f} s", size=8, italic=True, color=STEEL)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
