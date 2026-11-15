"""Construye data/ingresos_ocupacion_edad.csv a partir de la ENAHO 2024 (módulo 500).

Fuente: INEI, Encuesta Nacional de Hogares 2024, Módulo 05 "Empleo e Ingresos"
(código de encuesta 966 en el portal de microdatos). Archivo: enaho01a-2024-500.dta.

Qué hace:
  1. Descarga el ZIP del módulo (si no está ya en datos/) y lo descomprime en un
     directorio propio, datos/enaho2024_mod500/. Los microdatos no se suben al repo.
  2. Filtra: ocupados (ocu500 == 1), residentes habituales, 18 años o más y con
     ingreso laboral anual > 0.
  3. Calcula el ingreso laboral anual (ocupación principal + secundaria, monetario
     y en especie, más ingresos extraordinarios) con las variables derivadas del INEI.
  4. Agrupa por gran grupo ocupacional CNO 2015 × grupo de edad y calcula
     percentiles ponderados con fac500a. Agrega una fila "todas" por grupo.

Uso (sin tocar las dependencias del proyecto):
  uv run --no-project --with pandas --with pyreadstat python -I scripts/build_enaho_table.py

El .dta es dato no confiable: solo se lee con pyreadstat (no se ejecuta nada de él)
y este script vive fuera del directorio donde se descomprime.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
import pyreadstat

REPO_ROOT = Path(__file__).resolve().parent.parent

ZIP_URL = "https://proyectos.inei.gob.pe/iinei/srienaho/descarga/STATA/966-Modulo05.zip"
# SHA-256 del ZIP descargado el 2026-11-15 (Last-Modified del servidor: 2025-05-17).
# Si el INEI republica el archivo el hash cambiará: se avisa, no se aborta.
ZIP_SHA256 = "462e4e08475c4107f7af261178c9ac492f0fa4239455ae2d765f4c14e176bb0f"
ZIP_PATH = REPO_ROOT / "datos" / "zip" / "966-Modulo05.zip"
EXTRACT_DIR = REPO_ROOT / "datos" / "enaho2024_mod500"
DTA_NAME = "enaho01a-2024-500.dta"
OUT_CSV = REPO_ROOT / "data" / "ingresos_ocupacion_edad.csv"

# Componentes del ingreso laboral anual (todas ya anualizadas por el INEI).
# Es la suma estándar del "ingreso proveniente del trabajo" en la ENAHO.
INCOME_VARS = {
    # Ocupación principal
    "i524a1": "dependiente: ingreso monetario total (imputado, anual)",
    "d529t": "dependiente: pagos en especie, total (deflactado, anual)",
    "i530a": "independiente: ganancia neta (imputado, anual)",
    "d536": "independiente: autoconsumo/autosuministro (deflactado, anual)",
    # Ocupación secundaria
    "i538a1": "dependiente: ingreso monetario total (imputado, anual)",
    "d540t": "dependiente: pagos en especie, total (deflactado, anual)",
    "i541a": "independiente: ganancia neta (imputado, anual)",
    "d543": "independiente: autoconsumo/autosuministro (deflactado, anual)",
    # Extraordinarios (últimos 12 meses)
    "d544t": "gratificaciones, bonificaciones, CTS, utilidades, etc. (deflactado, anual)",
}

ID_VARS = ["ocu500", "p204", "p205", "p206", "p208a", "p505r4", "fac500a"]

# Grandes grupos de la Clasificación Nacional de Ocupaciones 2015 (INEI).
CNO_GRANDES_GRUPOS = {
    0: "Ocupaciones militares y policiales",
    1: "Miembros del poder ejecutivo, legislativo, judicial y personal directivo de la administración pública y privada",
    2: "Profesionales científicos e intelectuales",
    3: "Profesionales técnicos",
    4: "Jefes y empleados administrativos",
    5: "Trabajadores de los servicios y vendedores de comercios y mercados",
    6: "Agricultores y trabajadores calificados agropecuarios, forestales y pesqueros",
    7: "Trabajadores de la construcción, edificación, productos artesanales, electricidad y las telecomunicaciones",
    8: "Operadores de maquinaria industrial, ensambladores y conductores de transporte",
    9: "Ocupaciones elementales",
}

AGE_BINS = [18, 25, 35, 45, 55, 65, np.inf]
AGE_LABELS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
TODAS = "todas"

PERCENTILES = {"p50": 0.50, "p75": 0.75, "p90": 0.90, "p95": 0.95, "p99": 0.99}
MIN_OBS_CELDA = 30


# --------------------------------------------------------------------------- #
# Descarga y extracción
# --------------------------------------------------------------------------- #
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_zip(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (enaho-table-builder)"})
    print(f"Descargando {url} ...")
    with urllib.request.urlopen(req, timeout=300) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.replace(dest)


def safe_extract(zip_path: Path, dest: Path) -> None:
    """Descomprime en `dest` rechazando rutas absolutas o con '..'."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise RuntimeError(f"Entrada sospechosa en el ZIP: {info.filename!r}")
            target = (dest / name).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"Entrada fuera del directorio destino: {info.filename!r}")
        zf.extractall(dest)


