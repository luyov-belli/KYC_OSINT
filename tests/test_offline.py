"""Pruebas sin API: reglas de riesgo, monto tope e informe Word con hallazgos armados a mano."""

from kyc import llm, risk, sanctions, wealth
from kyc.pipeline import KycResult
from kyc.report import to_docx
from kyc.schemas import (EvidenceAssessment, Findings, KycNarrative, LiquidityEvent,
                         PepAssessment, ProfileInput, SourceDoc, WealthSignals)


def make_findings(pep="no", adverse=False, group=2, seniority="senior", owner=False, size="ninguna",
                  career_years=None, events=None):
    evidence = [EvidenceAssessment(
        source_id=1, summary="Gerente en una empresa formal", category="empleo_cargo",
        source_type="web_empresa", identity_score=0.9, identity_reason="empleador coincide",
        relevance_score=0.6, relevance_reason="respalda ingresos", risk_direction="reduce")]
    if adverse:
        evidence.append(EvidenceAssessment(
            source_id=2, summary="Investigación fiscal por lavado de activos", category="noticia_adversa",
            source_type="medio", identity_score=0.85, identity_reason="DNI coincide",
            relevance_score=0.95, relevance_reason="LA/FT", risk_direction="aumenta"))
    evidence.append(EvidenceAssessment(
        source_id=3, summary="Homónimo con sentencia en otra región", category="sancion_o_proceso",
        source_type="medio", identity_score=0.15, identity_reason="edad incompatible",
        relevance_score=0.9, relevance_reason="proceso penal", risk_direction="aumenta"))
    return Findings(
        identity_summary="Profesional en Lima",
        evidence=evidence,
        pep=PepAssessment(is_pep=pep, relation="titular" if pep != "no" else "ninguna",
                          role="Exgerente regional" if pep != "no" else None, rationale="prueba"),
        wealth=WealthSignals(occupation_group=group, occupation_label="prueba", career_years=career_years,
                             seniority=seniority, business_owner=owner, business_size=size,
                             liquidity_events=events or [], rationale="prueba"),
        homonyms_note="Un homónimo descartado por edad",
    )


def test_homonym_is_discarded_even_if_relevant():
    f = make_findings()
    assert risk.classify(f.evidence[-1]) == "descartada"


def test_clean_profile_low_risk():
    p = ProfileInput(full_name="Persona Ficticia", age=48, amount=150_000, currency="USD")
    f = make_findings()
    w = wealth.estimate(p, f.wealth)
    r = risk.assess(p, [], f, w)
    assert w.tope_pen > w.base_pen > 0
    assert r.level in ("bajo", "medio")


def test_adverse_media_and_pep_force_edd():
    p = ProfileInput(full_name="Persona Ficticia", age=55, amount=100_000, currency="USD")
    f = make_findings(pep="si", adverse=True)
    w = wealth.estimate(p, f.wealth)
    r = risk.assess(p, [], f, w)
    assert r.dd_type == "reforzada"
    assert r.level in ("alto", "crítico")


def test_amount_far_above_ceiling_is_incoherent():
    p = ProfileInput(full_name="Persona Ficticia", age=40, amount=5_000_000, currency="USD")
    f = make_findings(group=5, seniority="intermedio")
    w = wealth.estimate(p, f.wealth)
    assert w.coherence == "incoherente"


def test_liquidity_event_raises_ceiling():
    p = ProfileInput(full_name="Persona Ficticia", age=40, amount=100_000, currency="PEN")
    without = wealth.estimate(p, make_findings().wealth)
    with_event = wealth.estimate(p, make_findings(events=[
        LiquidityEvent(description="Venta de inmueble", amount_pen=800_000, source_id=1)]).wealth)
    assert with_event.tope_pen - without.tope_pen == 800_000


def test_strong_sanction_hit_is_critical():
    p = ProfileInput(full_name="Persona Ficticia", age=40, amount=10_000)
    hit = sanctions.SanctionHit("OFAC SDN", "1", "X", "X", "individual", "SDNTK", "", 100.0, "fuerte")
    f = make_findings()
    r = risk.assess(p, [hit], f, wealth.estimate(p, f.wealth))
    assert r.level == "crítico"


def test_docx_builds():
    p = ProfileInput(full_name="Persona Ficticia", age=48, amount=150_000)
    f = make_findings(adverse=True)
    w = wealth.estimate(p, f.wealth)
    res = KycResult(
        profile=p, mode="sintético", hits=[], lists_date="2026-11-15",
        sources=[SourceDoc(id=i, url=f"https://ejemplo.pe/{i}", title=f"Fuente {i}") for i in (1, 2, 3)],
        dossier="", findings=f, wealth=w, risk=risk.assess(p, [], f, w),
        narrative=KycNarrative(perfil_profesional="a [1]", exposicion_politica="b", noticias_adversas="c [2]",
                               origen_riqueza_y_fondos="d", conclusion="e", documentos_a_solicitar=["f"]),
        usage=llm.UsageTracker(), seconds=1.0)
    data = to_docx(res)
    assert data[:2] == b"PK" and len(data) > 10_000
