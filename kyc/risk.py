"""Motor de reglas de riesgo: transparente y auditable, sin LLM.

Cada regla suma puntos y deja una razón escrita. El puntaje total define el
nivel de riesgo, y algunos disparadores obligan a la DD reforzada aunque el
puntaje sea bajo (enfoque basado en riesgo).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .sanctions import SanctionHit
from .schemas import EvidenceAssessment, Findings, ProfileInput
from .wealth import WealthEstimate

IDENTITY_MIN = 0.7      # desde aquí, la fuente habla de la misma persona
RELEVANCE_MIN = 0.5     # desde aquí, la fuente pesa para el riesgo o el SoW
HOMONYM_MAX = 0.4       # por debajo, se descarta como homónimo
EDD_AMOUNT_USD = 500_000  # umbral de la firma para DD reforzada por monto

LEVELS = [(100, "crítico"), (40, "alto"), (15, "medio"), (0, "bajo")]
DD_BY_LEVEL = {"crítico": "reforzada", "alto": "reforzada", "medio": "estándar", "bajo": "simplificada"}


@dataclass
class RiskFactor:
    rule: str
    detail: str
    points: int
    forces_edd: bool = False


@dataclass
class RiskResult:
    score: int
    level: str
    dd_type: str
    factors: list[RiskFactor] = field(default_factory=list)
    recommendation: str = ""


def classify(e: EvidenceAssessment) -> str:
    """Ubica cada evidencia en el espectro: considerada, contexto o descartada."""
    if e.identity_score < HOMONYM_MAX:
        return "descartada"
    if e.identity_score >= IDENTITY_MIN and e.relevance_score >= RELEVANCE_MIN:
        return "considerada"
    return "contexto"


def assess(profile: ProfileInput, hits: list[SanctionHit], findings: Findings,
           wealth: WealthEstimate) -> RiskResult:
    f: list[RiskFactor] = []

    strong = [h for h in hits if h.strength == "fuerte"]
    possible = [h for h in hits if h.strength == "posible"]
    if strong:
        h = strong[0]
        f.append(RiskFactor("Lista de sanciones", f"Coincidencia fuerte con {h.source} ({h.matched_on}, "
                            f"programa {h.program}, similitud {h.score:.0f})", 100, True))
    elif possible:
        h = possible[0]
        f.append(RiskFactor("Lista de sanciones", f"Coincidencia posible con {h.source} ({h.matched_on}, "
                            f"similitud {h.score:.0f}): confirmar con fecha de nacimiento o documento", 30))

    if findings.pep.is_pep == "si":
        f.append(RiskFactor("PEP", f"{findings.pep.relation}: {findings.pep.role or findings.pep.rationale}", 40, True))
    elif findings.pep.is_pep == "posible":
        f.append(RiskFactor("PEP", f"Posible PEP: {findings.pep.rationale}", 20, True))

    adverse = [e for e in findings.evidence
               if classify(e) == "considerada" and e.risk_direction == "aumenta"
               and e.category in ("noticia_adversa", "sancion_o_proceso")]
    for e in sorted(adverse, key=lambda x: -x.relevance_score)[:2]:
        f.append(RiskFactor("Noticia adversa", f"[{e.source_id}] {e.summary}", 35))

    if wealth.coherence == "incoherente":
        f.append(RiskFactor("Origen de la riqueza", f"El monto declarado es {wealth.ratio:.1f}× el tope plausible "
                            f"(S/ {wealth.tope_pen:,.0f})", 35))
    elif wealth.coherence == "pedir_sustento":
        f.append(RiskFactor("Origen de la riqueza", f"El monto declarado es el {wealth.ratio:.0%} del tope "
                            f"plausible: pedir sustento documentario", 15))
    elif wealth.coherence == "sin_base":
        f.append(RiskFactor("Origen de la riqueza", "Sin base pública para estimar el patrimonio", 10))

    amount_usd = wealth.declared_pen / wealth.fx
    if amount_usd >= EDD_AMOUNT_USD:
        f.append(RiskFactor("Monto", f"US$ {amount_usd:,.0f} supera el umbral de US$ {EDD_AMOUNT_USD:,}", 15, True))
    if profile.via_company:
        f.append(RiskFactor("Beneficiario final", f"Invierte vía empresa ({profile.company_name or 'sin nombre'}): "
                            "identificar al beneficiario final", 15, True))
    if profile.funds_from_abroad:
        f.append(RiskFactor("Riesgo geográfico", "Fondos provenientes del exterior: verificar jurisdicción de origen", 15))

    if not any(classify(e) == "considerada" for e in findings.evidence):
        f.append(RiskFactor("Huella pública", "Ninguna fuente pública relevante confirma su perfil", 10))

    score = sum(x.points for x in f)
    level = next(name for threshold, name in LEVELS if score >= threshold)
    dd = DD_BY_LEVEL[level]
    if dd != "reforzada" and any(x.forces_edd for x in f):
        dd = "reforzada"

    if level == "crítico":
        rec = "Escalar al oficial de cumplimiento antes de cualquier contacto comercial. Posible rechazo."
    elif dd == "reforzada":
        rec = "Debida diligencia reforzada: sustento documentario de fondos y aprobación de la gerencia."
    elif dd == "estándar":
        rec = "Debida diligencia estándar: completar el sustento de fondos antes de la apertura."
    else:
        rec = "Debida diligencia simplificada: perfil coherente con la información pública."
    return RiskResult(score=score, level=level, dd_type=dd, factors=f, recommendation=rec)