def ensure_dta(dta_arg: Path | None) -> Path:
    if dta_arg is not None:
        if not dta_arg.is_file():
            sys.exit(f"No existe el archivo indicado: {dta_arg}")
        return dta_arg

    found = list(EXTRACT_DIR.rglob(DTA_NAME)) if EXTRACT_DIR.exists() else []
    if found:
        return found[0]

    if not ZIP_PATH.is_file():
        download_zip(ZIP_URL, ZIP_PATH)
    digest = sha256(ZIP_PATH)
    if digest != ZIP_SHA256:
        print(f"AVISO: el SHA-256 del ZIP ({digest}) no coincide con el registrado; "
              "puede que el INEI haya republicado el módulo. Se continúa.")
    with zipfile.ZipFile(ZIP_PATH) as zf:
        if not any(PurePosixPath(n).name == DTA_NAME for n in zf.namelist()):
            sys.exit(f"El ZIP no contiene {DTA_NAME}: no parece el módulo 500 de la ENAHO 2024.")
    safe_extract(ZIP_PATH, EXTRACT_DIR)
    found = list(EXTRACT_DIR.rglob(DTA_NAME))
    if not found:
        sys.exit(f"No se encontró {DTA_NAME} tras descomprimir en {EXTRACT_DIR}")
    return found[0]


