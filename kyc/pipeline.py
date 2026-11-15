"""Orquesta el flujo completo: sanciones → OSINT → extracción → patrimonio → riesgo → redacción.

Es un flujo determinista: el código decide el orden de los pasos y Claude solo
actúa dentro de cada uno. En modo sintético, las fuentes vienen de un fixture
y se salta la búsqueda web; todo lo demás es idéntico.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

import anthropic

from . import llm, osint, risk, sanctions, wealth
from .schemas import Findings, KycNarrative, ProfileInput, SourceDoc

Progress = Callable[[str], None]


@dataclass
class KycResult:
    profile: ProfileInput
    mode: str                                  # "en vivo" | "sintético"
    hits: list[sanctions.SanctionHit]
    lists_date: str
    sources: list[SourceDoc]
    dossier: str
    findings: Findings
    wealth: wealth.WealthEstimate
    risk: risk.RiskResult
    narrative: KycNarrative
    usage: llm.UsageTracker
    seconds: float
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    def source(self, source_id: int) -> SourceDoc | None:
        return next((s for s in self.sources if s.id == source_id), None)


def run(profile: ProfileInput, client: anthropic.Anthropic, *,
        sources: list[SourceDoc] | None = None, dossier: str = "",
        progress: Progress = lambda _: None) -> KycResult:
    t0 = time.time()
    tracker = llm.UsageTracker()
    mode = "sintético" if sources is not None else "en vivo"

    progress("Cruzando listas de sanciones OFAC y ONU")
    hits = sanctions.screen(profile.full_name)
    if profile.via_company and profile.company_name:
        hits += sanctions.screen(profile.company_name)

    if sources is None:
        progress("Buscando en fuentes públicas peruanas")
        sources, dossier = osint.research(client, profile, tracker)

    progress(f"Evaluando {len(sources)} fuentes: identidad y relevancia")
    findings = llm.extract_findings(client, profile, sources, dossier, tracker)

    progress("Estimando el monto tope plausible (ENAHO 2024 + BCRP)")
    w = wealth.estimate(profile, findings.wealth)

    progress("Aplicando reglas de riesgo")
    r = risk.assess(profile, hits, findings, w)

    progress("Redactando el borrador KYC")
    context = {
        "cliente": profile.model_dump(),
        "sanciones": [asdict(h) for h in hits] or f"Sin coincidencias en OFAC SDN ni ONU ({sanctions.lists_date()})",
        "identidad": findings.identity_summary,
        "pep": findings.pep.model_dump(),
        "evidencia": [
            {**e.model_dump(), "clasificacion": risk.classify(e)} for e in findings.evidence
        ],
        "homonimos": findings.homonyms_note,
        "fuentes": [{"id": s.id, "titulo": s.title, "url": s.url, "fecha": s.date} for s in sources],
        "patrimonio": {
            "monto_declarado_soles": round(w.declared_pen),
            "monto_tope_plausible_soles": round(w.tope_pen),
            "rango_base_a_tope_soles": [round(w.base_pen), round(w.tope_pen)],
            "ratio_declarado_tope": round(w.ratio, 2) if w.ratio is not None else None,
            "coherencia": w.coherence,
            "ocupacion": w.occupation,
            "senales": findings.wealth.model_dump(),
            "supuestos": w.assumptions,
        },
        "riesgo": {"nivel": r.level, "puntaje": r.score, "tipo_dd": r.dd_type,
                   "factores": [asdict(x) for x in r.factors], "recomendacion": r.recommendation},
    }
    narrative = llm.write_narrative(client, context, tracker)

    return KycResult(profile=profile, mode=mode, hits=hits, lists_date=sanctions.lists_date(),
                     sources=sources, dossier=dossier, findings=findings, wealth=w, risk=r,
                     narrative=narrative, usage=tracker, seconds=time.time() - t0)
