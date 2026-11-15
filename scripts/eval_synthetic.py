"""Evalúa el agente con las personas sintéticas de `fixtures/`.

Para cada persona compara lo que sale del pipeline con lo esperado:
nivel de riesgo, tipo de DD, condición PEP y homónimos descartados.
Escribe el resumen en `docs/eval_sinteticos.md` y guarda cada resultado en
`fixtures/resultados/<id>.json`: la app los muestra desde ahí sin llamar a la
API (son datos ficticios, se pueden versionar).

Uso:  uv run python scripts/eval_synthetic.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kyc import pipeline, risk  # noqa: E402
from kyc.llm import MODEL, make_client  # noqa: E402
from kyc.schemas import ProfileInput, SourceDoc  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env")
    client = make_client()
    rows, passed, total_cost = [], 0, 0.0
    for f in sorted((ROOT / "fixtures").glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        exp = p["expected"]
        res = pipeline.run(ProfileInput(**p["profile"]), client,
                           sources=[SourceDoc(**s) for s in p["sources"]])
        discarded = {e.source_id for e in res.findings.evidence if risk.classify(e) == "descartada"}
        checks = {
            "riesgo": res.risk.level in exp["risk_levels"],
            "DD": res.risk.dd_type in exp["dd"],
            "PEP": res.findings.pep.is_pep == exp["pep"],
            "homónimos": set(exp["discard_ids"]) <= discarded,
        }
        ok = all(checks.values())
        passed += ok
        total_cost += res.usage.cost_usd()
        rows.append((p["label"], res.risk.level, res.risk.dd_type, res.findings.pep.is_pep,
                     f"{res.wealth.ratio:.2f}" if res.wealth.ratio is not None else "s/d",
                     ", ".join(k for k, v in checks.items() if not v) or "—",
                     "✅" if ok else "❌", f"{res.usage.cost_usd():.3f}", f"{res.seconds:.0f}"))
        pipeline.save(res, ROOT / "fixtures" / "resultados" / f"{p['id']}.json")
        print(rows[-1])

    lines = [
        "# Evaluación con personas sintéticas",
        "",
        f"Modelo `{MODEL}`. {passed}/{len(rows)} casos correctos. Costo total US$ {total_cost:.2f}.",
        "",
        "| Caso | Riesgo | DD | PEP | Declarado/tope | Falló en | OK | US$ | s |",
        "|---|---|---|---|---|---|---|---|---|",
        *("| " + " | ".join(r) + " |" for r in rows),
        "",
        "Los nombres, las fuentes y los hechos son ficticios (ver `fixtures/`).",
    ]
    out = ROOT / "docs" / "eval_sinteticos.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(rows)} correctos · US$ {total_cost:.2f} · {out}")


if __name__ == "__main__":
    main()
