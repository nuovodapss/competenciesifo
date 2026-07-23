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
    identifier = _person_id(row.get("ID", ""))
    suffix = " · ".join(part for part in [structure, f"ID {identifier}" if identifier else ""] if part)
    return f"{_full_name(row)} · {suffix}" if suffix else _full_name(row)


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


def _topbar_html(file_name: str | None = None) -> str:
    label = file_name or "Nessun file caricato"
    return f"""
    <div class="dapss-topbar">
      <div>
        <div class="dapss-eyebrow">Direzione delle Professioni Sanitarie</div>
        <div class="dapss-title">COMPETENZE DAPSS</div>
        <div class="dapss-subtitle">Cockpit coordinatori · modifica e download del file di valutazione</div>
      </div>
      <div class="dapss-status">
        <strong>{html.escape(label)}</strong><br>
        <span class="dapss-subtitle">carica il file scaricato dal Drive, modifica, salva e poi scarica la copia aggiornata</span>
      </div>
    </div>
    """


def _profile_identity_html(person: pd.Series, profession_label: str, area_value: str) -> str:
    return f"""
    <div class="dapss-profile-identity">
      <div class="dapss-profile-kicker">PROFILO PROFESSIONALE</div>
      <div class="dapss-profile-name">{html.escape(_full_name(person))}</div>
      <div class="dapss-profile-id">MATRICOLA {html.escape(_person_id(person.get('ID', '')) or '—')}</div>
      <div class="dapss-profile-meta">{html.escape(profession_label)}</div>
      <div class="dapss-profile-meta">{html.escape(_safe_text(person.get('Struttura', '')))}</div>
      <div class="dapss-profile-meta">{html.escape(area_value or '—')}</div>
    </div>
    """


def _cluster_card_html() -> str:
    return """
    <div class="dapss-role-card">
      <div class="dapss-kpi-label">CLUSTER DI APPARTENENZA</div>
      <div class="dapss-role-name">—</div>
      <div class="dapss-role-stars">☆ ☆ ☆ ☆ ☆</div>
      <div class="dapss-role-note">Aderenza al cluster —</div>
      <div class="dapss-role-disclaimer">Le stelle indicano coerenza con il profilo del cluster.</div>
    </div>
    """


def _badge_shelf_html() -> str:
    return """
    <div class="dapss-badge-shelf">
      <div class="dapss-kpi-label">BADGE</div>
      <div class="dapss-badge-list"><span class="dapss-badge-empty">Nessun badge attivo</span></div>
      <div class="dapss-kpi-note">Spazio predisposto per badge e credential</div>
    </div>
    """


def _kpi_card_html(label: str, value: str, note: str = "") -> str:
    return f"""
    <div class="dapss-kpi">
      <div class="dapss-kpi-label">{html.escape(label)}</div>
      <div class="dapss-kpi-value">{html.escape(value)}</div>
      <div class="dapss-kpi-note">{html.escape(note)}</div>
    </div>
    """


def _score_label(levels: list[str]) -> str:
    numeric = recode_series_to_num(pd.Series(levels))
    valid = numeric.dropna()
    if valid.empty:
        return "—"
    return str(int(round(score_percent(numeric))))


def _render_popover_for_competence(
    competence: pd.Series,
    widget_key: str,
    current_level: str,
) -> None:
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
                st.info("Nessun livello attribuito: la competenza è non applicabile o non ancora valutata.")
            else:
                level_description = _safe_text(competence.get(f"Livello_{selected_level}", ""))
                st.markdown(f"**Descrittore {_level_label(selected_level)}**")
                if level_description:
                    st.write(level_description)
                else:
                    st.warning("Descrittore del livello non disponibile.")

        with competence_tab:
            definition = _safe_text(competence.get("Definizione / Razionale", ""))
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


