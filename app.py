from __future__ import annotations

import hashlib
from pathlib import Path

import re
import textwrap
import numpy as np

import pandas as pd
import streamlit as st
import altair as alt
import matplotlib.pyplot as plt
import plotly.graph_objects as go

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
# Page config
# ------------------------------------------------------------
st.set_page_config(
    page_title="APPGrade — Reparto",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# Style helpers
# ------------------------------------------------------------
COLOR_SCALE = alt.Scale(domain=[0, 100], range=["#d7191c", "#1a9641"])
BAR_BORDER = {"stroke": "black", "strokeWidth": 1}
APP_GREEN = "#1B7F5A"
APP_GREEN_LIGHT = "#EAF4EE"
GRID_COLOR = "#AEB8B2"
WHITE_BG = "#FFFFFF"


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


def _wrap_pizza_label(text: str, width: int = 18) -> str:
    txt = str(text).strip()
    if not txt:
        return txt
    return "\n".join(
        textwrap.wrap(
            txt,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


def _render_radar_plot(labels: list[str], values: list[float], title: str | None = None):
    if len(labels) < 2:
        st.info("Radar non disponibile: servono almeno 2 dimensioni nello scope selezionato.")
        return

    n = len(labels)
    wrap_w = 18 if n <= 8 else 16 if n <= 10 else 14
    wrapped_labels = [_wrap_pizza_label(lbl, width=wrap_w) for lbl in labels]
    clean_values = [max(0.0, min(100.0, float(v))) if pd.notna(v) else 0.0 for v in values]

    theta = wrapped_labels + [wrapped_labels[0]]
    r = clean_values + [clean_values[0]]

    try:
        fig = go.Figure()
        fig.add_trace(
            go.Scatterpolar(
                r=r,
                theta=theta,
                mode="lines+markers",
                fill="toself",
                line=dict(color=APP_GREEN, width=3),
                marker=dict(size=7, color=APP_GREEN),
                fillcolor="rgba(27,127,90,0.28)",
                hovertemplate="%{theta}<br>Score: %{r:.1f}<extra></extra>",
                name="Profilo",
            )
        )

        fig.update_layout(
            showlegend=False,
            paper_bgcolor="white",
            plot_bgcolor="white",
            margin=dict(l=40, r=40, t=20, b=20),
            height=400 if n <= 8 else 760 if n <= 11 else 840,
            polar=dict(
                bgcolor="white",
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    tickmode="array",
                    tickvals=[20, 40, 60, 80, 100],
                    ticktext=["20", "40", "60", "80", "100"],
                    tickfont=dict(size=12, color="#222222"),
                    gridcolor="#D7DCD9",
                    gridwidth=1,
                    griddash="dot",
                    linecolor="#222222",
                    linewidth=1,
                    angle=90,
                ),
                angularaxis=dict(
                    direction="clockwise",
                    rotation=90,
                    gridcolor="#D7DCD9",
                    linecolor="#222222",
                    linewidth=1,
                    tickfont=dict(size=15 if n <= 8 else 13 if n <= 10 else 12, color="#111111"),
                ),
            ),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})
    except Exception:
        st.info("Radar temporaneamente non disponibile. Restano visibili barre e percentili qui sotto.")

guide = _load_guide()
column_order = _load_column_order()
structure_dim_map = _load_structure_dimensions()

all_codes = column_order[4:]

# Trasversali: sempre incluse e sempre modificabili
trans_df = guide.df[guide.df["Pannello"].astype(str).str.strip().str.lower() == "trasversali"].copy()
TRANS_CODES = list(dict.fromkeys(trans_df["Codice"].astype(str).tolist()))
TRANS_DIMENSIONS = trans_df["Dimensione"].astype(str).drop_duplicates().tolist()

# Codici duplicati nella guida
duplicate_code_counts = guide.df["Codice"].astype(str).value_counts()
DUPLICATE_CODES = duplicate_code_counts[duplicate_code_counts > 1].index.tolist()

css = _read_css()
if css:
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

st.title("Pannello di Competenze")
st.markdown(
    "Carica il file del tuo reparto per **monitorare** le competenze e **modificare** i livelli degli Infermieri "
    "con download finale in file excel **.xlsx**."
)

with st.sidebar:
    st.markdown("### 1) Carica file")
    uploaded = st.file_uploader("File Excel (.xlsx)", type=["xlsx"], accept_multiple_files=False)

if uploaded is None:
    st.info("Carica il file di reparto in formato .xlsx per iniziare.")
    st.stop()

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

missing_base = [c for c in ["ID", "Nome", "Cognome", "Struttura"] if c not in df_in.columns]
if missing_base:
    st.error(
        "Il dataset caricato non contiene tutte le colonne minime richieste: "
        f"{missing_base}.\n\nColonne trovate: {list(df_in.columns)}"
    )
    st.stop()

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

all_dims = guide.df["Dimensione"].dropna().astype(str).str.strip().unique().tolist()
spec_dims = [d for d in all_dims if d not in TRANS_DIMENSIONS]

mapped_dims_raw = []
default_dims = []
unavailable_mapped_dims = []
if structure and structure in structure_dim_map:
    mapped_dims_raw = structure_dim_map.get(structure, [])
    default_dims = [d for d in mapped_dims_raw if d in spec_dims]
    unavailable_mapped_dims = [d for d in mapped_dims_raw if d not in spec_dims]
elif structure:
    default_dims = guess_dimensions_from_structure(structure, spec_dims)
else:
    default_dims = []

with st.sidebar:
    st.markdown("---")
    st.markdown("### 2) Dimensioni di competenza")
    st.markdown(f"<div class='pill'>Struttura: {structure or '—'}</div>", unsafe_allow_html=True)

    selected_dims = st.multiselect(
        "Competenze Specifiche",
        options=spec_dims,
        default=st.session_state.get("selected_dimensions", default_dims),
        help="Le Trasversali sono sempre incluse. Qui selezioni le Dimensioni specifiche del reparto.",
    )
    st.session_state["selected_dimensions"] = selected_dims

    if structure and structure not in structure_dim_map:
        st.info("Struttura non presente nella mappa: scegli manualmente le Dimensioni specifiche da includere.")
    elif unavailable_mapped_dims:
        st.info(
            "Alcune dimensioni presenti nella mappa della struttura non sono disponibili nella guida competenze aggiornata: "
            + ", ".join(unavailable_mapped_dims)
        )

    st.markdown("---")
    st.caption("")

if DUPLICATE_CODES:
    st.warning(
        "Nel file guida ci sono codici duplicati "
        f"({', '.join(DUPLICATE_CODES)}). Nell'app restano associati a una sola colonna Excel per codice."
    )

if "df_work" not in st.session_state:
    df_work = df_in.copy()
    df_work = ensure_schema(df_work, column_order, fill_value="NA")
    df_work = normalize_competence_columns(df_work, all_codes)
    st.session_state["df_work"] = df_work
else:
    df_work = st.session_state["df_work"]

scope_df = guide.df[
    (guide.df["Codice"].astype(str).isin(TRANS_CODES))
    | (guide.df["Dimensione"].astype(str).isin(selected_dims))
].copy()

scope_df["Codice"] = scope_df["Codice"].astype(str)
editable_codes = scope_df["Codice"].tolist()

tab_mon, tab_edit = st.tabs(["Monitoraggio", "Modifica & Download"])

# ---------------- Monitoraggio ----------------
with tab_mon:
    df_num = recode_df_to_num(df_work, editable_codes)

    codes_by_dim: dict[str, list[str]] = {}
    for dim, g in scope_df.groupby("Dimensione", sort=False):
        codes_by_dim[str(dim)] = g["Codice"].astype(str).tolist()

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Livelli medi di Competenza del reparto")
    st.caption("Grafico a barre dei livelli medi per dimensioni di competenze trasversali e specifiche.")

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

    if dim_table.empty:
        st.info("Nessuna dimensione disponibile nel scope selezionato.")
    else:
        chart = (
            alt.Chart(dim_table)
            .mark_bar(**BAR_BORDER)
            .encode(
                y=alt.Y("Dimensione:N", sort=dim_table["Dimensione"].tolist(), title=None),
                x=alt.X("Score_medio_%:Q", title="Score medio 0–100", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("Score_medio_%:Q", scale=COLOR_SCALE, legend=None),
                tooltip=[
                    alt.Tooltip("Dimensione:N"),
                    alt.Tooltip("Score_medio_%:Q", format=".1f"),
                    alt.Tooltip("Copertura_media_%:Q", format=".1f"),
                    alt.Tooltip("N_competenze:Q"),
                ],
            )
            .properties(height=min(720, 28 * max(8, len(dim_table))))
        )
        st.altair_chart(chart, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Profilo Infermiere")
    st.caption("Profilo del singolo Infermiere selezionato.")

    df_id = df_work[["ID", "Nome", "Cognome", "Struttura"]].copy().astype(str)
    df_id["label"] = (
        df_id["Cognome"]
        + " "
        + df_id["Nome"]
        + " ("
        + df_id["Struttura"]
        + ", ID:"
        + df_id["ID"]
        + ")"
    )

    if df_id.empty:
        st.warning("Nessun infermiere presente nel file.")
        st.stop()

    target_label = st.selectbox("Seleziona infermiere", sorted(df_id["label"].tolist()), key="scout_target")
    target_id = df_id.loc[df_id["label"] == target_label, "ID"].iloc[0]
    target_id_str = str(target_id)

    scope_mode = st.radio(
        "Competenze in visualizzazione",
        ["Competenze Trasversali", "Competenze Specifiche", "Competenze Trasversali e Specifiche"],
        horizontal=True,
        help="Influenza Radar, barre, percentili e dettaglio competenze.",
        key="scout_scope_mode",
    )

    if scope_mode == "Competenze Trasversali":
        scout_scope_df = guide.df[guide.df["Codice"].astype(str).isin(TRANS_CODES)].copy()
    elif scope_mode == "Competenze Specifiche":
        scout_scope_df = guide.df[
            (~guide.df["Codice"].astype(str).isin(TRANS_CODES))
            & (guide.df["Dimensione"].astype(str).isin(selected_dims))
        ].copy()
    else:
        scout_scope_df = scope_df.copy()

    scout_scope_df["Codice"] = scout_scope_df["Codice"].astype(str)

    codes_by_dim = {}
    for dim, g in scout_scope_df.groupby("Dimensione", sort=False):
        codes_by_dim[str(dim)] = g["Codice"].astype(str).tolist()

    dims_all = list(codes_by_dim.keys())

    df_dims = df_work[["ID", "Nome", "Cognome", "Struttura"]].copy().astype(str)
    for dim, codes in codes_by_dim.items():
        df_dims[dim] = df_num[codes].apply(score_percent, axis=1)

    row_dims = df_dims[df_dims["ID"].astype(str) == target_id_str].iloc[0]

    st.markdown("### Profilo")
    c1, c2, c3 = st.columns([2, 2, 2])

    with c1:
        st.markdown("**Anagrafica**")
        st.write(f"- **ID**: {row_dims['ID']}")
        st.write(f"- **Nome**: {row_dims['Nome']}")
        st.write(f"- **Cognome**: {row_dims['Cognome']}")
        st.write(f"- **Struttura**: {row_dims['Struttura']}")

    with c2:
        st.markdown("**Sintesi dimensioni (0–100)**")
        vals = [float(row_dims[d]) for d in dims_all] if dims_all else []
        mean_v = float(np.mean(vals)) if vals else np.nan
        min_v = float(np.min(vals)) if vals else np.nan
        max_v = float(np.max(vals)) if vals else np.nan
        st.metric("Media", f"{mean_v:.1f}" if np.isfinite(mean_v) else "—")
        st.metric("Min", f"{min_v:.1f}" if np.isfinite(min_v) else "—")
        st.metric("Max", f"{max_v:.1f}" if np.isfinite(max_v) else "—")

    st.markdown("### Radar")
    if dims_all:
        pizza_values = [float(row_dims[d]) for d in dims_all]
        _render_radar_plot(dims_all, pizza_values, f"{scope_mode} — profilo dimensionale")
    else:
        st.info("Radar non disponibile: nessuna dimensione nello scope selezionato.")

    st.markdown("---")

    st.markdown("## Livelli di Competenza")
    if dims_all:
        dps_df = pd.DataFrame({"Dimensione": dims_all, "Score": [float(row_dims[d]) for d in dims_all]})
        dps_chart = (
            alt.Chart(dps_df)
            .mark_bar(**BAR_BORDER)
            .encode(
                y=alt.Y("Dimensione:N", sort=dims_all, title=None),
                x=alt.X("Score:Q", title="Score 0–100", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("Score:Q", scale=COLOR_SCALE, legend=None),
                tooltip=[alt.Tooltip("Dimensione:N"), alt.Tooltip("Score:Q", format=".1f")],
            )
            .properties(height=min(720, 28 * max(8, len(dps_df))))
        )
        st.altair_chart(dps_chart, use_container_width=True)
    else:
        st.info("Nessuna dimensione da visualizzare per lo scope selezionato.")

    st.markdown("---")

    st.markdown("## Posizione rispetto ai percentili del reparto")
    rows_pct = []
    for dim in dims_all:
        global_scores = df_dims[dim].dropna().values
        val = float(row_dims[dim])
        if len(global_scores) > 0:
            pct = (float(np.sum(global_scores <= val)) / float(len(global_scores))) * 100.0
        else:
            pct = np.nan
        rows_pct.append({"Dimensione": dim, "Percentile globale": pct})

    pct_df = pd.DataFrame(rows_pct)

    if not pct_df.empty:
        pct_chart = (
            alt.Chart(pct_df)
            .mark_bar(**BAR_BORDER)
            .encode(
                y=alt.Y("Dimensione:N", sort=dims_all, title=None),
                x=alt.X("Percentile globale:Q", title="Percentile globale (%)", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("Percentile globale:Q", scale=COLOR_SCALE, legend=None),
                tooltip=[alt.Tooltip("Dimensione:N"), alt.Tooltip("Percentile globale:Q", format=".1f")],
            )
            .properties(height=min(720, 28 * max(8, len(pct_df))))
        )
        st.altair_chart(pct_chart, use_container_width=True)
    else:
        st.info("Impossibile calcolare i percentili globali.")

    st.markdown("---")

    st.markdown("## Competenze dettagliate del profilo")
    _scope = scout_scope_df.copy()
    _scope["Codice"] = _scope["Codice"].astype(str)

    code_to_label = dict(zip(_scope["Codice"], _scope["Competenza"].astype(str)))
    code_to_dim = dict(zip(_scope["Codice"], _scope["Dimensione"].astype(str)))
    dim_pos = {d: i for i, d in enumerate(dims_all)}

    def _code_sort_key(code: str):
        d = code_to_dim.get(code, "")
        dpos = dim_pos.get(d, 999)
        m = re.search(r"(\D+)(\d+)$", str(code))
        if m:
            root = m.group(1)
            n_code = int(m.group(2))
        else:
            root = re.sub(r"\d+$", "", str(code))
            n_code = 9999
        return (dpos, root, n_code, str(code))

    sorted_codes = sorted(_scope["Codice"].astype(str).tolist(), key=_code_sort_key)

    _target_idx = df_work.index[df_work["ID"].astype(str) == target_id_str].tolist()
    if not _target_idx:
        st.warning("Infermiere non trovato nel dataset.")
        st.stop()
    target_idx = _target_idx[0]

    rows_comp = []
    for code in sorted_codes:
        level = normalize_level(df_work.loc[target_idx, code]) if code in df_work.columns else "NA"
        rows_comp.append(
            {
                "Dimensione": code_to_dim.get(code, ""),
                "Competenza": code_to_label.get(code, code),
                "Livello": level,
            }
        )

    comp_df = pd.DataFrame(rows_comp)

    st.markdown("### Visione d'insieme")
    dim_rows = []
    for dim, codes in codes_by_dim.items():
        vals = df_num.loc[target_idx, codes]
        coverage = float((vals != 0).sum() / max(len(codes), 1) * 100)
        score = float(row_dims[dim]) if dim in row_dims else 0.0

        global_scores = df_dims[dim].dropna().astype(float).values if dim in df_dims.columns else np.array([])
        if len(global_scores) > 0:
            pct = (float(np.sum(global_scores <= score)) / float(len(global_scores))) * 100.0
        else:
            pct = np.nan

        dim_rows.append(
            {
                "Dimensione": dim,
                "Score": round(score, 1),
                "Copertura_%": round(coverage, 1),
                "Percentile_globale": round(float(pct), 1) if np.isfinite(pct) else np.nan,
                "N_competenze": int(len(codes)),
            }
        )

    dim_over = pd.DataFrame(dim_rows)

    if dim_over.empty:
        st.info("Nessuna competenza disponibile nel profilo per lo scope selezionato.")
    else:
        over_chart = (
            alt.Chart(dim_over)
            .mark_bar(**BAR_BORDER)
            .encode(
                y=alt.Y("Dimensione:N", sort=dims_all, title=None),
                x=alt.X("Score:Q", title="Score 0–100", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("Score:Q", scale=COLOR_SCALE, legend=None),
                tooltip=[
                    alt.Tooltip("Dimensione:N"),
                    alt.Tooltip("Score:Q", format=".1f"),
                    alt.Tooltip("Copertura_%:Q", format=".1f"),
                    alt.Tooltip("Percentile_globale:Q", format=".1f"),
                    alt.Tooltip("N_competenze:Q"),
                ],
            )
            .properties(height=min(720, 28 * max(8, len(dim_over))))
        )
        st.altair_chart(over_chart, use_container_width=True)

        show_dim_table = st.toggle("Mostra tabella riepilogo (dimensioni)", value=False, key="scout_show_dim_table")
        if show_dim_table:
            st.dataframe(
                dim_over[["Dimensione", "Score", "Copertura_%", "Percentile_globale", "N_competenze"]],
                hide_index=True,
                use_container_width=True,
            )

    st.markdown("### Singole competenze (per dimensione)")
    q = st.text_input("Cerca competenza", value="", key="scout_search_comp")
    view_comp = comp_df.copy()
    if q.strip():
        qq = q.strip().lower()
        view_comp = view_comp[view_comp["Competenza"].astype(str).str.lower().str.contains(qq)].copy()

    if view_comp.empty:
        st.info("Nessuna competenza trovata con il filtro.")
    else:
        _metrics = {}
        if not dim_over.empty:
            for _, r in dim_over.iterrows():
                _metrics[str(r["Dimensione"])] = r

        for dim in dims_all:
            sub = view_comp[view_comp["Dimensione"] == dim][["Competenza", "Livello"]].copy()
            if sub.empty:
                continue

            r = _metrics.get(dim, None)
            if r is not None and pd.notna(r.get("Score", np.nan)):
                title = f"{dim} — {float(r['Score']):.1f}/100 · Copertura {float(r['Copertura_%']):.0f}%"
            else:
                title = dim

            with st.expander(title, expanded=False):
                st.dataframe(sub, hide_index=True, use_container_width=True)

        show_list = st.toggle(
            "Mostra lista completa (tutte le competenze filtrate)",
            value=False,
            key="scout_show_full_list",
        )
        if show_list:
            st.dataframe(
                view_comp[["Dimensione", "Competenza", "Livello"]],
                hide_index=True,
                use_container_width=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Modifica ----------------
with tab_edit:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Modifica livelli per singolo infermiere")
    st.caption("Seleziona un infermiere e modifica i livelli (NA, N, Pav, C, A, E). Premi **Salva** per applicare.")
    st.markdown("</div>", unsafe_allow_html=True)

    df_id = df_work[["ID", "Cognome", "Nome"]].astype(str)
    df_id["label"] = df_id["ID"] + " — " + df_id["Cognome"] + " " + df_id["Nome"]
    labels = df_id["label"].tolist()

    if not labels:
        st.error("Nel file non risultano infermieri (righe) da modificare.")
        st.stop()

    sel_label = st.selectbox("Seleziona infermiere", options=labels)
    idx = labels.index(sel_label)

    current_levels = []
    for code in editable_codes:
        current_levels.append(df_work.loc[idx, code] if code in df_work.columns else "NA")

    editor_df = scope_df.copy()
    editor_df["Livello"] = [normalize_level(x) for x in current_levels]

    f1, f2 = st.columns([1, 2])
    with f1:
        dim_options = list(editor_df["Dimensione"].unique())
        dim_filter = st.multiselect("Filtra Dimensione", options=dim_options, default=dim_options, key="dim_filter")
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
        key=f"editor_{df_work.loc[idx, 'ID']}",
    )

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

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Download dataset uniforme (.xlsx)")
    st.caption(
        "Nel file scaricato: ordine colonne canonico (Direzione) + "
        "colonne non visibili per questa Struttura impostate a `NA`."
    )

    export_df = df_work.copy()
    editable_set = set(editable_codes)
    for c in all_codes:
        if c in export_df.columns:
            export_df[c] = export_df[c].apply(normalize_level)
            if c not in editable_set:
                export_df[c] = "NA"

    export_df = export_df[column_order]

    xlsx_bytes = to_excel_bytes(export_df)
    fname = f"competenze_{(structure or 'struttura').replace(' ', '_')}.xlsx"
    st.download_button(
        label="⬇️ Scarica Excel aggiornato",
        data=xlsx_bytes,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("</div>", unsafe_allow_html=True)

st.caption("Config: `config/structure_dimensions.yml` (mappa Struttura→Dimensioni) · `config/column_order.json` (ordine colonne).")
