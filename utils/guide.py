from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

@dataclass(frozen=True)
class Guide:
    df: pd.DataFrame  # columns: Pannello, Dimensione, Codice, Competenza

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
        for dim, g in dff.groupby("Dimensione", sort=False):
            out[dim] = g["Codice"].astype(str).tolist()
        return out

    def codes_by_panel_and_dimension(self, panels: list[str] | None = None) -> dict[str, dict[str, list[str]]]:
        dff = self.df if panels is None else self.filter_by_panels(panels)
        out: dict[str, dict[str, list[str]]] = {}
        for panel, g1 in dff.groupby("Pannello", sort=False):
            out[panel] = {}
            for dim, g2 in g1.groupby("Dimensione", sort=False):
                out[panel][dim] = g2["Codice"].astype(str).tolist()
        return out

def load_guide(guide_path: str | Path) -> Guide:
    guide_path = Path(guide_path)
    df = pd.read_excel(guide_path)
    df = df.rename(columns={c: c.strip() for c in df.columns})
    required = ["Pannello", "Dimensione", "Codice", "Competenza"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Guida competenze: colonne mancanti: {missing}. Trovate: {list(df.columns)}")
    # clean
    df["Pannello"] = df["Pannello"].astype(str).str.strip()
    df["Dimensione"] = df["Dimensione"].astype(str).str.strip()
    df["Codice"] = df["Codice"].astype(str).str.strip()
    df["Competenza"] = df["Competenza"].astype(str).str.strip()
    return Guide(df=df)
