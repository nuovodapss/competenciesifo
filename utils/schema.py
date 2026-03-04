from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

BASE_FIELDS = ["ID", "Nome", "Cognome", "Struttura"]

def load_column_order(path: str | Path) -> list[str]:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ensure_schema(df: pd.DataFrame, column_order: list[str], fill_value: str = "NA") -> pd.DataFrame:
    """Ensure all columns exist; add missing as fill_value; return df with columns ordered.
    Extra columns are appended at the end (stable order).
    """
    out = df.copy()
    for col in column_order:
        if col not in out.columns:
            out[col] = fill_value
    extra = [c for c in out.columns if c not in column_order]
    return out[column_order + extra]

def coerce_base_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Light normalization for base columns names."""
    out = df.copy()
    rename = {}
    for c in out.columns:
        c2 = str(c).strip()
        if c2 != c:
            rename[c] = c2
    if rename:
        out = out.rename(columns=rename)
    return out
