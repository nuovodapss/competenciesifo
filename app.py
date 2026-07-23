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
VIEWS = ["Panoramica", "Rosa reparto", "Professionista", "Similarità", "Cluster"]

st.set_page_config(
    page_title="Competenze DAPSS — Coordinatori",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _safe_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _person_id(value: object) -> str:
    text = _safe_text(value)
    return text[:-2] if text.endswith(".0") else text


def _full_name(row: pd.Series) -> str:
    name = _safe_text(row.get("Nome", ""))
    surname = _safe_text(row.get("Cognome", ""))
    return " ".join(part for part in [name, surname] if part).strip() or "Professionista"


def _person_label(row: pd.Series) -> str:
    structure = _safe_text(row.get("Struttura", ""))
    return f"{_full_name(row)} · {structure}" if structure else _full_name(row)


def _level_label(level: str) -> str:
    level = normalize_level(level)
    if level == "Pav":
        return "PAV"
    if level == "NA":
        return "—"
    return level


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
        "view_widget",
        "active_competence_row",
        "active_competence_code",
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

    xlsx_bytes = update_excel_bytes(st.session_state["source_excel_bytes"], df_work)
    st.session_state["df_work"] = df_work
    st.session_state["export_bytes"] = xlsx_bytes
    st.session_state["has_saved"] = True
    st.session_state["unsaved_changes"] = False
    st.session_state["last_saved_at"] = datetime.now().strftime("%d/%m/%Y alle %H:%M")


def _topbar(snapshot_label: str, count: int) -> None:
    st.markdown(
        f"""
        <div class="dapss-topbar">
          <div>
            <div class="dapss-eyebrow">Direzione delle Professioni Sanitarie</div>
            <div class="dapss-title">COMPETENZE DAPSS</div>
            <div class="dapss-subtitle">Cockpit direzionale · Infermieri · {count} professionisti</div>
          </div>
          <div class="dapss-status">
            <strong>{html.escape(snapshot_label)}</strong><br>
            <span class="dapss-subtitle">FILE DI VALUTAZIONE · modifica locale e download</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _profile_identity_card(person: pd.Series, profession_label: str, area_label: str) -> None:
    st.markdown(
        f"""
        <div class="dapss-profile-identity">
          <div class="dapss-profile-kicker">PROFILO PROFESSIONALE</div>
          <div class="dapss-profile-name">{html.escape(_full_name(person))}</div>
          <div class="dapss-profile-id">MATRICOLA {html.escape(_person_id(person.get('ID', '')) or '—')}</div>
          <div class="dapss-profile-meta">{html.escape(profession_label)}</div>
          <div class="dapss-profile-meta">{html.escape(_safe_text(person.get('Struttura', '')))}</div>
          <div class="dapss-profile-meta">{html.escape(area_label or '—')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _cluster_card() -> None:
    st.markdown(
        """
        <div class="dapss-role-card">
          <div class="dapss-kpi-label">CLUSTER DI APPARTENENZA</div>
          <div class="dapss-role-name">—</div>
          <div class="dapss-role-stars" aria-label="Aderenza al cluster 0 su 5">☆ ☆ ☆ ☆ ☆</div>
          <div class="dapss-role-note">Aderenza al cluster —</div>
          <div class="dapss-role-disclaimer">Le stelle indicano coerenza con il profilo del cluster.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _badge_shelf() -> None:
    st.markdown(
        """
        <div class="dapss-badge-shelf">
          <div class="dapss-kpi-label">BADGE</div>
          <div class="dapss-badge-list"><span class="dapss-badge-empty">Nessun badge attivo</span></div>
          <div class="dapss-kpi-note">Spazio predisposto per badge e credential</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _kpi_card(label: str, value: str, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="dapss-kpi">
          <div class="dapss-kpi-label">{html.escape(label)}</div>
          <div class="dapss-kpi-value">{html.escape(value)}</div>
          <div class="dapss-kpi-note">{html.escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _score_label(levels: list[str]) -> str:
    numeric = recode_series_to_num(pd.Series(levels))
    valid = numeric.dropna()
    if valid.empty:
        return "—"
    return str(int(round(score_percent(numeric))))


def _set_active_competence(selected_row: int, code: str) -> None:
    st.session_state["active_competence_row"] = selected_row
    st.session_state["active_competence_code"] = code


def _render_competence_detail_panel(selected_row: int, file_key: str, catalogue_df: pd.DataFrame) -> None:
    active_row = st.session_state.get("active_competence_row")
    active_code = st.session_state.get("active_competence_code")
    if active_row != selected_row or not active_code:
        return

    matches = catalogue_df[catalogue_df["Codice"].astype(str).eq(str(active_code))]
    if matches.empty:
        return
    competence = matches.iloc[0]
    widget_key = f"level::{file_key}::{selected_row}::{active_code}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = normalize_level("NA")

    panel_left, panel_right = st.columns([5.2, 1.2])
    with panel_left:
        st.markdown(
            f"""
            <div class="dapss-download-card">
              <div class="dapss-download-title">COMPETENZA SELEZIONATA</div>
              <div class="dapss-download-name">{html.escape(str(competence['Codice']))} · {html.escape(str(competence['Competenza']))}</div>
              <div class="dapss-download-copy">Modifica il livello Benner e consulta definizione e descrittori della singola competenza.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with panel_right:
        if st.button("Chiudi pannello", use_container_width=True, key=f"close_detail::{selected_row}::{active_code}"):
            st.session_state.pop("active_competence_row", None)
            st.session_state.pop("active_competence_code", None)
            st.rerun()

    tab_level, tab_comp, tab_desc = st.tabs(["Livello", "Competenza", "Descrittori"])
    with tab_level:
        st.radio(
            "Livello di competenza",
            options=LEVELS,
            key=widget_key,
            format_func=_level_label,
            horizontal=True,
            on_change=_mark_dirty,
        )
        chosen = normalize_level(st.session_state[widget_key])
        if chosen == "NA":
            st.info("Nessun livello attribuito: la competenza è non applicabile o non ancora valutata.")
        else:
            level_description = _safe_text(competence.get(f"Livello_{chosen}", ""))
            st.markdown(f"**Descrittore {_level_label(chosen)}**")
            if level_description:
                st.write(level_description)
            else:
                st.warning("Descrittore del livello non disponibile.")

    with tab_comp:
        definition = _safe_text(competence.get("Definizione / Razionale", ""))
        if definition:
            st.write(definition)
        else:
            st.info("Definizione della competenza non disponibile.")

    with tab_desc:
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



def _render_dimension_card(
    dimension: str,
    subset: pd.DataFrame,
    selected_row: int,
    file_key: str,
    df_work: pd.DataFrame,
) -> None:
    draft_levels: list[str] = []
    for code in subset["Codice"].astype(str):
        widget_key = f"level::{file_key}::{selected_row}::{code}"
        initial = normalize_level(df_work.at[selected_row, code])
        if widget_key not in st.session_state:
            st.session_state[widget_key] = initial
        draft_levels.append(normalize_level(st.session_state[widget_key]))

    score = _score_label(draft_levels)

    with st.container(border=True):
        st.markdown(
            f"""
            <div class="dapss-fm-family-header">
              <h4>{html.escape(str(dimension))}</h4>
              <span>{html.escape(score)}<small>/100</small></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for _, row in subset.iterrows():
            code = str(row["Codice"])
            widget_key = f"level::{file_key}::{selected_row}::{code}"
            current = normalize_level(st.session_state[widget_key])
            code_col, text_col, level_col = st.columns([0.75, 4.4, 0.95], gap="small")
            with code_col:
                st.markdown(
                    f'<div class="dapss-fm-code">{html.escape(code)}</div>',
                    unsafe_allow_html=True,
                )
            with text_col:
                st.markdown(
                    f'<div class="dapss-fm-competency">'
                    f'{html.escape(str(row["Competenza"]))}</div>',
                    unsafe_allow_html=True,
                )
            with level_col:
                if st.button(
                    _level_label(current),
                    key=f"open::{file_key}::{selected_row}::{code}",
                    use_container_width=True,
                    help="Apri livello, definizione e descrittori",
                ):
                    _set_active_competence(selected_row, code)
                    st.rerun()


def _render_dimension_grid(
    title: str,
    dimensions: list[str],
    source_df: pd.DataFrame,
    selected_row: int,
    file_key: str,
    df_work: pd.DataFrame,
) -> None:
    """Renderizza una famiglia per riga a tutta larghezza, con layout stabile."""
    if not dimensions:
        return

    st.markdown(
        f'<div class="dapss-fm-section-title">{html.escape(title)}</div>',
        unsafe_allow_html=True,
    )

    # Layout volutamente verticale e stabile: una famiglia per riga a tutta larghezza.
    # Evita differenze di altezza, colonne sfalsate e card compresse.
    for dimension in [str(d) for d in dimensions]:
        subset = source_df[source_df["Dimensione"].astype(str).eq(dimension)].copy()
        if subset.empty:
            continue
        _render_dimension_card(dimension, subset, selected_row, file_key, df_work)



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

uploaded_name = st.session_state.get("source_filename") or "Nessun file caricato"
current_count = len(st.session_state.get("df_work", pd.DataFrame())) if isinstance(st.session_state.get("df_work"), pd.DataFrame) else 0
_topbar(uploaded_name, current_count)

header_cols = st.columns([1.05, 1.2, 1.45, 2.35, 0.65])
with header_cols[4]:
    with st.popover("📦 Snapshot", use_container_width=True):
        uploaded = st.file_uploader(
            "Carica il file Excel scaricato dal Drive",
            type=["xlsx"],
            accept_multiple_files=False,
            key="snapshot_upload",
        )
        st.caption("L’app modifica una copia del file. Dopo il download dovrai ricaricarla manualmente sul Drive.")
        if uploaded is not None:
            st.success(f"File attivo: {uploaded.name}")

if uploaded is None:
    with header_cols[0]:
        st.selectbox("Professione", ["Infermieri"], disabled=True)
    with header_cols[1]:
        st.selectbox("Area", [ALL_AREAS], disabled=True)
    with header_cols[2]:
        st.selectbox("Struttura", [ALL_STRUCTURES], disabled=True)
    with header_cols[3]:
        st.selectbox("Professionista", ["Carica uno Snapshot"], disabled=True)
    if "view_widget" not in st.session_state:
        st.session_state["view_widget"] = "Professionista"
    st.segmented_control("Vista", VIEWS, key="view_widget", label_visibility="collapsed", width="stretch")
    st.info("Carica il file da modificare per attivare la schermata professionista.")
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
    st.session_state["view_widget"] = "Professionista"
    st.rerun()

df_work: pd.DataFrame = st.session_state["df_work"]

with header_cols[0]:
    st.selectbox("Professione", ["Infermieri"], disabled=True)

area_column = next((column for column in df_work.columns if _norm(column) == "area"), None)
if area_column:
    area_values = sorted(v for v in df_work[area_column].dropna().astype(str).map(str.strip).unique() if v)
    area_options = [ALL_AREAS, *area_values]
    if st.session_state.get("filter_area") not in area_options:
        st.session_state["filter_area"] = ALL_AREAS
    with header_cols[1]:
        selected_area = st.selectbox("Area", area_options, key="filter_area")
else:
    with header_cols[1]:
        selected_area = st.selectbox("Area", [ALL_AREAS], disabled=True)

filtered_people = df_work.copy()
if area_column and selected_area != ALL_AREAS:
    filtered_people = filtered_people[filtered_people[area_column].fillna("").astype(str).str.strip().eq(selected_area)]

structures = sorted(v for v in filtered_people["Struttura"].dropna().astype(str).map(str.strip).unique() if v)
structure_options = [ALL_STRUCTURES, *structures]
if st.session_state.get("filter_structure") not in structure_options:
    st.session_state["filter_structure"] = ALL_STRUCTURES
with header_cols[2]:
    selected_structure = st.selectbox("Struttura", structure_options, key="filter_structure")
if selected_structure != ALL_STRUCTURES:
    filtered_people = filtered_people[filtered_people["Struttura"].fillna("").astype(str).str.strip().eq(selected_structure)]

professional_options = list(filtered_people.index)
if not professional_options:
    st.error("Nessun professionista disponibile per i filtri selezionati.")
    st.stop()
if st.session_state.get("filter_professional") not in professional_options:
    st.session_state["filter_professional"] = professional_options[0]
with header_cols[3]:
    selected_row = st.selectbox(
        "Professionista",
        professional_options,
        key="filter_professional",
        format_func=lambda index: _person_label(df_work.loc[index]),
    )

if st.session_state.get("view_widget") not in VIEWS:
    st.session_state["view_widget"] = "Professionista"
view = st.segmented_control("Vista", VIEWS, key="view_widget", label_visibility="collapsed", width="stretch")

if view != "Professionista":
    st.info("In questa versione operativa è attiva la vista Professionista per modifica e download del file.")

selected_person = df_work.loc[selected_row]
selected_structure_text = _safe_text(selected_person.get("Struttura", ""))
selected_area_text = _safe_text(selected_person.get(area_column, "")) if area_column else ""

mapped_dimensions = governance.dimensions_for_structure(selected_structure_text)
if mapped_dimensions:
    scope_dimensions = mapped_dimensions
else:
    populated_dimensions = catalogue.loc[
        catalogue["Codice"].map(lambda code: normalize_level(df_work.at[selected_row, code]) != "NA" if code in df_work.columns else False),
        "Dimensione",
    ].astype(str).drop_duplicates().tolist()
    scope_dimensions = list(dict.fromkeys([*transversal_dimensions, *populated_dimensions]))

scope_df = catalogue[catalogue["Dimensione"].isin(scope_dimensions)].copy()
if scope_df.empty:
    scope_df = catalogue[catalogue["Dimensione"].isin(transversal_dimensions)].copy()
scope_df = scope_df.sort_values("_ordine")

selected_levels = [normalize_level(df_work.at[selected_row, code]) for code in scope_df["Codice"].astype(str) if code in df_work.columns]
assigned_count = sum(level != "NA" for level in selected_levels)
applicable_count = len(scope_df)
completezza = f"{round((assigned_count / applicable_count) * 100) if applicable_count else 0}%"
transversal_active = [dimension for dimension in transversal_dimensions if dimension in scope_dimensions]

ready_for_download = bool(st.session_state.get("has_saved")) and not bool(st.session_state.get("unsaved_changes"))

header_left, header_right = st.columns([5, 1])
with header_left:
    st.markdown("## Profilo professionista")
    st.caption("Attribute profile · livelli Benner e punteggi delle singole famiglie di competenze")
with header_right:
    if st.button("Salva modifiche", type="primary", use_container_width=True, key="save_top"):
        try:
            _save_all_drafts(file_key, all_codes)
            st.toast("Modifiche salvate. Il file è pronto per il download.", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Non è stato possibile salvare il file: {exc}")
    st.download_button(
        "Scarica file aggiornato",
        data=st.session_state.get("export_bytes") or b"",
        file_name=st.session_state["source_filename"],
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
        disabled=not ready_for_download,
        key="download_top",
    )

identity_col, cluster_col, badge_col = st.columns([1.35, .85, 1.2])
with identity_col:
    _profile_identity_card(selected_person, "Infermieri", selected_area_text)
with cluster_col:
    _cluster_card()
with badge_col:
    _badge_shelf()

m1, m2, m3 = st.columns(3)
with m1:
    _kpi_card("Completezza", completezza, f"{assigned_count}/{applicable_count} competenze")
with m2:
    _kpi_card("Dimensioni attive", str(len(scope_dimensions)), f"{len(transversal_active)} trasversali")
with m3:
    _kpi_card("Matricola", _person_id(selected_person.get("ID", "")) or "—", "Infermieri")

st.markdown(
    '<div class="dapss-insight">Ogni famiglia mostra il proprio punteggio /100. Ogni competenza è rappresentata dal mini-badge del livello Benner: N, PAV, C, A o E.</div>',
    unsafe_allow_html=True,
)

_render_competence_detail_panel(selected_row, file_key, catalogue)

transversal_df = scope_df[scope_df["Dimensione"].isin(transversal_active)].copy()
transversal_dims = transversal_df["Dimensione"].astype(str).drop_duplicates().tolist()
_render_dimension_grid("Competenze trasversali", transversal_dims, transversal_df, selected_row, file_key, df_work)

specific_dimensions = [dimension for dimension in scope_dimensions if dimension not in transversal_active]
if specific_dimensions:
    specific_df = scope_df[scope_df["Dimensione"].isin(specific_dimensions)].copy()
    specific_dims = specific_df["Dimensione"].astype(str).drop_duplicates().tolist()
    _render_dimension_grid("Competenze specifiche attive", specific_dims, specific_df, selected_row, file_key, df_work)

if st.session_state.get("unsaved_changes"):
    st.markdown('<div class="dapss-flow-note">Ci sono modifiche non salvate. Premi <strong>Salva modifiche</strong> prima di scaricare il file aggiornato.</div>', unsafe_allow_html=True)
elif st.session_state.get("has_saved"):
    st.markdown(
        f'<div class="dapss-flow-note">File pronto per il download · salvato il {html.escape(st.session_state.get("last_saved_at", ""))}</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown('<div class="dapss-flow-note">Flusso operativo: scarica dal Drive → carica qui il file → modifica → salva → scarica la copia aggiornata → ricarica manualmente sul Drive.</div>', unsafe_allow_html=True)