def _render_dimension_section(
    title: str,
    dimensions: list[str],
    displayed_df: pd.DataFrame,
    selected_row: int,
    file_key: str,
    df_work: pd.DataFrame,
) -> None:
    if not dimensions:
        return

    st.markdown(f'<div class="dapss-fm-section-title">{html.escape(title)}</div>', unsafe_allow_html=True)
    columns = st.columns(3, gap="large")

    for position, dimension in enumerate(dimensions):
        dimension_df = displayed_df[displayed_df["Dimensione"].astype(str).eq(dimension)].copy()
        if dimension_df.empty:
            continue

        draft_levels: list[str] = []
        for code in dimension_df["Codice"].astype(str):
            widget_key = f"level::{file_key}::{selected_row}::{code}"
            initial_level = normalize_level(df_work.at[selected_row, code])
            if widget_key not in st.session_state:
                st.session_state[widget_key] = initial_level
            draft_levels.append(normalize_level(st.session_state[widget_key]))

        score_label = _score_label(draft_levels)

        with columns[position % 3]:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div class="dapss-fm-family-header">
                      <h4>{html.escape(dimension)}</h4>
                      <span>{html.escape(score_label)}<small>/100</small></span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                for _, competence in dimension_df.iterrows():
                    code = str(competence["Codice"])
                    widget_key = f"level::{file_key}::{selected_row}::{code}"
                    current_level = normalize_level(st.session_state[widget_key])
                    row_cols = st.columns([0.85, 4.6, 1.15], gap="small")
                    with row_cols[0]:
                        st.markdown(
                            f'<div class="dapss-fm-code">{html.escape(code)}</div>',
                            unsafe_allow_html=True,
                        )
                    with row_cols[1]:
                        st.markdown(
                            f'<div class="dapss-fm-competency">{html.escape(str(competence["Competenza"]))}</div>',
                            unsafe_allow_html=True,
                        )
                    with row_cols[2]:
                        _render_popover_for_competence(competence, widget_key, current_level)


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

st.markdown(_topbar_html(st.session_state.get("source_filename")), unsafe_allow_html=True)

header_columns = st.columns([1.05, 1.2, 1.45, 2.35, 0.75], gap="large")
uploaded = None

