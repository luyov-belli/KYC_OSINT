"""Screening contra listas de sanciones oficiales (sesión 03: scraping y APIs).

Fuentes públicas, descargadas directamente de los emisores:
- OFAC SDN (Departamento del Tesoro de EE. UU.): SDN.CSV + ALT.CSV (alias).
- Lista consolidada del Consejo de Seguridad de la ONU: consolidated.xml.

La coincidencia es difusa (rapidfuzz) porque las listas escriben los nombres
de forma distinta ("APELLIDO, Nombre", sin tildes, con alias).
"""

from __future__ import annotations

import io
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
from rapidfuzz import fuzz, process

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_FILE = CACHE_DIR / "sanctions.csv"
CACHE_MAX_AGE_S = 7 * 24 * 3600

OFAC_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
OFAC_ALT_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ALT.CSV"
UN_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

SDN_COLS = ["ent_num", "name", "sdn_type", "program", "title", "call_sign",
            "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks"]
ALT_COLS = ["ent_num", "alt_num", "alt_type", "alt_name", "alt_remarks"]

# Umbrales de similitud (0-100), visibles en la UI
STRONG_MATCH = 92
POSSIBLE_MATCH = 85


@dataclass
class SanctionHit:
    source: str        # "OFAC SDN" | "ONU"
    list_id: str
    listed_name: str   # nombre tal como aparece en la lista
    matched_on: str    # nombre o alias que coincidió
    kind: str          # individual | entidad
    program: str
    remarks: str
    score: float       # 0-100
    strength: str      # "fuerte" | "posible"


