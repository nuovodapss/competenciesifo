from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from utils.export import to_excel_bytes
from utils.governance import load_governance_descriptions
from utils.guide import load_guide
from utils.io import detect_structure_values, normalize_competence_columns, read_department_excel
from utils.panels import guess_dimensions_from_structure, load_structure_dimensions
from utils.recode import LEVELS, display_level, normalize_level, score_levels
from utils.schema import coerce_base_columns, ensure_schema, load_column_order


APP_DIR = Path(__file__).parent
GUIDE_PATH = APP_DIR / "data" / "guida_competenze.xlsx"
COLUMN_ORDER_PATH = APP_DIR / "config" / "column_order.json"
STRUCTURE_DIMENSIONS_PATH = APP_DIR / "config" / "structure_dimensions.yml"
STYLE_PATH = APP_DIR / "assets" / "style.css"

st.set_page_config(
    page_title="APPGrade — Modifica competenze",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def _load_guide_df() -> pd.DataFrame:
    guide_df = load_guide(GUIDE_PATH).df.copy()

    governance_dirs: list[Path] = [
        APP_DIR / "00_GOVERNANCE",
        APP_DIR / "data" / "00_GOVERNANCE",
    ]
    configured_dir = os.getenv("GOVERNANCE_DIR", "").strip()
    if configured_dir:
        governance_dirs.insert(0, Path(configured_dir))

    descriptions, sources = load_governance_descriptions(governance_dirs, guide_df)
    guide_df["Descrizione"] = guide_df.apply(
        lambda row: descriptions.get(str(row["Codice"]), str(row.get("Descrizione", "")).strip()),
        axis=1,
    )
    guide_df.attrs["description_sources"] = sources
    return guide_df


@st.cache_data(show_spinner=False)
def _load_column_order() -> list[str]:
    return load_column_order(COLUMN_ORDER_PATH)


@st.cache_data(show_spinner=False)
def _load_structure_dimensions() -> dict[str, list[str]]:
    return load_structure_dimensions(STRUCTURE_DIMENSIONS_PATH)


@st.cache_data(show_spinner=False)
def _read_css() -> str:
    return STYLE_PATH.read_text(encoding="utf-8") if STYLE_PATH.exists() else ""


def _slug(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value)).strip("_") or "item"


def _row_token(row_index: object, row: pd.Series) -> str:
    raw = f"{row_index}|{row.get('ID', '')}|{row.get('Cognome', '')}|{row.get('Nome', '')}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _level_key(file_hash: str, row_token: str, code: str) -> str:
    return f"level_{file_hash}_{row_token}_{_slug(code)}"


def _score_for_codes(df: pd.DataFrame, row_index: object, codes: list[str]) -> int:
    existing = [code for code in codes if code in df.columns]
    if not existing:
        return 0
    return int(round(score_levels(df.loc[row_index, existing])))


def _estimate_card_weight(group: pd.DataFrame) -> float:
    weight = 1.8
    for _, row in group.iterrows():
        weight += 1.0
        description = str(row.get("Descrizione", "")).strip()
        if description:
            weight += min(2.0, max(0.4, len(description) / 150))
    return weight


def _apply_widget_values(
    df: pd.DataFrame,
    row_index: object,
    file_hash: str,
    row_token: str,
    codes: list[str],
) -> None:
    for code in codes:
        key = _level_key(file_hash, row_token, code)
        if key in st.session_state and code in df.columns:
            df.at[row_index, code] = normalize_level(st.session_state[key])


