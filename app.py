from __future__ import annotations

from datetime import datetime
import hashlib
import html
from io import BytesIO
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from utils.export import update_excel_bytes
from utils.governance import GovernanceData, load_governance
from utils.io import normalize_competence_columns, read_department_excel
from utils.recode import LEVELS, normalize_level, recode_series_to_num, score_percent


APP_DIR = Path(__file__).resolve().parent
GOVERNANCE_DIR = APP_DIR / "00_GOVERNANCE"
STYLE_PATH = APP_DIR / "assets" / "style.css"
BASE_COLUMNS = ["ID", "Nome", "Cognome", "Struttura"]
ALL_STRUCTURES = "Tutte le strutture"
ALL_AREAS = "Tutte le aree"

st.set_page_config(
    page_title="Competenze DAPSS — Coordinatori",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _level_label(level: str) -> str:
    return "PAV" if normalize_level(level) == "Pav" else normalize_level(level)


def _safe_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _person_id(value: object) -> str:
    text = _safe_text(value)
    return text[:-2] if text.endswith(".0") else text


def _person_label(row: pd.Series) -> str:
    surname = _safe_text(row.get("Cognome", ""))
    name = _safe_text(row.get("Nome", ""))
    structure = _safe_text(row.get("Struttura", ""))
    identifier = _person_id(row.get("ID", ""))
    identity = " ".join(part for part in [surname, name] if part).strip() or "Professionista"
    suffix = " · ".join(part for part in [structure, f"ID {identifier}" if identifier else ""] if part)
    return f"{identity} · {suffix}" if suffix else identity


def _markdown_bullets(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    lines: list[str] = []
    for line in text.split("\n"):
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.startswith("•"):
            cleaned = "- " + cleaned.lstrip("•").strip()
        lines.append(cleaned)
    return "\n".join(lines)


def _mark_dirty() -> None:
    st.session_state["unsaved_changes"] = True


@st.cache_data(show_spinner=False)
def _read_css() -> str:
    return STYLE_PATH.read_text(encoding="utf-8") if STYLE_PATH.exists() else ""


@st.cache_data(show_spinner=False)
def _load_governance() -> GovernanceData:
    return load_governance(GOVERNANCE_DIR)


def _reset_for_new_file() -> None:
    prefixes = ("level::",)
    exact_keys = {
        "df_work",
        "source_excel_bytes",
        "source_filename",
        "loaded_file_key",
        "unsaved_changes",
        "has_saved",
        "export_bytes",
        "last_saved_at",
        "filter_area",
        "filter_structure",
        "filter_professional",
        "competence_search",
    }
    for key in list(st.session_state):
        if key in exact_keys or any(key.startswith(prefix) for prefix in prefixes):
            del st.session_state[key]


def _save_all_drafts(file_key: str, all_codes: list[str]) -> None:
    df_work: pd.DataFrame = st.session_state["df_work"].copy()
    prefix = f"level::{file_key}::"

    for key, raw_level in list(st.session_state.items()):
        if not key.startswith(prefix):
            continue
        remainder = key[len(prefix):]
        try:
            row_text, code = remainder.split("::", 1)
            row_index = int(row_text)
        except (ValueError, TypeError):
            continue
        if row_index not in df_work.index or code not in df_work.columns:
            continue
        df_work.at[row_index, code] = normalize_level(raw_level)

    for code in all_codes:
        if code in df_work.columns:
            df_work[code] = df_work[code].apply(normalize_level)

    xlsx_bytes = update_excel_bytes(
        st.session_state["source_excel_bytes"],
        df_work,
    )
    st.session_state["df_work"] = df_work
    st.session_state["export_bytes"] = xlsx_bytes
    st.session_state["has_saved"] = True
    st.session_state["unsaved_changes"] = False
    st.session_state["last_saved_at"] = datetime.now().strftime("%d/%m/%Y alle %H:%M")


css = _read_css()
if css:
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

try:
    governance = _load_governance()
except Exception as exc:
    st.error(f"Non è stato possibile caricare 00_GOVERNANCE: {exc}")
    st.stop()

catalogue = governance.catalogue.copy()
all_codes = governance.codes
transversal_dimensions = catalogue.loc[
    catalogue["Pannello"].astype(str).str.strip().str.lower().eq("trasversali"),
    "Dimensione",
].astype(str).drop_duplicates().tolist()

st.markdown(
    """
    <div class="app-shell-header">
      <div class="app-brand-mark">DAPSS</div>
      <div class="app-brand-copy">
        <div class="app-brand-title">Gestione competenze</div>
        <div class="app-brand-subtitle">Modifica e download dei file di valutazione</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

header_columns = st.columns([1.05, 1.2, 1.45, 2.25, 0.72], gap="large")

with header_columns[4]:
    st.markdown("<div class='snapshot-label'>File</div>", unsafe_allow_html=True)
    with st.popover("📦 Snapshot", use_container_width=True):
        uploaded = st.file_uploader(
            "Carica il file Excel scaricato dal Drive",
            type=["xlsx"],
            accept_multiple_files=False,
            key="snapshot_upload",
        )
        st.caption(
            "L’app modifica una copia del file. Dopo il download dovrai ricaricarla manualmente sul Drive."
        )
        if uploaded is not None:
            st.success(f"File attivo: {uploaded.name}")

if uploaded is None:
    with header_columns[0]:
        st.selectbox("Professione", ["Infermieri"], disabled=True)
    with header_columns[1]:
        st.selectbox("Area", [ALL_AREAS], disabled=True)
    with header_columns[2]:
        st.selectbox("Struttura", [ALL_STRUCTURES], disabled=True)
    with header_columns[3]:
        st.selectbox("Professionista", ["Carica uno Snapshot"], disabled=True)

    st.markdown("<div class='top-rule'></div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="empty-state-card">
          <div class="empty-state-icon">📄</div>
          <div class="empty-state-title">Carica il file da modificare</div>
          <div class="empty-state-copy">
            Apri <strong>Snapshot</strong>, seleziona il file Excel scaricato dal Drive e poi scegli il professionista.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

raw_bytes = uploaded.getvalue()
file_hash = hashlib.sha256(raw_bytes).hexdigest()
file_key = f"{uploaded.name}:{file_hash}"

if st.session_state.get("loaded_file_key") != file_key:
    _reset_for_new_file()
    try:
        incoming = read_department_excel(BytesIO(raw_bytes))
    except Exception as exc:
        st.error(f"Non è stato possibile leggere il file Excel: {exc}")
        st.stop()

    missing = [column for column in BASE_COLUMNS if column not in incoming.columns]
    if missing:
        st.error(
            "Il file non contiene tutte le colonne richieste: "
            f"{', '.join(missing)}. Colonne trovate: {', '.join(map(str, incoming.columns))}"
        )
        st.stop()

    incoming = normalize_competence_columns(incoming, all_codes).reset_index(drop=True)
    st.session_state["df_work"] = incoming
    st.session_state["source_excel_bytes"] = raw_bytes
    st.session_state["source_filename"] = uploaded.name
    st.session_state["loaded_file_key"] = file_key
    st.session_state["unsaved_changes"] = False
    st.session_state["has_saved"] = False
    st.session_state["export_bytes"] = None
    st.session_state["last_saved_at"] = None


df_work: pd.DataFrame = st.session_state["df_work"]
if df_work.empty:
    st.warning("Il file caricato non contiene professionisti da modificare.")
    st.stop()

with header_columns[0]:
    st.selectbox("Professione", ["Infermieri"], disabled=True)

area_column = next((column for column in df_work.columns if _norm(column) == "area"), None)
if area_column:
    area_values = sorted(
        value
        for value in df_work[area_column].dropna().astype(str).map(str.strip).unique()
        if value
    )
    area_options = [ALL_AREAS, *area_values]
    if st.session_state.get("filter_area") not in area_options:
        st.session_state["filter_area"] = ALL_AREAS
    with header_columns[1]:
        selected_area = st.selectbox("Area", area_options, key="filter_area")
else:
    with header_columns[1]:
        selected_area = st.selectbox("Area", [ALL_AREAS], disabled=True)

filtered_people = df_work.copy()
if area_column and selected_area != ALL_AREAS:
    filtered_people = filtered_people[
        filtered_people[area_column].fillna("").astype(str).str.strip().eq(selected_area)
    ]

structures = sorted(
    value
    for value in filtered_people["Struttura"].dropna().astype(str).map(str.strip).unique()
    if value
)
structure_options = [ALL_STRUCTURES, *structures]
if st.session_state.get("filter_structure") not in structure_options:
    st.session_state["filter_structure"] = ALL_STRUCTURES
with header_columns[2]:
    selected_structure = st.selectbox("Struttura", structure_options, key="filter_structure")

if selected_structure != ALL_STRUCTURES:
    filtered_people = filtered_people[
        filtered_people["Struttura"].fillna("").astype(str).str.strip().eq(selected_structure)
    ]

professional_options = list(filtered_people.index)
if not professional_options:
    st.error("Nessun professionista corrisponde ai filtri selezionati.")
    st.stop()
if st.session_state.get("filter_professional") not in professional_options:
    st.session_state["filter_professional"] = professional_options[0]
with header_columns[3]:
    selected_row = st.selectbox(
        "Professionista",
        professional_options,
        key="filter_professional",
        format_func=lambda index: _person_label(df_work.loc[index]),
    )

st.markdown("<div class='top-rule'></div>", unsafe_allow_html=True)

edit_tab, download_tab = st.tabs(["Modifica", "Download"])

selected_person = df_work.loc[selected_row]
selected_person_name = " ".join(
    part
    for part in [
        _safe_text(selected_person.get("Nome", "")),
        _safe_text(selected_person.get("Cognome", "")),
    ]
    if part
).strip()
selected_person_structure = _safe_text(selected_person.get("Struttura", ""))

mapped_dimensions = governance.dimensions_for_structure(selected_person_structure)
if mapped_dimensions:
    scope_dimensions = mapped_dimensions
else:
    populated_dimensions = catalogue.loc[
        catalogue["Codice"].map(
            lambda code: normalize_level(df_work.at[selected_row, code]) != "NA"
            if code in df_work.columns
            else False
        ),
        "Dimensione",
    ].astype(str).drop_duplicates().tolist()
    scope_dimensions = list(dict.fromkeys([*transversal_dimensions, *populated_dimensions]))

scope_df = catalogue[catalogue["Dimensione"].isin(scope_dimensions)].copy()
if scope_df.empty:
    scope_df = catalogue[catalogue["Dimensione"].isin(transversal_dimensions)].copy()
scope_df = scope_df.sort_values("_ordine")

with edit_tab:
    heading_left, heading_right = st.columns([4.6, 1.15], gap="large")
    with heading_left:
        st.markdown("<h1 class='page-title'>Modifica competenze</h1>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='page-subtitle'>"
            f"{html.escape(selected_person_name or 'Professionista')} · "
            f"{html.escape(selected_person_structure or 'Struttura non indicata')} · "
            f"matricola {html.escape(_person_id(selected_person.get('ID', '')) or '—')}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with heading_right:
        st.markdown("<div class='save-button-spacer'></div>", unsafe_allow_html=True)
        save_clicked = st.button(
            "Salva modifiche",
            type="primary",
            use_container_width=True,
            key="save_top",
        )

    if save_clicked:
        try:
            _save_all_drafts(file_key, all_codes)
            st.toast("Modifiche salvate. Il file è pronto per il download.", icon="✅")
        except Exception as exc:
            st.error(f"Non è stato possibile salvare il file: {exc}")

    status_columns = st.columns([1.25, 1.25, 4.5])
    with status_columns[0]:
        if st.session_state.get("unsaved_changes"):
            st.markdown("<div class='status-chip status-dirty'>● Modifiche da salvare</div>", unsafe_allow_html=True)
        elif st.session_state.get("has_saved"):
            st.markdown("<div class='status-chip status-saved'>✓ Modifiche salvate</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='status-chip status-neutral'>Nessuna modifica</div>", unsafe_allow_html=True)
    with status_columns[1]:
        st.markdown(
            f"<div class='status-chip status-neutral'>{len(scope_df)} competenze</div>",
            unsafe_allow_html=True,
        )

    search = st.text_input(
        "Cerca una competenza",
        placeholder="Codice, titolo, definizione o descrittore…",
        key="competence_search",
    )
    displayed_df = scope_df.copy()
    if search.strip():
        query = search.strip().lower()
        searchable_columns = [
            "Codice",
            "Competenza",
            "Definizione / Razionale",
            "Attitudini",
            "Motivazioni",
            "Skills",
            "Conoscenze",
        ]
        mask = pd.Series(False, index=displayed_df.index)
        for column in searchable_columns:
            mask = mask | displayed_df[column].fillna("").astype(str).str.lower().str.contains(
                query, regex=False
            )
        displayed_df = displayed_df[mask]

    st.caption(
        "Clicca il livello sulla destra: si aprono la scelta del livello, il descrittore Benner, "
        "la definizione e i descrittori presenti nel file Mappe."
    )

    dimensions = displayed_df["Dimensione"].astype(str).drop_duplicates().tolist()
    card_columns = st.columns(3, gap="large")

    for dimension_position, dimension in enumerate(dimensions):
        dimension_df = displayed_df[displayed_df["Dimensione"].astype(str).eq(dimension)].copy()

        draft_levels: list[str] = []
        for code in dimension_df["Codice"].astype(str):
            widget_key = f"level::{file_key}::{selected_row}::{code}"
            initial_level = normalize_level(df_work.at[selected_row, code])
            if widget_key not in st.session_state:
                st.session_state[widget_key] = initial_level
            draft_levels.append(normalize_level(st.session_state[widget_key]))

        score = round(score_percent(recode_series_to_num(pd.Series(draft_levels)))) if draft_levels else 0

        with card_columns[dimension_position % 3]:
            with st.container(border=True):
                st.markdown(
                    f"<div class='competence-card-head'>"
                    f"<span>{html.escape(dimension)}</span>"
                    f"<strong>{int(score)}<small>/100</small></strong>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                for _, competence in dimension_df.iterrows():
                    code = str(competence["Codice"])
                    widget_key = f"level::{file_key}::{selected_row}::{code}"
                    current_level = normalize_level(st.session_state[widget_key])
                    row_left, row_right = st.columns([5.2, 1.15], gap="small")

                    with row_left:
                        st.markdown(
                            f"<div class='competence-row'>"
                            f"<span class='competence-code'>{html.escape(code)}</span>"
                            f"<span class='competence-name'>{html.escape(str(competence['Competenza']))}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                    with row_right:
                        with st.popover(_level_label(current_level), use_container_width=True):
                            selected_level = st.radio(
                                "Livello di competenza",
                                options=LEVELS,
                                key=widget_key,
                                format_func=_level_label,
                                horizontal=True,
                                on_change=_mark_dirty,
                            )
                            selected_level = normalize_level(selected_level)

                            level_tab, competence_tab, descriptors_tab = st.tabs(
                                ["Livello", "Competenza", "Descrittori"]
                            )
                            with level_tab:
                                if selected_level == "NA":
                                    st.info("Nessun livello attribuito: la competenza è non applicabile o non valutata.")
                                else:
                                    level_description = _safe_text(
                                        competence.get(f"Livello_{selected_level}", "")
                                    )
                                    st.markdown(
                                        f"**Descrittore {_level_label(selected_level)}**"
                                    )
                                    if level_description:
                                        st.write(level_description)
                                    else:
                                        st.warning("Descrittore del livello non disponibile.")

                            with competence_tab:
                                definition = _safe_text(
                                    competence.get("Definizione / Razionale", "")
                                )
                                if definition:
                                    st.write(definition)
                                else:
                                    st.info("Definizione della competenza non disponibile.")

                            with descriptors_tab:
                                for label, column in [
                                    ("Attitudini", "Attitudini"),
                                    ("Motivazioni", "Motivazioni"),
                                    ("Skills", "Skills"),
                                    ("Conoscenze", "Conoscenze"),
                                ]:
                                    descriptor = _markdown_bullets(competence.get(column, ""))
                                    st.markdown(f"**{label}**")
                                    if descriptor:
                                        st.markdown(descriptor)
                                    else:
                                        st.caption("Non disponibile")

                st.markdown("<div class='card-bottom-space'></div>", unsafe_allow_html=True)

    if displayed_df.empty:
        st.info("Nessuna competenza corrisponde alla ricerca.")

    st.markdown("<div class='bottom-save-rule'></div>", unsafe_allow_html=True)
    bottom_left, bottom_right = st.columns([4.7, 1.3], gap="large")
    with bottom_left:
        st.caption(
            "Salva prima di passare al download. Il salvataggio prepara la copia Excel ma non scrive sul Drive."
        )
    with bottom_right:
        if st.button(
            "Salva modifiche",
            type="primary",
            use_container_width=True,
            key="save_bottom",
        ):
            try:
                _save_all_drafts(file_key, all_codes)
                st.toast("Modifiche salvate. Apri la scheda Download.", icon="✅")
            except Exception as exc:
                st.error(f"Non è stato possibile salvare il file: {exc}")

with download_tab:
    st.markdown("<h1 class='page-title'>Download</h1>", unsafe_allow_html=True)
    st.markdown(
        "<div class='page-subtitle'>Scarica il file salvato e ricaricalo manualmente nella stessa cartella Drive.</div>",
        unsafe_allow_html=True,
    )

    ready_for_download = bool(st.session_state.get("has_saved")) and not bool(
        st.session_state.get("unsaved_changes")
    )

    if st.session_state.get("unsaved_changes"):
        st.warning("Ci sono modifiche non salvate. Premi Salva prima di scaricare il file.")
    elif not st.session_state.get("has_saved"):
        st.info("Premi Salva modifiche nella scheda Modifica per preparare il file da scaricare.")
    else:
        st.success(f"File pronto · salvato il {st.session_state.get('last_saved_at')}")

    download_card_left, download_card_right = st.columns([2.3, 1.2], gap="large")
    with download_card_left:
        st.markdown(
            f"""
            <div class="download-card">
              <div class="download-file-label">FILE PRONTO</div>
              <div class="download-file-name">{html.escape(st.session_state['source_filename'])}</div>
              <div class="download-file-copy">
                Il nome del file rimane invariato. Gli altri fogli e la formattazione esistente vengono preservati.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with download_card_right:
        st.download_button(
            "Scarica file aggiornato",
            data=st.session_state.get("export_bytes") or b"",
            file_name=st.session_state["source_filename"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            disabled=not ready_for_download,
        )
        st.caption("Il download non aggiorna automaticamente il Drive.")

    st.markdown(
        """
        <div class="drive-steps">
          <div><strong>1.</strong> Scarica il file aggiornato.</div>
          <div><strong>2.</strong> Apri la cartella Drive di origine.</div>
          <div><strong>3.</strong> Ricarica il file e sostituisci la versione precedente.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