with header_columns[4]:
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

    st.markdown(
        """
        <div class="dapss-static-views">
          <div class="dapss-static-view-item">Panoramica</div>
          <div class="dapss-static-view-item">Rosa reparto</div>
          <div class="dapss-static-view-item active">Professionista</div>
          <div class="dapss-static-view-item">Similarità</div>
          <div class="dapss-static-view-item">Cluster</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="dapss-download-card" style="max-width:740px; margin:2rem auto 0; text-align:center;">
          <div class="dapss-download-title">FILE DA MODIFICARE</div>
          <div class="dapss-download-name">Carica il file scaricato dal Drive</div>
          <div class="dapss-download-copy">
            Apri <strong>Snapshot</strong>, seleziona l’Excel da aggiornare e poi scegli il professionista.
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
    st.session_state["view_widget"] = "Professionista"
    st.rerun()


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

with header_columns[4]:
    with st.popover("📦 Snapshot", use_container_width=True):
        uploaded_repeat = st.file_uploader(
            "Sostituisci il file Excel",
            type=["xlsx"],
            accept_multiple_files=False,
            key="snapshot_upload_repeat",
        )
        st.caption("Carica un altro file per ricominciare la modifica da capo.")
        if uploaded_repeat is not None:
            st.info('Per usare un nuovo file, ricarica la pagina e caricalo dallo Snapshot principale.')

st.markdown(
    """
    <div class="dapss-static-views">
      <div class="dapss-static-view-item">Panoramica</div>
      <div class="dapss-static-view-item">Rosa reparto</div>
      <div class="dapss-static-view-item active">Professionista</div>
      <div class="dapss-static-view-item">Similarità</div>
      <div class="dapss-static-view-item">Cluster</div>
    </div>
    """,
    unsafe_allow_html=True,
)

selected_person = df_work.loc[selected_row]
selected_person_name = _full_name(selected_person)
selected_person_structure = _safe_text(selected_person.get("Struttura", ""))
selected_person_area = _safe_text(selected_person.get(area_column, "")) if area_column else ""

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

selected_levels = [normalize_level(df_work.at[selected_row, code]) for code in scope_df["Codice"].astype(str) if code in df_work.columns]
assigned_count = sum(level != "NA" for level in selected_levels)
applicable_count = len(scope_df)
completeness_value = f"{round((assigned_count / applicable_count) * 100) if applicable_count else 0}%"
transversal_active = [dimension for dimension in transversal_dimensions if dimension in scope_dimensions]
ready_for_download = bool(st.session_state.get("has_saved")) and not bool(st.session_state.get("unsaved_changes"))

page_title_col, page_action_col = st.columns([5, 1.8], gap="large")
with page_title_col:
    st.markdown('<div class="dapss-page-title">Profilo professionista</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dapss-page-subtitle">Attribute profile · livelli Benner e punteggi delle singole famiglie di competenze</div>',
        unsafe_allow_html=True,
    )
with page_action_col:
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
    st.markdown(_profile_identity_html(selected_person, "Infermieri", selected_person_area), unsafe_allow_html=True)
with cluster_col:
    st.markdown(_cluster_card_html(), unsafe_allow_html=True)
with badge_col:
    st.markdown(_badge_shelf_html(), unsafe_allow_html=True)

m1, m2, m3 = st.columns(3)
with m1:
    st.markdown(
        _kpi_card_html("Completezza", completeness_value, f"{assigned_count}/{applicable_count} competenze"),
        unsafe_allow_html=True,
    )
with m2:
    st.markdown(
        _kpi_card_html("Dimensioni attive", str(len(scope_dimensions)), f"{len(transversal_active)} trasversali"),
        unsafe_allow_html=True,
    )
with m3:
    st.markdown(
        _kpi_card_html("Matricola", _person_id(selected_person.get("ID", "")) or "—", "Infermieri"),
        unsafe_allow_html=True,
    )

status_bits: list[str] = []
if st.session_state.get("unsaved_changes"):
    status_bits.append('<span class="dapss-pill dapss-warning-pill">Modifiche da salvare</span>')
elif st.session_state.get("has_saved"):
    status_bits.append('<span class="dapss-pill">Modifiche salvate</span>')
else:
    status_bits.append('<span class="dapss-pill dapss-neutral-pill">Nessuna modifica</span>')
if st.session_state.get("last_saved_at"):
    status_bits.append(f'<span class="dapss-pill dapss-neutral-pill">Salvato il {html.escape(st.session_state["last_saved_at"])}</span>')

st.markdown(
    '<div class="dapss-status-row">' + ''.join(status_bits) + '</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="dapss-insight">Clicca il livello sulla destra di ogni competenza per aprire il pannello di modifica con livello Benner, definizione e descrittori della mappa.</div>',
    unsafe_allow_html=True,
)

transversal_df = scope_df[scope_df["Dimensione"].isin(transversal_active)].copy()
transversal_displayed = transversal_df.copy()
transversal_dims = transversal_displayed["Dimensione"].astype(str).drop_duplicates().tolist()
_render_dimension_section(
    "Competenze trasversali",
    transversal_dims,
    transversal_displayed,
    selected_row,
    file_key,
    df_work,
)

specific_dimensions = [dimension for dimension in scope_dimensions if dimension not in transversal_active]
if specific_dimensions:
    specific_df = scope_df[scope_df["Dimensione"].isin(specific_dimensions)].copy()
    specific_dims = specific_df["Dimensione"].astype(str).drop_duplicates().tolist()
    _render_dimension_section(
        "Competenze specifiche attive",
        specific_dims,
        specific_df,
        selected_row,
        file_key,
        df_work,
    )

bottom_info_col, bottom_action_col = st.columns([4.2, 1.8], gap="large")
with bottom_info_col:
    st.markdown(
        f"""
        <div class="dapss-download-card">
          <div class="dapss-download-title">FILE PRONTO</div>
          <div class="dapss-download-name">{html.escape(st.session_state['source_filename'])}</div>
          <div class="dapss-download-copy">
            Premi <strong>Salva modifiche</strong> prima del download. Il file scaricato dovrà poi essere ricaricato manualmente nella stessa cartella del Drive.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with bottom_action_col:
    if st.button("Salva modifiche", type="primary", use_container_width=True, key="save_bottom"):
        try:
            _save_all_drafts(file_key, all_codes)
            st.toast("Modifiche salvate. Ora puoi scaricare il file aggiornato.", icon="✅")
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
        key="download_bottom",
    )
    if st.session_state.get("unsaved_changes"):
        st.caption("Ci sono modifiche non salvate.")
    elif not st.session_state.get("has_saved"):
        st.caption("Salva prima di scaricare.")
    else:
        st.caption(f"Pronto per il download · {st.session_state.get('last_saved_at')}")

st.markdown(
    '<div class="dapss-footer-note">Flusso operativo: scarica dal Drive → carica qui il file → modifica → salva → scarica la copia aggiornata → ricarica manualmente sul Drive.</div>',
    unsafe_allow_html=True,
)