def _render_dimension_card(
    dimension: str,
    dimension_df: pd.DataFrame,
    full_dimension_df: pd.DataFrame,
    df_work: pd.DataFrame,
    selected_index: object,
    file_hash: str,
    row_token: str,
) -> None:
    full_codes = full_dimension_df["Codice"].astype(str).tolist()
    dimension_score = _score_for_codes(df_work, selected_index, full_codes)

    with st.container(border=True):
        st.markdown(
            "<div class='dimension-card-header'>"
            f"<div class='dimension-card-title'>{html.escape(str(dimension))}</div>"
            f"<div class='dimension-card-score'>{dimension_score}<span>/100</span></div>"
            "</div>",
            unsafe_allow_html=True,
        )

        for position, (_, competence) in enumerate(dimension_df.iterrows()):
            code = str(competence["Codice"])
            title = str(competence["Competenza"])
            description = str(competence.get("Descrizione", "")).strip()

            code_col, text_col, level_col = st.columns([0.9, 5.6, 1.15])
            with code_col:
                st.markdown(f"<div class='competence-code'>{html.escape(code)}</div>", unsafe_allow_html=True)
            with text_col:
                description_html = ""
                if description and description.casefold() != title.casefold():
                    description_html = (
                        f"<div class='competence-description'>{html.escape(description)}</div>"
                    )
                st.markdown(
                    f"<div class='competence-title'>{html.escape(title)}</div>{description_html}",
                    unsafe_allow_html=True,
                )
            with level_col:
                current_level = normalize_level(df_work.at[selected_index, code])
                key = _level_key(file_hash, row_token, code)
                selected_level = st.selectbox(
                    f"Livello {code}",
                    options=LEVELS,
                    index=LEVELS.index(current_level),
                    format_func=display_level,
                    key=key,
                    label_visibility="collapsed",
                )
                df_work.at[selected_index, code] = normalize_level(selected_level)

            if position < len(dimension_df) - 1:
                st.markdown("<div class='competence-divider'></div>", unsafe_allow_html=True)


def _render_panel(
    panel_title: str,
    panel_df: pd.DataFrame,
    full_panel_df: pd.DataFrame,
    df_work: pd.DataFrame,
    selected_index: object,
    file_hash: str,
    row_token: str,
) -> None:
    if panel_df.empty:
        return

    st.markdown(
        f"<div class='section-heading'>{html.escape(panel_title)}</div><div class='section-rule'></div>",
        unsafe_allow_html=True,
    )

    visible_groups = [(str(dim), group.copy()) for dim, group in panel_df.groupby("Dimensione", sort=False)]
    full_groups = {str(dim): group.copy() for dim, group in full_panel_df.groupby("Dimensione", sort=False)}

    assignments: list[list[tuple[str, pd.DataFrame]]] = [[], [], []]
    weights = [0.0, 0.0, 0.0]
    for dimension, group in visible_groups:
        target = min(range(3), key=lambda index: weights[index])
        assignments[target].append((dimension, group))
        weights[target] += _estimate_card_weight(group)

    columns = st.columns(3)
    for column, cards in zip(columns, assignments):
        with column:
            for dimension, group in cards:
                _render_dimension_card(
                    dimension=dimension,
                    dimension_df=group,
                    full_dimension_df=full_groups.get(dimension, group),
                    df_work=df_work,
                    selected_index=selected_index,
                    file_hash=file_hash,
                    row_token=row_token,
                )


css = _read_css()
if css:
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

guide_df = _load_guide_df()
column_order = _load_column_order()
structure_dim_map = _load_structure_dimensions()
all_codes = column_order[4:]

transversal_mask = guide_df["Pannello"].astype(str).str.strip().str.casefold() == "trasversali"
transversal_df = guide_df[transversal_mask].copy()
transversal_codes = transversal_df["Codice"].astype(str).tolist()
transversal_dimensions = transversal_df["Dimensione"].astype(str).drop_duplicates().tolist()
all_dimensions = guide_df["Dimensione"].astype(str).drop_duplicates().tolist()
specific_dimensions = [dimension for dimension in all_dimensions if dimension not in transversal_dimensions]

duplicate_codes = (
    guide_df["Codice"].astype(str).value_counts().loc[lambda counts: counts > 1].index.tolist()
)

with st.sidebar:
    st.markdown("<div class='sidebar-brand'>APPGrade</div>", unsafe_allow_html=True)
    st.caption("Modifica e download delle competenze")
    uploaded = st.file_uploader("File del reparto (.xlsx)", type=["xlsx"], accept_multiple_files=False)

