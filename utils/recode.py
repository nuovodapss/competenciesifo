from __future__ import annotations
import pandas as pd

LEVELS = ["NA", "N", "Pav", "C", "A", "E"]

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

NUM_TO_STR = {v: k for k, v in STR_TO_NUM.items() if k not in (None, "")}
NUM_TO_STR[0] = "NA"
NUM_TO_STR[1] = "N"
NUM_TO_STR[2] = "Pav"
NUM_TO_STR[3] = "C"
NUM_TO_STR[4] = "A"
NUM_TO_STR[5] = "E"

def normalize_level(x) -> str:
    """Normalize any input to one of: NA, N, Pav, C, A, E."""
    if x is None:
        return "NA"
    s = str(x).strip()
    if s == "":
        return "NA"
    s_up = s.upper()
    if s_up in ("NA", "N", "C", "A", "E"):
        return s_up if s_up != "NA" else "NA"
    if s_up in ("PAV", "PAV.", "P.AV", "P.AV."):
        return "Pav"
    if s == "Pav":
        return "Pav"
    # fallback
    return "NA"

def recode_series_to_num(s: pd.Series) -> pd.Series:
    s_norm = s.apply(normalize_level)
    return s_norm.map(STR_TO_NUM).fillna(0).astype(int)

def recode_df_to_num(df: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in codes:
        if c in out.columns:
            out[c] = recode_series_to_num(out[c])
    return out

def score_percent(values_num: pd.Series) -> float:
    """Compute percent score 0-100 ignoring NA (0) by default.
    If all are NA, returns 0.
    """
    # treat 0 as missing for mean; keep others
    nonzero = values_num.replace(0, pd.NA).dropna()
    if len(nonzero) == 0:
        return 0.0
    return float(nonzero.mean() / 5 * 100)

def score_sum(values_num: pd.Series) -> int:
    return int(values_num.fillna(0).sum())
