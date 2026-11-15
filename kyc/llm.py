"""Llamadas a Claude: extracción estructurada y redacción del KYC (sesión 08).

- `extract_findings`: lee las fuentes y devuelve `Findings` (pydantic) con un
  puntaje de identidad y otro de relevancia por cada pieza de evidencia.
- `write_narrative`: redacta las secciones del borrador citando las fuentes [n].

Los números del monto tope no salen de aquí: el LLM solo extrae señales
(ocupación, años, tamaño de empresa) y `kyc/wealth.py` hace la cuenta.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import anthropic

from .schemas import Findings, KycNarrative, ProfileInput, SourceDoc

MODEL = os.getenv("KYC_MODEL", "claude-opus-5-5")
# Si el modelo declina por política, la API reintenta en otro modelo dentro de la misma llamada.
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"

# US$ por millón de tokens (entrada, salida) y por búsqueda web. Precios de lista, nov. 2026.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
WEB_SEARCH_USD = 10.00 / 1000


class RefusalError(RuntimeError):
    pass


@dataclass
class UsageTracker:
    """Acumula tokens y búsquedas para calcular el costo real por informe."""
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0
    calls: list[str] = field(default_factory=list)

    def add(self, step: str, usage) -> None:
        if usage is None:
            return
        self.input_tokens += (getattr(usage, "input_tokens", 0) or 0) \
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        server = getattr(usage, "server_tool_use", None)
        if server is not None:
            self.web_searches += getattr(server, "web_search_requests", 0) or 0
        self.calls.append(step)

    def cost_usd(self, model: str = MODEL) -> float:
        p_in, p_out = PRICES.get(model, PRICES["claude-opus-5-5"])
        return (self.input_tokens * p_in + self.output_tokens * p_out) / 1e6 \
            + self.web_searches * WEB_SEARCH_USD


def make_client(api_key: str | None = None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def _check(resp) -> None:
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        raise RefusalError(f"El modelo declinó la solicitud: {getattr(details, 'explanation', '')}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta se cortó por max_tokens.")


def sources_block(sources: list[SourceDoc]) -> str:
    return "\n\n".join(
        f"[{s.id}] {s.title}\nURL: {s.url}\nFecha: {s.date or 'desconocida'}\n{s.text}".strip()
        for s in sources
    )


EXTRACT_SYSTEM = """Eres analista senior de cumplimiento (KYC/PLAFT) en una boutique de wealth management en Perú.
Tu trabajo es leer fuentes públicas sobre un posible cliente y evaluarlas con criterio, no resumirlas a ciegas.

Reglas:
- Evalúa CADA fuente de la lista que mencione a alguien con ese nombre, aunque sea un homónimo.
- identity_score (0 a 1): ¿es la misma persona? Usa los desambiguadores (DNI, edad, ciudad, empleador, ocupación).
  Coincidencia solo de nombre en un nombre común = 0.2-0.4. Edad o ciudad incompatibles = menos de 0.2.
- relevance_score (0 a 1): ¿cuánto pesa para el riesgo de lavado de activos / financiamiento del terrorismo,
  la condición PEP o para explicar el origen de la riqueza? Una opinión política en redes NO es relevante
  (0.0-0.2) salvo que revele un cargo público. Un proceso fiscal por lavado o corrupción es 0.9-1.0.
  Un registro de empresa o cargo directivo documentado es relevante para el origen de la riqueza (0.5-0.8).
- PEP según la SBS: funcionario público con funciones prominentes (actual o en los últimos 5 años),
  y también sus familiares y colaboradores cercanos. Opinar de política no convierte a nadie en PEP.
- No inventes datos. Si una fuente no dice algo, no lo supongas. Los montos solo si la fuente los publica.
- occupation_group y business_size se infieren de la evidencia con identidad alta y de lo declarado.
- Escribe en español, en tono profesional y breve."""


def extract_findings(client: anthropic.Anthropic, profile: ProfileInput, sources: list[SourceDoc],
                     dossier: str, tracker: UsageTracker) -> Findings:
    prompt = (
        f"Posible cliente: {profile.full_name} (residente en Perú)\n"
        f"Desambiguadores: {profile.disambiguators()}\n"
        f"Fuente de fondos declarada: {profile.declared_source_of_funds or 'no declarada'}\n\n"
        f"## Fuentes numeradas\n\n{sources_block(sources)}\n\n"
        f"## Notas del investigador\n\n{dossier or '(sin notas)'}\n\n"
        "Evalúa las fuentes y devuelve los hallazgos. Usa como source_id solo ids de la lista."
    )
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=BETAS,
        fallbacks=FALLBACKS,
        output_config={"effort": "low"},
        system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=Findings,
    )
    tracker.add("extraccion", resp.usage)
    _check(resp)
    findings: Findings = resp.parsed_output
    valid_ids = {s.id for s in sources}
    findings.evidence = [e for e in findings.evidence if e.source_id in valid_ids]
    findings.wealth.liquidity_events = [
        ev for ev in findings.wealth.liquidity_events if ev.source_id in valid_ids
    ]
    for e in findings.evidence:
        e.identity_score = min(max(e.identity_score, 0.0), 1.0)
        e.relevance_score = min(max(e.relevance_score, 0.0), 1.0)
    return findings


NARRATIVE_SYSTEM = """Redactas borradores de KYC para el área de cumplimiento de una boutique de wealth management en Perú.
El borrador lo revisa y firma un oficial de cumplimiento: escribe para él.

Reglas:
- Cada afirmación sobre la persona lleva su cita [n] con el id de la fuente. Sin fuente, no se afirma.
- Usa solo la evidencia marcada como considerada (identidad y relevancia sobre el umbral). La descartada
  se menciona solo para dejar constancia de homónimos.
- No inventes cifras. El monto tope plausible y el nivel de riesgo ya están calculados: úsalos tal cual.
- Si una sección no tiene hallazgos, dilo en una oración ("No se encontraron...").
- Tono profesional, frases cortas, sin adjetivos innecesarios. Español de Perú."""


def write_narrative(client: anthropic.Anthropic, context: dict, tracker: UsageTracker) -> KycNarrative:
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=BETAS,
        fallbacks=FALLBACKS,
        output_config={"effort": "low"},
        system=NARRATIVE_SYSTEM,
        messages=[{
            "role": "user",
            "content": "Redacta las secciones del borrador KYC con este contexto (JSON):\n\n"
                       + json.dumps(context, ensure_ascii=False, indent=1, default=str),
        }],
        output_format=KycNarrative,
    )
    tracker.add("redaccion", resp.usage)
    _check(resp)
    return resp.parsed_output
