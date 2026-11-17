"""Paquete de evidencia para auditoría (pedido de Compliance en las conversaciones).

Empaqueta en un JSON todo lo que vio y decidió el agente: cada fuente con su
enlace, fecha de publicación, fecha de consulta y extracto; los puntajes de
identidad y relevancia con sus razones; las coincidencias en listas de
sanciones; las reglas de riesgo que se activaron con sus umbrales; y los
supuestos del monto tope.

Solo reordena un resultado ya calculado: no llama al modelo ni cuesta API.

La huella SHA-256 se calcula sobre el contenido (sin la propia huella) y se
imprime también en el Word: así se puede comprobar que el informe y la
evidencia son del mismo análisis y que el JSON no se modificó.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from . import risk
from .llm import MODEL
from .pipeline import KycResult

FORMAT_VERSION = "1"


def _fingerprint(content: dict) -> str:
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _content(r: KycResult) -> dict:
    by_source = {e.source_id: e for e in r.findings.evidence}
    fuentes = []
    for s in r.sources:
        e = by_source.get(s.id)
        fuentes.append({
            "id": s.id,
            "titulo": s.title,
            "url": s.url,
            "fecha_publicacion": s.date,
            "fecha_consulta": r.generated_at,
            "extracto": s.text,
            "evaluacion": None if e is None else {
                "clasificacion": risk.classify(e),
                "resumen": e.summary,
                "categoria": e.category,
                "tipo_de_fuente": e.source_type,
                "identidad": e.identity_score,
                "razon_identidad": e.identity_reason,
                "relevancia": e.relevance_score,
                "razon_relevancia": e.relevance_reason,
                "direccion_del_riesgo": e.risk_direction,
            },
        })
    w = r.wealth
    return {
        "formato": f"kyc-osint-evidencia/{FORMAT_VERSION}",
        "informe": {
            "generado": r.generated_at,
            "modo": r.mode,
            "modelo": MODEL,
            "duracion_s": round(r.seconds, 1),
            "costo_usd": round(r.usage.cost_usd(), 4),
            "tokens_entrada": r.usage.input_tokens,
            "tokens_salida": r.usage.output_tokens,
            "busquedas_web": r.usage.web_searches,
            "nota_monto_simulado": r.amount_note or None,
        },
        "cliente_declarado": r.profile.model_dump(mode="json"),
        "sanciones": {
            "listas": "OFAC SDN (con alias) y lista consolidada de la ONU",
            "fecha_de_las_listas": r.lists_date,
            "coincidencias": [asdict(h) for h in r.hits],
        },
        "fuentes": fuentes,
        "identidad": r.findings.identity_summary,
        "homonimos": r.findings.homonyms_note,
        "pep": r.findings.pep.model_dump(mode="json"),
        "monto_tope": {
            "declarado_soles": round(w.declared_pen, 2),
            "base_soles": round(w.base_pen, 2),
            "tope_soles": round(w.tope_pen, 2),
            "ratio_declarado_tope": None if w.ratio is None else round(w.ratio, 4),
            "coherencia": w.coherence,
            "ocupacion": w.occupation,
            "anios_de_carrera": w.career_years,
            "percentil_tope": w.percentile_tope,
            "tipo_de_cambio": {"valor": w.fx, "fuente": w.fx_source},
            "senales_extraidas": r.findings.wealth.model_dump(mode="json"),
            "supuestos": w.assumptions,
        },
        "riesgo": {
            "nivel": r.risk.level,
            "puntaje": r.risk.score,
            "debida_diligencia": r.risk.dd_type,
            "recomendacion": r.risk.recommendation,
            "factores": [{"regla": f.rule, "puntos": f.points, "detalle": f.detail,
                          "obliga_dd_reforzada": f.forces_edd} for f in r.risk.factors],
            "umbrales": {
                "identidad_minima": risk.IDENTITY_MIN,
                "relevancia_minima": risk.RELEVANCE_MIN,
                "homonimo_maximo": risk.HOMONYM_MAX,
                "monto_dd_reforzada_usd": risk.EDD_AMOUNT_USD,
                "niveles": {name: threshold for threshold, name in risk.LEVELS},
            },
        },
        "notas_del_investigador": r.dossier or None,
    }


def evidence(r: KycResult) -> dict:
    content = _content(r)
    return {**content, "huella_sha256": _fingerprint(content)}


def fingerprint(r: KycResult) -> str:
    return _fingerprint(_content(r))


def evidence_json(r: KycResult) -> bytes:
    return json.dumps(evidence(r), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def verify(data: dict) -> bool:
    """Comprueba que un paquete de evidencia no se modificó después de generarse."""
    content = {k: v for k, v in data.items() if k != "huella_sha256"}
    return data.get("huella_sha256") == _fingerprint(content)
