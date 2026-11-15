"""Exporta el borrador KYC a Word (.docx) con un formato estándar de compliance."""

from __future__ import annotations

import io

from docx import Document
from docx.shared import Pt, RGBColor

from .pipeline import KycResult
from .risk import classify

LEVEL_COLOR = {"bajo": RGBColor(0x1E, 0x7B, 0x34), "medio": RGBColor(0xB2, 0x6B, 0x00),
               "alto": RGBColor(0xC6, 0x28, 0x28), "crítico": RGBColor(0x8B, 0x00, 0x00)}


def _table(doc: Document, rows: list[tuple[str, str]]) -> None:
    t = doc.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    for k, v in rows:
        cells = t.add_row().cells
        cells[0].text, cells[1].text = k, v


def money(x: float) -> str:
    return f"S/ {x:,.0f}"


def to_docx(r: KycResult) -> bytes:
    p = r.profile
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)

    doc.add_heading(f"Borrador KYC: {p.full_name}", level=0)
    note = doc.add_paragraph(
        f"Generado por KYC OSINT el {r.generated_at} (modo {r.mode}). Borrador para revisión del oficial de "
        "cumplimiento: no constituye una decisión de aceptación. Solo fuentes públicas.")
    note.runs[0].italic = True

    doc.add_heading("1. Identificación del cliente", level=1)
    _table(doc, [
        ("Nombre", p.full_name), ("DNI", p.dni or "no declarado"),
        ("Edad", str(p.age) if p.age else "no declarada"), ("Ciudad", p.city or "no declarada"),
        ("Ocupación declarada", p.declared_occupation or "no declarada"),
        ("Empleador declarado", p.employer or "no declarado"),
        ("Monto a invertir", f"{p.currency} {p.amount:,.0f} ({money(r.wealth.declared_pen)})"),
        ("Fuente de fondos declarada", p.declared_source_of_funds or "no declarada"),
        ("Vía empresa", f"Sí: {p.company_name}" if p.via_company else "No"),
        ("Fondos del exterior", "Sí" if p.funds_from_abroad else "No"),
    ])

    doc.add_heading("2. Resumen de riesgo", level=1)
    para = doc.add_paragraph()
    run = para.add_run(f"Riesgo {r.risk.level.upper()} · DD {r.risk.dd_type} · puntaje {r.risk.score}")
    run.bold = True
    run.font.color.rgb = LEVEL_COLOR.get(r.risk.level, RGBColor(0, 0, 0))
    doc.add_paragraph(r.risk.recommendation)
    if r.risk.factors:
        _table(doc, [(f"{x.rule} (+{x.points})", x.detail) for x in r.risk.factors])
    else:
        doc.add_paragraph("No se activó ninguna regla de riesgo.")

    doc.add_heading("3. Perfil profesional", level=1)
    doc.add_paragraph(r.narrative.perfil_profesional)

    doc.add_heading("4. Exposición política (PEP)", level=1)
    doc.add_paragraph(r.narrative.exposicion_politica)

    doc.add_heading("5. Listas de sanciones", level=1)
    if r.hits:
        _table(doc, [(f"{h.source} · {h.strength} ({h.score:.0f})",
                      f"{h.listed_name} · {h.kind} · programa {h.program}") for h in r.hits])
    else:
        doc.add_paragraph(f"Sin coincidencias en OFAC SDN ni en la lista consolidada de la ONU "
                          f"(listas descargadas el {r.lists_date}).")

    doc.add_heading("6. Noticias adversas", level=1)
    doc.add_paragraph(r.narrative.noticias_adversas)

    doc.add_heading("7. Origen de la riqueza y de los fondos", level=1)
    doc.add_paragraph(r.narrative.origen_riqueza_y_fondos)
    w = r.wealth
    _table(doc, [
        ("Monto tope plausible", money(w.tope_pen)),
        ("Rango base → tope", f"{money(w.base_pen)} → {money(w.tope_pen)}"),
        ("Monto declarado / tope", f"{w.ratio:.2f}" if w.ratio is not None else "sin base"),
        ("Coherencia", w.coherence.replace("_", " ")),
        ("Componente laboral (tope)", f"{money(w.labor_tope)} · {w.occupation} · {w.career_years} años · {w.percentile_tope}"),
        ("Componente empresarial (tope)", money(w.business_tope)),
        ("Eventos de liquidez publicados", money(w.events_pen)),
    ])
    doc.add_paragraph("Supuestos: " + "; ".join(w.assumptions) + ". La ENAHO subestima los ingresos altos: "
                      "el tope es una señal para pedir sustento, no un criterio de rechazo.").runs[0].italic = True

    doc.add_heading("8. Evidencia evaluada", level=1)
    rows = []
    for e in sorted(r.findings.evidence, key=lambda x: (-x.identity_score * x.relevance_score)):
        rows.append((f"[{e.source_id}] {classify(e)}",
                     f"{e.summary} (identidad {e.identity_score:.2f}, relevancia {e.relevance_score:.2f})"))
    if rows:
        _table(doc, rows)
    doc.add_paragraph(f"Homónimos: {r.findings.homonyms_note}")

    doc.add_heading("9. Conclusión", level=1)
    doc.add_paragraph(r.narrative.conclusion)
    if r.narrative.documentos_a_solicitar:
        doc.add_paragraph("Documentos a solicitar:")
        for d in r.narrative.documentos_a_solicitar:
            doc.add_paragraph(d, style="List Bullet")

    doc.add_heading("Fuentes", level=1)
    for s in r.sources:
        doc.add_paragraph(f"[{s.id}] {s.title}. {s.url}" + (f" ({s.date})" if s.date else ""))

    doc.add_paragraph(f"Costo de este informe: US$ {r.usage.cost_usd():.2f} "
                      f"({r.usage.input_tokens:,} tokens de entrada, {r.usage.output_tokens:,} de salida, "
                      f"{r.usage.web_searches} búsquedas) · {r.seconds:.0f} s").runs[0].italic = True

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
