"""Modelos de datos del pipeline (pydantic).

Los modelos que Claude devuelve (Findings, KycNarrative) se usan como salidas
estructuradas (sesión 08): la API garantiza JSON válido contra este esquema.
Los puntajes 0-1 no llevan restricciones en el esquema; se acotan en código.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- Entrada ----------

class ProfileInput(BaseModel):
    full_name: str
    dni: str | None = None
    age: int | None = None
    city: str | None = None
    employer: str | None = None
    declared_occupation: str | None = None
    amount: float = 0
    currency: Literal["USD", "PEN"] = "USD"
    declared_source_of_funds: str | None = None
    via_company: bool = False
    company_name: str | None = None
    funds_from_abroad: bool = False

    def disambiguators(self) -> str:
        parts = [
            f"DNI: {self.dni}" if self.dni else None,
            f"edad: {self.age} años" if self.age else None,
            f"ciudad: {self.city}" if self.city else None,
            f"empleador declarado: {self.employer}" if self.employer else None,
            f"ocupación declarada: {self.declared_occupation}" if self.declared_occupation else None,
            f"empresa vehículo: {self.company_name}" if self.via_company and self.company_name else None,
        ]
        return "; ".join(p for p in parts if p) or "sin desambiguadores"


# ---------- Fuentes (búsqueda web o fixtures sintéticos) ----------

class SourceDoc(BaseModel):
    id: int
    url: str
    title: str
    date: str | None = None
    text: str = ""          # extracto o resumen del contenido


# ---------- Salida estructurada de la extracción ----------

Category = Literal[
    "empleo_cargo", "pep", "sancion_o_proceso", "noticia_adversa",
    "patrimonio_negocio", "opinion_redes", "otro",
]
SourceType = Literal["registro_oficial", "medio", "web_empresa", "red_social_opinion", "otro"]


class EvidenceAssessment(BaseModel):
    source_id: int = Field(description="id de la fuente en la lista entregada")
    summary: str = Field(description="Qué dice la fuente sobre la persona, 1-2 oraciones en español")
    category: Category
    source_type: SourceType
    identity_score: float = Field(description="0 a 1: probabilidad de que sea la MISMA persona, según los desambiguadores")
    identity_reason: str
    relevance_score: float = Field(description="0 a 1: cuánto pesa para el riesgo LA/FT o para explicar el origen de la riqueza")
    relevance_reason: str
    risk_direction: Literal["aumenta", "reduce", "neutral"] = Field(
        description="aumenta = señal de riesgo; reduce = respalda un origen legítimo de fondos; neutral = ninguna")
    date: str | None = None


class PepAssessment(BaseModel):
    is_pep: Literal["si", "no", "posible"]
    relation: Literal["titular", "familiar", "colaborador_cercano", "ninguna"]
    role: str | None = Field(default=None, description="Cargo público y entidad, si aplica")
    rationale: str


class LiquidityEvent(BaseModel):
    description: str
    amount_pen: float | None = Field(default=None, description="Monto en soles solo si la fuente lo publica; si no, null")
    source_id: int


class WealthSignals(BaseModel):
    occupation_group: int = Field(description=(
        "Gran grupo CNO 2015: 1 directivos y altos funcionarios; 2 profesionales científicos e intelectuales; "
        "3 profesionales técnicos; 4 empleados administrativos; 5 servicios y comercio; 6 agropecuarios; "
        "7 construcción y oficios; 8 operadores y conductores; 9 ocupaciones elementales; 0 militares y policías; "
        "-1 desconocido"))
    occupation_label: str
    career_years: int | None = Field(default=None, description="Años de carrera estimados; null si no hay base")
    seniority: Literal["junior", "intermedio", "senior", "alta_direccion", "desconocido"]
    business_owner: bool
    business_size: Literal["ninguna", "micro", "pequena", "mediana", "grande", "desconocido"]
    liquidity_events: list[LiquidityEvent]
    rationale: str


class Findings(BaseModel):
    identity_summary: str = Field(description="Quién parece ser la persona, en 2-3 oraciones")
    evidence: list[EvidenceAssessment]
    pep: PepAssessment
    wealth: WealthSignals
    homonyms_note: str = Field(description="Homónimos detectados y por qué se descartan, o 'ninguno'")


class KycNarrative(BaseModel):
    perfil_profesional: str
    exposicion_politica: str
    noticias_adversas: str
    origen_riqueza_y_fondos: str
    conclusion: str
    documentos_a_solicitar: list[str]
