from __future__ import annotations

from pathlib import Path
import yaml

def load_structure_dimensions(path: str | Path) -> dict[str, list[str]]:
    """Load mapping Struttura -> Dimensioni (come da tabella fornita dalla Direzione).

    File YAML atteso:
        DEFAULT: []
        Cardiologia:
          - ...
    """
    path = Path(path)
    if not path.exists():
        return {"DEFAULT": []}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "DEFAULT" not in data:
        data["DEFAULT"] = []
    # normalizza: list di stringhe
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if v is None:
            out[str(k)] = []
        elif isinstance(v, list):
            out[str(k)] = [str(x).strip() for x in v if str(x).strip()]
        else:
            out[str(k)] = [str(v).strip()] if str(v).strip() else []
    return out

def guess_dimensions_from_structure(structure: str, available_dimensions: list[str]) -> list[str]:
    """Fallback leggero: se non troviamo la Struttura in mappa, non imponiamo nulla."""
    _ = structure
    _ = available_dimensions
    return []

# Backward-compat alias (vecchio nome)
def load_structure_panels(path: str | Path) -> dict[str, list[str]]:
    return load_structure_dimensions(path)
