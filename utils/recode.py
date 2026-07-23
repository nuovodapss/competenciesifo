from __future__ import annotations

import pandas as pd


LEVELS = ["NA", "N", "Pav", "C", "A", "E"]

# Ordinale tecnico usato quando è utile mantenere la successione dei livelli.
STR_TO_NUM = {
    None: 0,
    "": 0,
    "NA": 0,
    "N": 1,
    "PAV": 2,
    "Pav": 2,
    "C": 3,
    "A": 4,
    "E": 5,
}

NUM_TO_STR = {0: "NA", 1: "N", 2: "Pav", 3: "C", 4: "A", 5: "E"}

# Scala visualizzata nell'Applicativo Competenze di riferimento.
# NA è escluso dal calcolo; N rappresenta il livello iniziale (0/100).
LEVEL_TO_SCORE = {"N": 0.0, "Pav": 25.0, "C": 50.0, "A": 75.0, "E": 100.0}


def normalize_level(x: object) -> str:
    """Normalizza qualsiasi input in: NA, N, Pav, C, A, E."""
    if x is None or pd.isna(x):
        return "NA"
    s = str(x).strip()
    if not s or s in {"-", "—"}:
        return "NA"
    s_up = s.upper()
    if s_up in {"NA", "N", "C", "A", "E"}:
        return s_up
    if s_up in {"PAV", "PAV.", "P.AV", "P.AV."}:
        return "Pav"
    return "NA"


def display_level(level: object) -> str:
    normalized = normalize_level(level)
    if normalized == "NA":
        return "—"
    if normalized == "Pav":
        return "PAV"
    return normalized


def recode_series_to_num(s: pd.Series) -> pd.Series:
    return s.apply(normalize_level).map(STR_TO_NUM).fillna(0).astype(int)


def recode_df_to_num(df: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in codes:
        if c in out.columns:
            out[c] = recode_series_to_num(out[c])
    return out


def score_levels(values: pd.Series | list[object]) -> float:
    """Calcola lo score 0–100 ignorando esclusivamente i valori NA."""
    series = pd.Series(values, dtype="object").apply(normalize_level)
    valid = series[series != "NA"]
    if valid.empty:
        return 0.0
    return float(valid.map(LEVEL_TO_SCORE).fillna(0.0).mean())


def score_percent(values_num: pd.Series) -> float:
    """Compatibilità con la precedente API basata su ordinali 0–5.

    La funzione interpreta 0 come NA e converte 1..5 nei livelli N..E,
    applicando la scala ufficiale 0/25/50/75/100.
    """
    levels = values_num.map(NUM_TO_STR)
    return score_levels(levels)


def score_sum(values_num: pd.Series) -> int:
    return int(values_num.fillna(0).sum())