def normalize(name: str) -> str:
    """Mayúsculas, sin tildes ni puntuación, espacios simples."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^A-Za-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip().upper()


def _reorder_ofac(name: str) -> str:
    """OFAC escribe a las personas como 'APELLIDOS, Nombres'."""
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name


def _clean(value: str) -> str:
    value = (value or "").strip()
    return "" if value == "-0-" else value


def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=90, headers={"User-Agent": "kyc-osint/0.1 (proyecto academico)"})
    resp.raise_for_status()
    return resp.content


def _parse_ofac(sdn_raw: bytes, alt_raw: bytes) -> list[dict]:
    sdn = pd.read_csv(io.BytesIO(sdn_raw), header=None, names=SDN_COLS, dtype=str,
                      encoding="latin-1", keep_default_na=False)
    sdn = sdn.map(_clean)
    # Solo personas y entidades (fuera buques y aeronaves)
    sdn = sdn[~sdn["sdn_type"].isin(["vessel", "aircraft"])]
    sdn["kind"] = sdn["sdn_type"].map(lambda t: "individual" if t == "individual" else "entidad")

    rows = []
    for r in sdn.itertuples():
        rows.append(dict(source="OFAC SDN", list_id=r.ent_num, listed_name=r.name,
                         matched_on=_reorder_ofac(r.name), kind=r.kind,
                         program=r.program, remarks=r.remarks))

    alt = pd.read_csv(io.BytesIO(alt_raw), header=None, names=ALT_COLS, dtype=str,
                      encoding="latin-1", keep_default_na=False)
    alt = alt.map(_clean)
    meta = sdn.set_index("ent_num")[["name", "kind", "program", "remarks"]]
    alt = alt[alt["ent_num"].isin(meta.index)]
    for r in alt.itertuples():
        m = meta.loc[r.ent_num]
        rows.append(dict(source="OFAC SDN", list_id=r.ent_num, listed_name=m["name"],
                         matched_on=_reorder_ofac(r.alt_name), kind=m["kind"],
                         program=m["program"], remarks=m["remarks"]))
    return rows


def _text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _parse_un(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    rows = []
    for ind in root.iter("INDIVIDUAL"):
        parts = [_text(ind, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]
        name = " ".join(p for p in parts if p)
        base = dict(source="ONU", list_id=_text(ind, "REFERENCE_NUMBER"), listed_name=name,
                    kind="individual", program=_text(ind, "UN_LIST_TYPE"),
                    remarks=_text(ind, "COMMENTS1")[:500])
        rows.append({**base, "matched_on": name})
        for alias in ind.iter("INDIVIDUAL_ALIAS"):
            alias_name = _text(alias, "ALIAS_NAME")
            if alias_name:
                rows.append({**base, "matched_on": alias_name})
    for ent in root.iter("ENTITY"):
        name = _text(ent, "FIRST_NAME")
        base = dict(source="ONU", list_id=_text(ent, "REFERENCE_NUMBER"), listed_name=name,
                    kind="entidad", program=_text(ent, "UN_LIST_TYPE"),
                    remarks=_text(ent, "COMMENTS1")[:500])
        rows.append({**base, "matched_on": name})
        for alias in ent.iter("ENTITY_ALIAS"):
            alias_name = _text(alias, "ALIAS_NAME")
            if alias_name:
                rows.append({**base, "matched_on": alias_name})
    return rows


def refresh_lists() -> pd.DataFrame:
    """Descarga las listas oficiales y guarda una tabla unificada en caché."""
    rows = _parse_ofac(_download(OFAC_SDN_URL), _download(OFAC_ALT_URL))
    rows += _parse_un(_download(UN_URL))
    df = pd.DataFrame(rows)
    df = df[df["matched_on"].str.len() > 2]
    df["norm"] = df["matched_on"].map(normalize)
    df = df.drop_duplicates(subset=["source", "list_id", "norm"]).reset_index(drop=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE_FILE, index=False)
    return df


def load_lists(max_age_s: int = CACHE_MAX_AGE_S) -> pd.DataFrame:
    """Usa la caché si tiene menos de una semana; si no, descarga de nuevo."""
    if CACHE_FILE.exists() and time.time() - CACHE_FILE.stat().st_mtime < max_age_s:
        return pd.read_csv(CACHE_FILE, dtype=str, keep_default_na=False)
    return refresh_lists()


def lists_date() -> str:
    """Fecha de la última descarga, para citarla en el informe."""
    if not CACHE_FILE.exists():
        return "sin descargar"
    return time.strftime("%Y-%m-%d", time.localtime(CACHE_FILE.stat().st_mtime))


def _score(query: str, candidate: str, **_: object) -> float:
    """Similitud robusta al orden de los nombres y a apellidos faltantes.

    token_sort_ratio compara los nombres completos sin importar el orden.
    token_set_ratio premia cuando un nombre está contenido en el otro
    (p. ej. la lista trae un solo apellido); se descuenta un poco para que
    no gane solo por compartir una palabra.
    """
    sort = fuzz.token_sort_ratio(query, candidate)
    shared = set(query.split()) & set(candidate.split())
    if len(shared) >= 2:
        # Un nombre contenido en otro nunca pasa de "posible": falta confirmar
        # con fecha de nacimiento o documento.
        return max(sort, min(fuzz.token_set_ratio(query, candidate) - 5, STRONG_MATCH - 1))
    return sort


def screen(name: str, lists: pd.DataFrame | None = None, limit: int = 10) -> list[SanctionHit]:
    """Busca un nombre (persona o empresa) en OFAC y ONU."""
    lists = load_lists() if lists is None else lists
    query = normalize(name)
    if not query:
        return []
    matches = process.extract(query, lists["norm"], scorer=_score,
                              score_cutoff=POSSIBLE_MATCH, limit=limit * 3)
    hits: dict[tuple[str, str], SanctionHit] = {}
    for _, score, idx in matches:
        r = lists.iloc[idx]
        key = (r["source"], r["list_id"])
        if key in hits and hits[key].score >= score:
            continue
        hits[key] = SanctionHit(
            source=r["source"], list_id=r["list_id"], listed_name=r["listed_name"],
            matched_on=r["matched_on"], kind=r["kind"], program=r["program"],
            remarks=r["remarks"], score=round(float(score), 1),
            strength="fuerte" if score >= STRONG_MATCH else "posible",
        )
    return sorted(hits.values(), key=lambda h: -h.score)[:limit]