if uploaded is None:
    st.markdown("<div class='empty-spacer'></div>", unsafe_allow_html=True)
    left, centre, right = st.columns([1, 1.5, 1])
    with centre:
        with st.container(border=True):
            st.markdown("<div class='upload-title'>Carica il file del reparto</div>", unsafe_allow_html=True)
            st.write(
                "Seleziona il file Excel scaricato dal Drive. Dopo il caricamento potrai modificare "
                "i livelli direttamente nelle schede e scaricare il file aggiornato."
            )
            st.info("Il file viene elaborato nella sessione corrente e non viene salvato dall'applicazione.")
    st.stop()

raw = uploaded.getvalue()
file_hash = hashlib.md5(raw).hexdigest()

if st.session_state.get("file_hash") != file_hash:
    try:
        df_input = read_department_excel(uploaded)
        df_input = coerce_base_columns(df_input)
    except Exception as exc:
        st.error(f"Impossibile leggere il file Excel: {exc}")
        st.stop()

    missing_base = [column for column in ["ID", "Nome", "Cognome", "Struttura"] if column not in df_input.columns]
    if missing_base:
        st.error(
            "Il file non contiene tutte le colonne richieste: "
            + ", ".join(missing_base)
            + "."
        )
        st.stop()

    df_work = ensure_schema(df_input, column_order, fill_value="NA")
    df_work = normalize_competence_columns(df_work, all_codes)

    st.session_state["file_hash"] = file_hash
    st.session_state["df_work"] = df_work
    st.session_state["uploaded_filename"] = uploaded.name
    st.session_state.pop("selected_structure", None)


df_work = st.session_state["df_work"]
structures = detect_structure_values(df_work)

with st.sidebar:
    st.markdown("---")
    st.markdown("#### File in lavorazione")
    st.markdown(
        f"<div class='file-chip'>{html.escape(st.session_state.get('uploaded_filename', uploaded.name))}</div>",
        unsafe_allow_html=True,
    )

    if not structures:
        structure = ""
        st.warning("La colonna Struttura è vuota: vengono mostrate le sole competenze trasversali.")
    elif len(structures) == 1:
        structure = structures[0]
        st.markdown(f"<div class='structure-label'>{html.escape(structure)}</div>", unsafe_allow_html=True)
    else:
        structure = st.selectbox(
            "Struttura",
            options=structures,
            index=structures.index(st.session_state.get("selected_structure", structures[0]))
            if st.session_state.get("selected_structure", structures[0]) in structures
            else 0,
        )
    st.session_state["selected_structure"] = structure

mapped_dimensions = []
if structure:
    mapped_dimensions = [
        dimension for dimension in structure_dim_map.get(structure, []) if dimension in specific_dimensions
    ]
    if not mapped_dimensions:
        mapped_dimensions = guess_dimensions_from_structure(structure, specific_dimensions)

with st.sidebar:
    if structure and not mapped_dimensions:
        with st.expander("Ambito competenze specifiche", expanded=True):
            selected_specific_dimensions = st.multiselect(
                "Dimensioni",
                options=specific_dimensions,
                default=[],
                help="La struttura non è presente nella mappa: seleziona le dimensioni specifiche da mostrare.",
            )
    else:
        selected_specific_dimensions = mapped_dimensions

    st.markdown("---")
    identity_df = df_work[["ID", "Cognome", "Nome"]].copy().astype(str)
    identity_df["row_index"] = df_work.index
    identity_df["label"] = (
        identity_df["Cognome"].str.strip()
        + " "
        + identity_df["Nome"].str.strip()
        + " · ID "
        + identity_df["ID"].str.strip()
    )
    duplicate_labels = identity_df["label"].duplicated(keep=False)
    identity_df.loc[duplicate_labels, "label"] = (
        identity_df.loc[duplicate_labels, "label"]
        + " · riga "
        + (identity_df.loc[duplicate_labels].index + 2).astype(str)
    )

    if identity_df.empty:
        st.error("Il file non contiene professionisti da modificare.")
        st.stop()

    selected_label = st.selectbox("Professionista", identity_df["label"].tolist())
    selected_index = identity_df.loc[identity_df["label"] == selected_label, "row_index"].iloc[0]
    selected_row = df_work.loc[selected_index]
    row_token = _row_token(selected_index, selected_row)

    view_mode = st.radio(
        "Visualizza",
        ["Trasversali", "Specifiche", "Tutte"],
        horizontal=True,
    )
    search_query = st.text_input("Cerca competenza", placeholder="Codice o testo")

