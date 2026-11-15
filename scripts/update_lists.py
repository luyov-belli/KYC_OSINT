"""Descarga de nuevo las listas de sanciones OFAC SDN y ONU a `data/cache/`.

Uso:  uv run python scripts/update_lists.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kyc import sanctions  # noqa: E402

if __name__ == "__main__":
    df = sanctions.refresh_lists()
    print(f"{len(df):,} nombres y alias · {df['source'].value_counts().to_dict()} · {sanctions.lists_date()}")
