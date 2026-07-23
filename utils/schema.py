from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BASE_FIELDS = ["ID", "Nome", "Cognome", "Struttura"]


def load_column_order(path: str | Path) -> list[str]:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as file:
        columns = json.load(file)
    return list(dict.fromkeys(columns))


def ensure_schema(df: pd.DataFrame, column_order: list[str], fill_value: str = "NA") -> pd.DataFrame:
    """Aggiunge le colonne mancanti e applica l'ordine canonico.

    Le colonne extra del file originale sono mantenute in coda durante la
    lavorazione; il download finale può selezionare il solo ordine canonico.
    """
    out = df.copy()
    missing = [column for column in column_order if column not in out.columns]
    if missing:
        additions = pd.DataFrame(fill_value, index=out.index, columns=missing)
        out = pd.concat([out, additions], axis=1)
    extra = [column for column in out.columns if column not in column_order]
    return out[column_order + extra]


def coerce_base_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizzazione leggera delle intestazioni del dataset."""
    out = df.copy()
    rename = {column: str(column).strip() for column in out.columns if str(column).strip() != column}
    return out.rename(columns=rename) if rename else out
