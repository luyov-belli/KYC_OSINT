"""Orquesta el flujo completo: sanciones → OSINT → extracción → patrimonio → riesgo → redacción.

Es un flujo determinista: el código decide el orden de los pasos y Claude solo
actúa dentro de cada uno. En modo sintético, las fuentes vienen de un fixture
y se salta la búsqueda web; todo lo demás es idéntico.

`save`/`load` guardan un resultado en JSON (los sintéticos van precalculados en
`fixtures/resultados/`, así mostrarlos no consume API). `with_amount` recalcula
monto tope, coherencia y riesgo con otro monto declarado, sin llamar al modelo.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
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
    amount_note: str = ""   # se llena si el monto se simuló después de redactar

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


# ---------------- Monto simulado (sin LLM) ----------------

def with_amount(r: KycResult, amount: float, currency: str) -> KycResult:
    """Recalcula monto tope, coherencia, riesgo y DD con otro monto declarado.

    Usa las mismas señales que ya extrajo el modelo: es Python puro y no cuesta API.
    El texto del borrador no se vuelve a redactar; queda una nota que lo advierte.
    """
    if amount == r.profile.amount and currency == r.profile.currency:
        return r
    profile = r.profile.model_copy(update={"amount": float(amount), "currency": currency})
    w = wealth.estimate(profile, r.findings.wealth)
    rk = risk.assess(profile, r.hits, r.findings, w)
    note = (f"Monto simulado: {currency} {amount:,.0f}. El monto tope, la coherencia, el riesgo y la DD se "
            f"recalcularon sin volver a consultar al modelo. El texto del borrador se redactó con el monto "
            f"original ({r.profile.currency} {r.profile.amount:,.0f}).")
    return replace(r, profile=profile, wealth=w, risk=rk, amount_note=note)


# ---------------- Guardar y cargar (JSON) ----------------

def to_dict(r: KycResult) -> dict:
    return {
        "profile": r.profile.model_dump(mode="json"),
        "mode": r.mode,
        "hits": [asdict(h) for h in r.hits],
        "lists_date": r.lists_date,
        "sources": [s.model_dump(mode="json") for s in r.sources],
        "dossier": r.dossier,
        "findings": r.findings.model_dump(mode="json"),
        "wealth": asdict(r.wealth),
        "risk": asdict(r.risk),
        "narrative": r.narrative.model_dump(mode="json"),
        "usage": asdict(r.usage),
        "seconds": r.seconds,
        "generated_at": r.generated_at,
        "amount_note": r.amount_note,
    }


def from_dict(d: dict) -> KycResult:
    rk = d["risk"]
    return KycResult(
        profile=ProfileInput.model_validate(d["profile"]),
        mode=d["mode"],
        hits=[sanctions.SanctionHit(**h) for h in d["hits"]],
        lists_date=d["lists_date"],
        sources=[SourceDoc.model_validate(s) for s in d["sources"]],
        dossier=d.get("dossier", ""),
        findings=Findings.model_validate(d["findings"]),
        wealth=wealth.WealthEstimate(**d["wealth"]),
        risk=risk.RiskResult(score=rk["score"], level=rk["level"], dd_type=rk["dd_type"],
                             factors=[risk.RiskFactor(**x) for x in rk["factors"]],
                             recommendation=rk["recommendation"]),
        narrative=KycNarrative.model_validate(d["narrative"]),
        usage=llm.UsageTracker(**d["usage"]),
        seconds=d["seconds"],
        generated_at=d["generated_at"],
        amount_note=d.get("amount_note", ""),
    )


def save(r: KycResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(r), ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path) -> KycResult:
    return from_dict(json.loads(path.read_text(encoding="utf-8")))
