from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Guide:
    df: pd.DataFrame  # Pannello, Dimensione, Codice, Competenza, Descrizione

    @property
    def panels(self) -> list[str]:
        return list(self.df["Pannello"].dropna().unique())

    @property
    def dimensions(self) -> list[str]:
        return list(self.df["Dimensione"].dropna().unique())

    @property
    def codes(self) -> list[str]:
        return self.df["Codice"].astype(str).tolist()

    def filter_by_panels(self, panels: list[str]) -> pd.DataFrame:
        return self.df[self.df["Pannello"].isin(panels)].copy()

    def codes_by_dimension(self, panels: list[str] | None = None) -> dict[str, list[str]]:
        dff = self.df if panels is None else self.filter_by_panels(panels)
        out: dict[str, list[str]] = {}
        for dim, group in dff.groupby("Dimensione", sort=False):
            out[str(dim)] = group["Codice"].astype(str).tolist()
        return out


def load_guide(guide_path: str | Path) -> Guide:
    guide_path = Path(guide_path)
    df = pd.read_excel(guide_path)
    df = df.rename(columns={c: str(c).strip() for c in df.columns})

    required = ["Pannello", "Dimensione", "Codice", "Competenza"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Guida competenze: colonne mancanti: {missing}. Trovate: {list(df.columns)}")

    if "Descrizione" not in df.columns:
        df["Descrizione"] = ""

    for col in ["Pannello", "Dimensione", "Codice", "Competenza", "Descrizione"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    return Guide(df=df[["Pannello", "Dimensione", "Codice", "Competenza", "Descrizione"]].copy())