scope_df = guide_df[
    guide_df["Codice"].astype(str).isin(transversal_codes)
    | guide_df["Dimensione"].astype(str).isin(selected_specific_dimensions)
].copy()

# Una sola colonna Excel può rappresentare un codice. In caso di duplicati si
# mantiene la prima definizione, coerentemente con il dataset di reparto.
scope_df = scope_df.drop_duplicates(subset=["Codice"], keep="first").copy()
editable_codes = scope_df["Codice"].astype(str).tolist()

_apply_widget_values(df_work, selected_index, file_hash, row_token, editable_codes)
st.session_state["df_work"] = df_work

if view_mode == "Trasversali":
    visible_scope = scope_df[scope_df["Codice"].astype(str).isin(transversal_codes)].copy()
elif view_mode == "Specifiche":
    visible_scope = scope_df[~scope_df["Codice"].astype(str).isin(transversal_codes)].copy()
else:
    visible_scope = scope_df.copy()

if search_query.strip():
    query = search_query.strip().casefold()
    visible_scope = visible_scope[
        visible_scope["Codice"].astype(str).str.casefold().str.contains(query, regex=False)
        | visible_scope["Competenza"].astype(str).str.casefold().str.contains(query, regex=False)
        | visible_scope["Descrizione"].astype(str).str.casefold().str.contains(query, regex=False)
    ].copy()

export_df = df_work.copy()
editable_set = set(editable_codes)
for code in all_codes:
    if code in export_df.columns:
        export_df[code] = export_df[code].apply(normalize_level)
        if code not in editable_set:
            export_df[code] = "NA"
export_df = export_df[column_order]

original_name = Path(st.session_state.get("uploaded_filename", uploaded.name)).stem
output_name = f"{original_name}_aggiornato.xlsx"
xlsx_bytes = to_excel_bytes(export_df)

with st.sidebar:
    st.markdown("---")
    st.download_button(
        "Scarica file aggiornato",
        data=xlsx_bytes,
        file_name=output_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
    st.caption("Le modifiche ai livelli vengono applicate automaticamente nella sessione.")

    with st.expander("Informazioni tecniche", expanded=False):
        described = int(scope_df["Descrizione"].astype(str).str.strip().ne("").sum())
        st.write(f"Descrizioni disponibili: **{described}/{len(scope_df)}**")
        sources = guide_df.attrs.get("description_sources", [])
        if sources:
            st.write(f"File governance letti: **{len(sources)}**")
        else:
            st.caption("Nessun file descrittivo rilevato nelle cartelle 00_GOVERNANCE.")
        if duplicate_codes:
            st.caption("Codici duplicati nella guida: " + ", ".join(duplicate_codes))

st.markdown(
    "<div class='page-kicker'>MODIFICA COMPETENZE</div>"
    f"<div class='person-heading'>{html.escape(str(selected_row['Cognome']))} "
    f"{html.escape(str(selected_row['Nome']))}</div>"
    f"<div class='person-subheading'>{html.escape(structure or 'Struttura non indicata')}</div>",
    unsafe_allow_html=True,
)

if visible_scope.empty:
    st.info("Nessuna competenza corrisponde ai filtri selezionati.")
    st.stop()

panel_order = visible_scope["Pannello"].astype(str).drop_duplicates().tolist()
for panel in panel_order:
    panel_visible = visible_scope[visible_scope["Pannello"].astype(str) == panel].copy()
    panel_full = scope_df[scope_df["Pannello"].astype(str) == panel].copy()
    title = "Competenze trasversali" if panel.casefold() == "trasversali" else panel
    _render_panel(
        panel_title=title,
        panel_df=panel_visible,
        full_panel_df=panel_full,
        df_work=df_work,
        selected_index=selected_index,
        file_hash=file_hash,
        row_token=row_token,
    )

st.session_state["df_work"] = df_work