# --------------------------------------------------------------------------- #
# Carga y construcción de variables
# --------------------------------------------------------------------------- #
def load(dta: Path) -> pd.DataFrame:
    _, meta = pyreadstat.read_dta(str(dta), metadataonly=True, encoding="latin1")
    needed = ID_VARS + list(INCOME_VARS)
    missing = [c for c in needed if c not in meta.column_names]
    if missing:
        sys.exit(f"Faltan variables en {dta.name}: {missing}")
    df, _ = pyreadstat.read_dta(str(dta), usecols=needed, encoding="latin1")
    # Algunas columnas vienen como object (mezcla int/float por los missing de Stata).
    for c in needed:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_universe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    steps: dict[str, int] = {"registros en el módulo 500": len(df)}

    df = df[df["ocu500"] == 1]
    steps["ocupados (ocu500 == 1)"] = len(df)

    residente = ((df["p204"] == 1) & (df["p205"] == 2)) | ((df["p204"] == 2) & (df["p206"] == 1))
    df = df[residente]
    steps["+ residentes habituales"] = len(df)

    df = df[df["p208a"] >= 18]
    steps["+ 18 años o más"] = len(df)

    df = df[df["p505r4"].notna() & (df["fac500a"] > 0)].copy()
    steps["+ con ocupación CNO y factor válidos"] = len(df)

    # Los montos crudos del cuestionario usan 999999 como missing; las variables
    # derivadas (i*/d*) no deberían traerlo, pero si apareciera se aborta.
    if (df[list(INCOME_VARS)] >= 999_999).any().any():
        sys.exit("Hay montos >= 999999 (posible código de missing) en las variables de ingreso.")
    df["ingreso_anual"] = df[list(INCOME_VARS)].fillna(0).sum(axis=1)
    steps["  de ellos con ingreso laboral = 0"] = int((df["ingreso_anual"] <= 0).sum())
    df = df[df["ingreso_anual"] > 0].copy()
    steps["+ ingreso laboral anual > 0 (universo final)"] = len(df)

    # p505r4 es numérico: los códigos militares/policiales (gran grupo 0) pierden
    # el cero inicial y quedan con 3 dígitos (111, 220, ...). Por eso // 1000.
    df["grupo_cno"] = (df["p505r4"].astype(int) // 1000).astype(int)
    bad = ~df["grupo_cno"].isin(CNO_GRANDES_GRUPOS)
    if bad.any():
        sys.exit(f"Códigos CNO inesperados: {df.loc[bad, 'p505r4'].unique()[:10]}")

    df["grupo_edad"] = pd.cut(df["p208a"], bins=AGE_BINS, labels=AGE_LABELS, right=False).astype(str)
    return df, steps


# --------------------------------------------------------------------------- #
# Percentiles ponderados
# --------------------------------------------------------------------------- #
def weighted_quantiles(values: np.ndarray, weights: np.ndarray, qs: list[float]) -> list[float]:
    """Percentil ponderado con la misma regla que Stata `_pctile [pw=]`.

    Ordena los valores, acumula los pesos y toma el primer valor cuya masa
    acumulada supera q·W; si coincide exactamente, promedia con el siguiente.
    """
    order = np.argsort(values, kind="mergesort")
    x = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    total = cw[-1]
    out = []
    for q in qs:
        target = q * total
        i = int(np.searchsorted(cw, target, side="left"))
        i = min(i, len(x) - 1)
        if np.isclose(cw[i], target) and i + 1 < len(x):
            out.append((x[i] + x[i + 1]) / 2)
        else:
            out.append(x[i])
    return out


def summarize(g: pd.DataFrame) -> pd.Series:
    qs = weighted_quantiles(g["ingreso_anual"].to_numpy(), g["fac500a"].to_numpy(), list(PERCENTILES.values()))
    row = {"n_obs": len(g), "poblacion": g["fac500a"].sum()}
    row.update(dict(zip(PERCENTILES, qs)))
    return pd.Series(row)


def build_table(df: pd.DataFrame) -> pd.DataFrame:
    cells = df.groupby(["grupo_cno", "grupo_edad"]).apply(summarize, include_groups=False).reset_index()
    todas = df.groupby("grupo_cno").apply(summarize, include_groups=False).reset_index()
    todas["grupo_edad"] = TODAS
    out = pd.concat([cells, todas], ignore_index=True)

    out["grupo_cno_nombre"] = out["grupo_cno"].map(CNO_GRANDES_GRUPOS)
    order = {lab: i for i, lab in enumerate(AGE_LABELS + [TODAS])}
    out = out.sort_values(["grupo_cno", "grupo_edad"], key=lambda s: s.map(order) if s.name == "grupo_edad" else s)

    out["grupo_cno"] = out["grupo_cno"].astype(int)
    out["n_obs"] = out["n_obs"].astype(int)
    out["poblacion"] = out["poblacion"].round().astype(int)
    for p in PERCENTILES:
        out[p] = out[p].round().astype(int)
    cols = ["grupo_cno", "grupo_cno_nombre", "grupo_edad", "n_obs", "poblacion", *PERCENTILES]
    return out[cols].reset_index(drop=True)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dta", type=Path, default=None, help=f"ruta a {DTA_NAME} (por defecto, se busca/descarga en datos/)")
    ap.add_argument("--out", type=Path, default=OUT_CSV, help="CSV de salida")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dta = ensure_dta(args.dta)
    print(f"Leyendo {dta.relative_to(REPO_ROOT) if dta.is_relative_to(REPO_ROOT) else dta}")
    df, steps = build_universe(load(dta))

    print("\nFiltros:")
    for k, v in steps.items():
        print(f"  {k:<48s} {v:>8,d}")

    table = build_table(df)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False, encoding="utf-8")
    print(f"\nEscrito {args.out} ({len(table)} filas)")

    # Resumen y chequeos de cordura
    w = df["fac500a"].to_numpy()
    mensual = df["ingreso_anual"].to_numpy() / 12
    p50_m, p90_m = weighted_quantiles(mensual, w, [0.5, 0.9])
    media_m = np.average(mensual, weights=w)
    print(f"\nPoblación ocupada representada (18+, ingreso > 0): {w.sum():,.0f}")
    print(f"Ingreso laboral mensual ponderado: mediana S/ {p50_m:,.0f} | media S/ {media_m:,.0f} | p90 S/ {p90_m:,.0f}")
    if not 700 <= p50_m <= 2000:
        print("AVISO: la mediana mensual cae fuera del rango plausible para el Perú (S/ 700-2,000).")

    with pd.option_context("display.width", 200, "display.max_rows", 200):
        resumen = table.copy()
        resumen["grupo_cno_nombre"] = resumen["grupo_cno_nombre"].str.slice(0, 32)
        print("\n" + resumen.to_string(index=False))

    pocas = table[(table["grupo_edad"] != TODAS) & (table["n_obs"] < MIN_OBS_CELDA)]
    print(f"\nCeldas con n_obs < {MIN_OBS_CELDA} (usar la fila '{TODAS}' como respaldo): {len(pocas)}")
    if len(pocas):
        print(pocas[["grupo_cno", "grupo_edad", "n_obs"]].to_string(index=False))


if __name__ == "__main__":
    main()
