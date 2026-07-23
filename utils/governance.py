from __future__ import annotations

from pathlib import Path
import re
import unicodedata

import pandas as pd


_CODE_ALIASES = {
    "codice",
    "codice competenza",
    "codice della competenza",
    "id competenza",
    "id_competenza",
    "codice_competenza",
}
_DESCRIPTION_ALIASES = {
    "descrizione",
    "descrizione competenza",
    "descrizione della competenza",
    "definizione",
    "descrittore",
    "descrittori",
    "comportamento atteso",
    "comportamenti attesi",
    "elementi descrittivi",
    "note descrittive",
}
_COMPETENCE_ALIASES = {
    "competenza",
    "nome competenza",
    "titolo competenza",
    "denominazione competenza",
}


def _norm(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text)


def _find_column(columns: list[object], aliases: set[str]) -> str | None:
    normalized = {_norm(col): str(col) for col in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]

    # Tolleranza per intestazioni più lunghe, ad esempio
    # "Descrizione sintetica della competenza".
    for norm_col, original in normalized.items():
        if any(alias in norm_col for alias in aliases):
            return original
    return None


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if text.lower() in {"nan", "none", "-", "—"}:
        return ""
    return text


def _read_tables(path: Path) -> list[pd.DataFrame]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        book = pd.ExcelFile(path)
        return [pd.read_excel(path, sheet_name=sheet) for sheet in book.sheet_names]
    if suffix == ".csv":
        # sep=None usa il rilevamento automatico e gestisce sia ; sia ,.
        return [pd.read_csv(path, sep=None, engine="python")]
    return []


def load_governance_descriptions(
    directories: list[str | Path],
    guide_df: pd.DataFrame,
) -> tuple[dict[str, str], list[str]]:
    """Carica descrizioni delle competenze dai file di 00_GOVERNANCE.

    Il matching avviene prima per ``Codice`` e, come fallback, per testo della
    ``Competenza``. Sono supportati Excel e CSV, anche con più fogli e con
    intestazioni leggermente differenti.

    Returns
    -------
    descriptions:
        Dizionario ``codice -> descrizione``.
    sources:
        Elenco dei file dai quali è stata ricavata almeno una descrizione.
    """

    title_to_codes: dict[str, list[str]] = {}
    for _, row in guide_df.iterrows():
        code = _clean_text(row.get("Codice"))
        title = _norm(row.get("Competenza"))
        if code and title:
            title_to_codes.setdefault(title, []).append(code)

    descriptions: dict[str, str] = {}
    used_sources: list[str] = []
    seen_files: set[Path] = set()

    for directory in directories:
        base = Path(directory).expanduser()
        if not base.exists() or not base.is_dir():
            continue

        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".xlsx", ".xlsm", ".xls", ".csv"}:
                continue
            if path.name.startswith("~$") or path in seen_files:
                continue
            seen_files.add(path)

            source_used = False
            try:
                tables = _read_tables(path)
            except Exception:
                # Un file non leggibile non deve bloccare l'applicazione.
                continue

            for table in tables:
                if table.empty:
                    continue
                table = table.rename(columns={c: str(c).strip() for c in table.columns})
                columns = list(table.columns)
                code_col = _find_column(columns, _CODE_ALIASES)
                description_col = _find_column(columns, _DESCRIPTION_ALIASES)
                competence_col = _find_column(columns, _COMPETENCE_ALIASES)

                if description_col is None:
                    continue

                for _, row in table.iterrows():
                    description = _clean_text(row.get(description_col))
                    if not description:
                        continue

                    target_codes: list[str] = []
                    if code_col is not None:
                        code = _clean_text(row.get(code_col))
                        if code:
                            target_codes = [code]
                    elif competence_col is not None:
                        title = _norm(row.get(competence_col))
                        target_codes = title_to_codes.get(title, [])

                    for code in target_codes:
                        # Il primo testo valido è mantenuto per rendere il risultato
                        # deterministico quando più file contengono lo stesso codice.
                        if code not in descriptions:
                            descriptions[code] = description
                            source_used = True

            if source_used:
                used_sources.append(str(path))

    return descriptions, used_sources
