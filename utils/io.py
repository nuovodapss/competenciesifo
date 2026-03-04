from __future__ import annotations
import pandas as pd
from .recode import normalize_level

def read_department_excel(file) -> pd.DataFrame:
    """Read coordinator dataset (xlsx)."""
    df = pd.read_excel(file)
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    return df

def normalize_competence_columns(df: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in codes:
        if c in out.columns:
            out[c] = out[c].apply(normalize_level)
    return out

def detect_structure_values(df: pd.DataFrame) -> list[str]:
    if "Struttura" not in df.columns:
        return []
    vals = (
        df["Struttura"]
        .dropna()
        .astype(str)
        .map(lambda x: x.strip())
    )
    return sorted([v for v in vals.unique() if v != ""])
