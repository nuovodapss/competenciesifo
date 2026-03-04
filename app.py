from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

from utils.export import to_excel_bytes
from utils.guide import load_guide
from utils.io import detect_structure_values, normalize_competence_columns, read_department_excel
from utils.panels import load_structure_dimensions, guess_dimensions_from_structure
from utils.recode import LEVELS, recode_df_to_num, recode_series_to_num, score_percent, normalize_level
from utils.schema import coerce_base_columns, ensure_schema, load_column_order


APP_DIR = Path(__file__).parent
GUIDE_PATH = APP_DIR / "data" / "guida_competenze.xlsx"
COLUMN_ORDER_PATH = APP_DIR / "config" / "column_order.json"
STRUCTURE_DIMENSIONS_PATH = APP_DIR / "config" / "structure_dimensions.yml"
STYLE_PATH = APP_DIR / "assets" / "style.css"

# ------------------------------------------------------------
# Page config — coerente con app Direzione (APPGrade)
# ------------------------------------------------------------
st.set_page_config(
    page_title="APPGrade — Reparto",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# Style helpers (rosso→verde + bordo nero) in stile dashboard
# ------------------------------------------------------------
COLOR_SCALE = alt.Scale(domain=[0, 100], range=["#d7191c", "#1a9641"])  # rosso→verde
BAR_BORDER = {"stroke": "black", "strokeWidth": 1}

@st.cache_data(show_spinner=False)
def _load_guide():
    return load_guide(GUIDE_PATH)

@st.cache_data(show_spinner=False)
def _load_column_order():
    return load_column_order(COLUMN_ORDER_PATH)

@st.cache_data(show_spinner=False)
def _load_structure_dimensions():
    return load_structure_dimensions(STRUCTURE_DIMENSIONS_PATH)

@st.cache_data(show_spinner=False)
def _read_css():
    if STYLE_PATH.exists():
        return STYLE_PATH.read_text(encoding="utf-8")
    return ""

guide = _load_guide()
column_order = _load_column_order()
structure_dim_map = _load_structure_dimensions()

all_codes = column_order[4:]  # after ID, Nome, Cognome, Struttura

# Trasversali: sempre inclusi e sempre modificabili
trans_df = guide.df[guide.df["Pannello"].astype(str).str.strip().str.lower() == "trasversali"].copy()
TRANS_CODES = trans_df["Codice"].astype(str).tolist()
TRANS_DIMENSIONS = trans_df["Dimensione"].astype(str).unique().tolist()

# CSS
css = _read_css()
if css:
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

# Header
st.title("🩺 APPGrade — Nursing Competencies (Reparto)")
st.markdown(
    "Carica il file del tuo reparto per **monitorare** le competenze e **modificare** i livelli degli infermieri "
    "con download finale in **.xlsx** con struttura colonne **uniforme**."
)

with st.sidebar:
    st.markdown("### 1) Carica dataset di reparto")
    uploaded = st.file_uploader("File Excel (.xlsx)", type=["xlsx"], accept_multiple_files=False)

if uploaded is None:
    st.info("Carica un dataset di reparto in formato .xlsx per iniziare.")
    st.stop()

# Hash upload to re-init session (evita residui in session_state)
raw = uploaded.getvalue()
file_hash = hashlib.md5(raw).hexdigest()

if st.session_state.get("file_hash") != file_hash:
    df_in = read_department_excel(uploaded)
    df_in = coerce_base_columns(df_in)
    st.session_state["df_in_raw"] = df_in
    st.session_state["file_hash"] = file_hash
    st.session_state.pop("df_work", None)
    st.session_state.pop("selected_structure", None)
    st.session_state.pop("selected_dimensions", None)

df_in = st.session_state["df_in_raw"].copy()

# Validazione base
missing_base = [c for c in ["ID", "Nome", "Cognome", "Struttura"] if c not in df_in.columns]
if missing_base:
    st.error(
        "Il dataset caricato non contiene tutte le colonne minime richieste: "
        f"{missing_base}.\n\nColonne trovate: {list(df_in.columns)}"
    )
    st.stop()

# Determina Struttura
structures = detect_structure_values(df_in)
if len(structures) == 0:
    structure = ""
    st.warning("Colonna 'Struttura' vuota/non compilata: verranno mostrate solo le Trasversali.")
elif len(structures) == 1:
    structure = structures[0]
else:
    st.warning("Nel file ci sono più valori diversi in 'Struttura'. Scegline uno per applicare la mappa Dimensioni.")
    structure = st.selectbox("Seleziona Struttura", structures)

st.session_state["selected_structure"] = structure

# Dimensioni specifiche disponibili (tutte tranne Trasversali)
all_dims = guide.df["Dimensione"].dropna().astype(str).str.strip().unique().tolist()
spec_dims = [d for d in all_dims if d not in TRANS_DIMENSIONS]

# Default dimensioni per Struttura
default_dims = []
if structure and structure in structure_dim_map:
    default_dims = structure_dim_map.get(structure, [])
elif structure:
    default_dims = guess_dimensions_from_structure(structure, spec_dims)
else:
    default_dims = []

with st.sidebar:
    st.markdown("---")
    st.markdown("### 2) Mappa Struttura → Dimensioni")
    st.markdown(f"<div class='pill'>Struttura: {structure or '—'}</div>", unsafe_allow_html=True)

    selected_dims = st.multiselect(
        "Dimensioni specifiche (oltre alle Trasversali)",
        options=spec_dims,
        default=st.session_state.get("selected_dimensions", default_dims),
        help="Le Trasversali sono sempre incluse. Qui selezioni le Dimensioni specifiche del reparto.",
    )
    st.session_state["selected_dimensions"] = selected_dims

    if structure and structure not in structure_dim_map:
        st.info("Struttura non presente nella mappa: scegli manualmente le Dimensioni specifiche da includere.")

    st.markdown("---")
    st.caption("Download sempre uniforme: colonne non visibili impostate a NA.")

# ------------------------------------------------------------
# Inizializza df_work: schema uniforme + normalizzazione livelli
# ------------------------------------------------------------
if "df_work" not in st.session_state:
    df_work = df_in.copy()
    df_work = ensure_schema(df_work, column_order, fill_value="NA")
    df_work = normalize_competence_columns(df_work, all_codes)
    st.session_state["df_work"] = df_work
else:
    df_work = st.session_state["df_work"]

# ------------------------------------------------------------
# Scope (codici) visibili/modificabili per questa Struttura
# ------------------------------------------------------------
scope_df = guide.df[
    (guide.df["Codice"].astype(str).isin(TRANS_CODES))
    | (guide.df["Dimensione"].astype(str).isin(selected_dims))
].copy()

# Mantieni l'ordine del file guida
scope_df["Codice"] = scope_df["Codice"].astype(str)
editable_codes = scope_df["Codice"].tolist()

# ------------------------------------------------------------
# Layout: due sezioni sulla stessa pagina
# ------------------------------------------------------------
tab_mon, tab_edit = st.tabs(["📊 Monitoraggio", "🛠️ Modifica & Download"])

# ---------------- Monitoraggio ----------------
with tab_mon:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Vista di struttura — score per Dimensione (0–100)")
    st.caption("Score = media dei livelli (1–5) × 20, ignorando le voci NA (0).")

    df_num = recode_df_to_num(df_work, editable_codes)

    codes_by_dim = {}
    for dim, g in scope_df.groupby("Dimensione", sort=False):
        codes_by_dim[str(dim)] = g["Codice"].astype(str).tolist()

    rows = []
    for dim, codes in codes_by_dim.items():
        per = []
        coverage = []
        for _, r in df_num.iterrows():
            vals = r[codes]
            per.append(score_percent(vals))
            non_na = int((vals != 0).sum())
            coverage.append(float(non_na / max(len(codes), 1) * 100))
        rows.append(
            {
                "Dimensione": dim,
                "N_competenze": len(codes),
                "Score_medio_%": round(float(pd.Series(per).mean()), 1) if len(per) else 0.0,
                "Copertura_media_%": round(float(pd.Series(coverage).mean()), 1) if len(coverage) else 0.0,
            }
        )

    dim_table = pd.DataFrame(rows).sort_values("Score_medio_%", ascending=False)

    c1, c2 = st.columns([1.15, 1])
    with c1:
        st.dataframe(dim_table, use_container_width=True, hide_index=True)
    with c2:
        if not dim_table.empty:
            chart = (
                alt.Chart(dim_table)
                .mark_bar(**BAR_BORDER)
                .encode(
                    x=alt.X("Score_medio_%:Q", title="Score medio 0–100", scale=alt.Scale(domain=[0, 100])),
                    y=alt.Y("Dimensione:N", sort=dim_table["Dimensione"].tolist(), title=None),
                    color=alt.Color("Score_medio_%:Q", scale=COLOR_SCALE, legend=None),
                    tooltip=[
                        alt.Tooltip("Dimensione:N"),
                        alt.Tooltip("Score_medio_%:Q", format=".1f"),
                        alt.Tooltip("Copertura_media_%:Q", format=".1f"),
                        alt.Tooltip("N_competenze:Q"),
                    ],
                )
                .properties(height=min(520, 28 * max(6, len(dim_table))))
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Nessuna dimensione disponibile nel scope selezionato.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Vista per infermiere")
    st.caption("Totale = media dei punteggi di dimensione (0–100) nello scope selezionato.")
    overall_rows = []
    for i, r in df_num.iterrows():
        scores = [score_percent(r[codes]) for codes in codes_by_dim.values()]
        overall = float(pd.Series(scores).mean()) if len(scores) else 0.0
        overall_rows.append(
            {
                "ID": df_work.loc[i, "ID"],
                "Cognome": df_work.loc[i, "Cognome"],
                "Nome": df_work.loc[i, "Nome"],
                "Score_totale_%": round(overall, 1),
            }
        )
    nurse_table = pd.DataFrame(overall_rows).sort_values("Score_totale_%", ascending=False)
    st.dataframe(nurse_table, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Modifica ----------------
with tab_edit:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Modifica livelli per singolo infermiere")
    st.caption("Seleziona un infermiere e modifica i livelli (NA, N, Pav, C, A, E). Premi **Salva** per applicare.")
    st.markdown("</div>", unsafe_allow_html=True)

    # nurse selector
    df_id = df_work[["ID", "Cognome", "Nome"]].astype(str)
    df_id["label"] = df_id["ID"] + " — " + df_id["Cognome"] + " " + df_id["Nome"]
    labels = df_id["label"].tolist()

    if not labels:
        st.error("Nel file non risultano infermieri (righe) da modificare.")
        st.stop()

    sel_label = st.selectbox("Seleziona infermiere", options=labels)
    idx = labels.index(sel_label)

    # Editor dataframe: guida + livello corrente
    current_levels = []
    for code in editable_codes:
        current_levels.append(df_work.loc[idx, code] if code in df_work.columns else "NA")

    editor_df = scope_df.copy()
    editor_df["Livello"] = [normalize_level(x) for x in current_levels]

    # Filtri
    f1, f2 = st.columns([1, 2])
    with f1:
        dim_options = list(editor_df["Dimensione"].unique())
        dim_filter = st.multiselect(
            "Filtra Dimensione",
            options=dim_options,
            default=dim_options,
            key="dim_filter",
        )
    with f2:
        query = st.text_input("Cerca (codice o testo competenza)", value="", key="search_query")

    view_df = editor_df[editor_df["Dimensione"].isin(dim_filter)].copy()
    if query.strip():
        q = query.strip().lower()
        view_df = view_df[
            view_df["Codice"].astype(str).str.lower().str.contains(q)
            | view_df["Competenza"].astype(str).str.lower().str.contains(q)
        ].copy()

    edited = st.data_editor(
        view_df[["Dimensione", "Codice", "Competenza", "Livello"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Livello": st.column_config.SelectboxColumn(
                "Livello",
                options=LEVELS,
                required=True,
                width="small",
            )
        },
        key=f"editor_{df_work.loc[idx,'ID']}",
    )

    # Applica edits subset al dataset completo del singolo infermiere
    merged = editor_df[["Dimensione", "Codice", "Competenza", "Livello"]].copy()
    merged["Codice"] = merged["Codice"].astype(str)
    merged["Livello"] = merged["Livello"].apply(normalize_level)

    edited_subset = edited[["Codice", "Livello"]].copy()
    edited_subset["Codice"] = edited_subset["Codice"].astype(str)
    edited_subset["Livello"] = edited_subset["Livello"].apply(normalize_level)

    merged = merged.set_index("Codice")
    merged.loc[edited_subset["Codice"], "Livello"] = edited_subset.set_index("Codice")["Livello"]
    merged = merged.reset_index()

    merged["Num"] = recode_series_to_num(merged["Livello"])

    dim_scores = (
        merged.groupby("Dimensione", sort=False)["Num"]
        .apply(lambda s: round(score_percent(s), 1))
        .reset_index()
        .rename(columns={"Num": "Score_% (0–100)"})
    )

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.subheader("Score per Dimensione (live)")
        st.dataframe(dim_scores, use_container_width=True, hide_index=True)
    with c2:
        tot = round(float(dim_scores["Score_% (0–100)"].mean()) if len(dim_scores) else 0.0, 1)
        st.metric("Score totale (%)", tot)
        st.caption("Score totale = media dei punteggi di dimensione nello scope selezionato.")
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("💾 Salva modifiche per questo infermiere", type="primary"):
        for code, level in zip(merged["Codice"].astype(str), merged["Livello"].astype(str)):
            if code in df_work.columns:
                df_work.loc[idx, code] = normalize_level(level)
        st.session_state["df_work"] = df_work
        st.success("Modifiche salvate nel dataset di sessione.")

    # ---------------- Download ----------------
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Download dataset uniforme (.xlsx)")
    st.caption(
        "Nel file scaricato: ordine colonne canonico (Direzione) + "
        "colonne non visibili per questa Struttura impostate a `NA`."
    )

    export_df = df_work.copy()

    # Normalizza e forza NA fuori-scope
    editable_set = set(editable_codes)
    for c in all_codes:
        if c in export_df.columns:
            export_df[c] = export_df[c].apply(normalize_level)
            if c not in editable_set:
                export_df[c] = "NA"

    # Uniforma: solo schema canonico (base + tutte le competenze)
    export_df = export_df[column_order]

    xlsx_bytes = to_excel_bytes(export_df)
    fname = f"competenze_{(structure or 'struttura').replace(' ','_')}.xlsx"
    st.download_button(
        label="⬇️ Scarica Excel aggiornato",
        data=xlsx_bytes,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("</div>", unsafe_allow_html=True)

st.caption("Config: `config/structure_dimensions.yml` (mappa Struttura→Dimensioni) · `config/column_order.json` (ordine colonne).")
