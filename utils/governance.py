from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd


LEVEL_COLUMN_MAP = {
    "N": "Novizio",
    "Pav": "Principiante avanzato",
    "C": "Competente",
    "A": "Abile",
    "E": "Esperto",
}


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class GovernanceData:
    catalogue: pd.DataFrame
    structure_dimensions: dict[str, list[str]]

    @property
    def codes(self) -> list[str]:
        return self.catalogue["Codice"].astype(str).tolist()

    def dimensions_for_structure(self, structure: str) -> list[str]:
        lookup = {_norm(k): v for k, v in self.structure_dimensions.items()}
        return list(lookup.get(_norm(structure), []))


def load_governance(root: str | Path) -> GovernanceData:
    root = Path(root)
    competence_map = root / "02_Mappe" / "Mappa_Competenze_INF.xlsx"
    structure_map = root / "02_Mappe" / "Mappa_Strutture_Dimensioni_Competenza_INF.xlsx"

    if not competence_map.exists():
        raise FileNotFoundError(f"Mappa competenze non trovata: {competence_map}")
    if not structure_map.exists():
        raise FileNotFoundError(f"Mappa strutture non trovata: {structure_map}")

    map_df = pd.read_excel(competence_map, sheet_name="Mappa", dtype=object)
    descriptors_df = pd.read_excel(competence_map, sheet_name="Descrittori", dtype=object)
    levels_df = pd.read_excel(competence_map, sheet_name="Livelli Benner", dtype=object)

    map_df = map_df.rename(columns={c: str(c).strip() for c in map_df.columns})
    required_map = [
        "Pannello",
        "Dimensione",
        "Codice",
        "Competenza",
        "Definizione / Razionale",
    ]
    missing = [c for c in required_map if c not in map_df.columns]
    if missing:
        raise ValueError(f"Mappa competenze: colonne mancanti {missing}")

    # La scheda Mappa contiene il perimetro ufficiale attivo.
    if "Selezionata" in map_df.columns:
        selected = map_df["Selezionata"].astype(str).str.strip().str.upper()
        map_df = map_df[selected.eq("SI")].copy()

    keep_map = required_map
    catalogue = map_df[keep_map].copy()
    for column in keep_map:
        catalogue[column] = catalogue[column].map(_clean_text)

    descriptor_columns = ["Codice", "Attitudini", "Motivazioni", "Skills", "Conoscenze"]
    missing_desc = [c for c in descriptor_columns if c not in descriptors_df.columns]
    if missing_desc:
        raise ValueError(f"Foglio Descrittori: colonne mancanti {missing_desc}")
    descriptors_df = descriptors_df[descriptor_columns].copy()
    for column in descriptor_columns:
        descriptors_df[column] = descriptors_df[column].map(_clean_text)
    descriptors_df = descriptors_df.drop_duplicates(subset=["Codice"], keep="first")

    level_columns = ["Codice", *LEVEL_COLUMN_MAP.values()]
    missing_levels = [c for c in level_columns if c not in levels_df.columns]
    if missing_levels:
        raise ValueError(f"Foglio Livelli Benner: colonne mancanti {missing_levels}")
    levels_df = levels_df[level_columns].copy()
    for column in level_columns:
        levels_df[column] = levels_df[column].map(_clean_text)
    levels_df = levels_df.drop_duplicates(subset=["Codice"], keep="first")
    levels_df = levels_df.rename(
        columns={source: f"Livello_{level}" for level, source in LEVEL_COLUMN_MAP.items()}
    )

    catalogue = catalogue.merge(descriptors_df, on="Codice", how="left")
    catalogue = catalogue.merge(levels_df, on="Codice", how="left")
    catalogue = catalogue.drop_duplicates(subset=["Codice"], keep="first").reset_index(drop=True)
    catalogue["_ordine"] = range(len(catalogue))

    structure_df = pd.read_excel(structure_map, sheet_name="Mappa", dtype=object)
    expected_structure = ["Struttura", "Dimensioni di Competenza Attivate"]
    missing_structure = [c for c in expected_structure if c not in structure_df.columns]
    if missing_structure:
        raise ValueError(f"Mappa strutture: colonne mancanti {missing_structure}")

    structure_dimensions: dict[str, list[str]] = {}
    for _, row in structure_df.iterrows():
        structure = _clean_text(row["Struttura"])
        raw_dimensions = _clean_text(row["Dimensioni di Competenza Attivate"])
        if not structure:
            continue
        dimensions = [part.strip() for part in raw_dimensions.split(";") if part.strip()]
        structure_dimensions[structure] = list(dict.fromkeys(dimensions))

    return GovernanceData(catalogue=catalogue, structure_dimensions=structure_dimensions)
