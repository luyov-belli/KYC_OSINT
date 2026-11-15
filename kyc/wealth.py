"""Monto tope plausible: ¿con cuánto dinero podría venir, como máximo, este cliente?

Es un cálculo híbrido para que el LLM no invente cifras:
- El LLM solo extrae señales cerradas (grupo ocupacional CNO, años de carrera,
  seniority, tamaño de empresa, eventos de liquidez con monto publicado).
- Este módulo hace la cuenta con supuestos visibles:
  * Patrimonio laboral: suma, año por año de carrera, del ingreso laboral de
    la ENAHO 2024 (percentil según seniority) × tasa de ahorro, capitalizado.
  * Patrimonio empresarial: ventas por tamaño de empresa (Ley MYPE, en UIT)
    × margen neto × múltiplo de valorización.
  * Eventos de liquidez con monto público (venta de inmueble, herencia...).

Límite conocido: la ENAHO subestima los ingresos altos. El tope sirve para
pedir sustento documentario, no para rechazar a nadie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

from .schemas import ProfileInput, WealthSignals

TABLE = Path(__file__).resolve().parent.parent / "data" / "ingresos_ocupacion_edad.csv"

# ---- Supuestos (visibles en la app y en el informe) ----
SAVINGS_BASE = 0.10          # escenario base: ahorra 10 % del ingreso
SAVINGS_TOPE = 0.35          # escenario tope: ahorra 35 %
REAL_RETURN = 0.04           # retorno real anual del ahorro
PCT_BASE = "p50"
PCT_TOPE_BY_SENIORITY = {"junior": "p75", "intermedio": "p90", "senior": "p95",
                         "alta_direccion": "p99", "desconocido": "p95"}
MIN_CELL_OBS = 30            # celdas con menos observaciones usan la fila "todas"
DEFAULT_CAREER_YEARS = 15
UIT_PEN = 5_350              # UIT 2025; actualizar al valor vigente
# Ventas anuales por tamaño (en UIT, Ley MYPE): (base, tope)
BUSINESS_SALES_UIT = {"micro": (75, 150), "pequena": (925, 1_700),
                      "mediana": (2_000, 2_300), "grande": (2_300, 9_200)}
BUSINESS_EQUITY_FACTOR = {"base": 0.05 * 3, "tope": 0.10 * 5}   # margen neto × múltiplo
FX_FALLBACK = 3.45           # S/ por US$, si la API del BCRP no responde

AGE_GROUPS = [(18, 24, "18-24"), (25, 34, "25-34"), (35, 44, "35-44"),
              (45, 54, "45-54"), (55, 64, "55-64"), (65, 200, "65+")]


@dataclass
class WealthEstimate:
    declared_pen: float
    fx: float
    fx_source: str
    labor_base: float
    labor_tope: float
    business_base: float
    business_tope: float
    events_pen: float
    base_pen: float
    tope_pen: float
    ratio: float | None            # declarado / tope
    coherence: str                 # coherente | pedir_sustento | incoherente | sin_base
    percentile_tope: str
    career_years: int
    occupation: str
    assumptions: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def usd_pen_rate() -> tuple[float, str]:
    """Tipo de cambio venta SBS desde la API del BCRP (serie PD04640PD)."""
    try:
        today = pd.Timestamp.today()
        url = ("https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04640PD/json/"
               f"{(today - pd.Timedelta(days=30)).date()}/{today.date()}")
        periods = requests.get(url, timeout=15).json()["periods"]
        for p in reversed(periods):
            value = p["values"][0]
            if value not in ("n.d.", ""):
                return float(value), f"BCRP, venta SBS {p['name']}"
    except Exception:
        pass
    return FX_FALLBACK, "valor de respaldo (BCRP no respondió)"


@lru_cache(maxsize=1)
def load_table() -> pd.DataFrame | None:
    if not TABLE.exists():
        return None
    return pd.read_csv(TABLE, encoding="utf-8")


def _age_group(age: int) -> str:
    for lo, hi, label in AGE_GROUPS:
        if lo <= age <= hi:
            return label
    return "18-24" if age < 18 else "65+"


def _income(table: pd.DataFrame, group: int, age: int, pct: str) -> float:
    rows = table[table["grupo_cno"] == group] if group >= 0 else table
    cell = rows[rows["grupo_edad"] == _age_group(age)]
    if group >= 0 and (cell.empty or int(cell["n_obs"].iloc[0]) < MIN_CELL_OBS):
        cell = rows[rows["grupo_edad"] == "todas"]
    if group < 0:  # ocupación desconocida: promedio ponderado entre grupos
        w = cell["poblacion"]
        return float((cell[pct] * w).sum() / w.sum())
    return float(cell[pct].iloc[0])


def _labor_wealth(table, group: int, age: int, years: int, pct: str, savings: float) -> float:
    total = 0.0
    for k in range(years):
        age_k = max(18, age - years + k)
        total += _income(table, group, age_k, pct) * savings * (1 + REAL_RETURN) ** (years - 1 - k)
    return total


def estimate(profile: ProfileInput, signals: WealthSignals) -> WealthEstimate:
    fx, fx_source = usd_pen_rate()
    declared_pen = profile.amount * (fx if profile.currency == "USD" else 1.0)
    table = load_table()
    assumptions = [
        f"Ingreso laboral: ENAHO 2024 (INEI), base {PCT_BASE}, tope según seniority",
        f"Ahorro {SAVINGS_BASE:.0%} (base) a {SAVINGS_TOPE:.0%} (tope), retorno real {REAL_RETURN:.0%} anual",
        f"Tipo de cambio S/ {fx:.3f} por US$ ({fx_source})",
    ]

    age = profile.age or 45
    if not profile.age:
        assumptions.append("Edad no declarada: se asume 45 años")
    start_age = 23 if signals.occupation_group in (1, 2) else 18
    if signals.career_years:
        years = max(1, min(signals.career_years, 50))
    else:
        years = max(1, min(age - start_age, 45))
        assumptions.append(f"Años de carrera estimados desde la edad: {years}")
    group = signals.occupation_group if 0 <= signals.occupation_group <= 9 else -1
    if group < 0:
        assumptions.append("Ocupación desconocida: promedio de todas las ocupaciones")
    pct_tope = PCT_TOPE_BY_SENIORITY.get(signals.seniority, "p95")

    if table is not None:
        labor_base = _labor_wealth(table, group, age, years, PCT_BASE, SAVINGS_BASE)
        labor_tope = _labor_wealth(table, group, age, years, pct_tope, SAVINGS_TOPE)
        occupation = (table.loc[table["grupo_cno"] == group, "grupo_cno_nombre"].iloc[0]
                      if group >= 0 else "desconocida")
    else:
        labor_base = labor_tope = 0.0
        occupation = signals.occupation_label
        assumptions.append("Tabla ENAHO no disponible: sin componente laboral")

    business_base = business_tope = 0.0
    if signals.business_owner:
        size = signals.business_size if signals.business_size in BUSINESS_SALES_UIT else "micro"
        if size != signals.business_size:
            assumptions.append("Tamaño de empresa desconocido: se asume microempresa")
        sales_base, sales_tope = BUSINESS_SALES_UIT[size]
        business_base = sales_base * UIT_PEN * BUSINESS_EQUITY_FACTOR["base"]
        business_tope = sales_tope * UIT_PEN * BUSINESS_EQUITY_FACTOR["tope"]
        assumptions.append(f"Empresa {size}: ventas Ley MYPE × margen 5-10 % × múltiplo 3-5 (UIT S/ {UIT_PEN:,})")

    events = sum(ev.amount_pen or 0 for ev in signals.liquidity_events)
    base = labor_base + business_base + events
    tope = labor_tope + business_tope + events

    if tope <= 0:
        ratio, coherence = None, "sin_base"
    else:
        ratio = declared_pen / tope
        coherence = "coherente" if ratio <= 0.6 else "pedir_sustento" if ratio <= 1.0 else "incoherente"

    return WealthEstimate(
        declared_pen=declared_pen, fx=fx, fx_source=fx_source,
        labor_base=labor_base, labor_tope=labor_tope,
        business_base=business_base, business_tope=business_tope, events_pen=events,
        base_pen=base, tope_pen=tope, ratio=ratio, coherence=coherence,
        percentile_tope=pct_tope, career_years=years, occupation=occupation,
        assumptions=assumptions,
    )
