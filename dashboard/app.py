"""
Decarbonization Tracker dashboard.

Reads straight from the warehouse (marts.mart_decarbonization_trend plus a
fuel-mix cut of staging.stg_eia_generators) and renders the headline finding:
is clean-energy capacity growth actually translating into falling measured
emissions, state by state?

Run with: streamlit run dashboard/app.py
"""
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

st.set_page_config(
    page_title="Energy Decarbonization Tracker",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Palette — validated dark-mode categorical set (scripts/validate_palette.js,
# all checks pass) plus the chart chrome tokens it's meant to sit on.
# ---------------------------------------------------------------------------
INK_PRIMARY = "#ffffff"
INK_SECONDARY = "#c3c2b7"
INK_MUTED = "#898781"
SURFACE = "#1a1a19"
PAGE = "#0d0d0d"
BORDER = "rgba(255,255,255,0.10)"
GRIDLINE = "#2c2c2a"
GOOD = "#0ca30c"
BAD = "#e66767"

CATEGORICAL = ["#3987e5", "#008300", "#d55181", "#c98500", "#199e70", "#d95926", "#9085e9", "#e66767"]
DIVERGING_SCALE = [[0.0, "#184f95"], [0.5, "#5a5a56"], [1.0, "#e66767"]]

FUEL_COLORS = {
    "Hydro": "#3987e5",
    "Nuclear": "#9085e9",
    "Wind": "#199e70",
    "Solar": "#c98500",
    "Natural Gas": "#d95926",
    "Coal": "#e66767",
}

CHART_FONT = dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK_SECONDARY)


def style_fig(fig, height=440):
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=CHART_FONT,
        title_font=dict(color=INK_PRIMARY, size=15),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK_SECONDARY)),
        margin=dict(l=70, r=30, t=30, b=60),
        height=height,
    )
    fig.update_xaxes(gridcolor=GRIDLINE, zerolinecolor=GRIDLINE, linecolor=GRIDLINE, color=INK_MUTED)
    fig.update_yaxes(gridcolor=GRIDLINE, zerolinecolor=GRIDLINE, linecolor=GRIDLINE, color=INK_MUTED)
    return fig


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def get_engine():
    """
    Local dev reads Postgres creds from .env (POSTGRES_*). Deployed on
    Streamlit Community Cloud, there's no .env — instead paste a single
    DATABASE_URL into the app's Secrets (Settings > Secrets), e.g. the
    connection string Neon/Supabase gives you (already includes
    sslmode=require). DATABASE_URL wins if both are present.
    """
    try:
        database_url = st.secrets.get("DATABASE_URL")
    except Exception:
        database_url = None  # no secrets.toml locally — that's expected in dev
    database_url = database_url or os.getenv("DATABASE_URL")
    if database_url:
        return create_engine(database_url)

    url = (
        f"postgresql://{os.getenv('POSTGRES_USER', 'lakehouse')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'lakehouse123')}"
        f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'energy_lakehouse')}"
    )
    return create_engine(url)


@st.cache_data(ttl=300)
def load_trend():
    engine = get_engine()
    return pd.read_sql(
        "select * from marts.mart_decarbonization_trend order by state_code, year",
        engine,
    )


@st.cache_data(ttl=300)
def load_fuel_mix():
    engine = get_engine()
    query = """
        select
            case energy_source_code
                when 'SUN' then 'Solar' when 'WND' then 'Wind' when 'WAT' then 'Hydro'
                when 'NG' then 'Natural Gas' when 'NUC' then 'Nuclear' when 'COL' then 'Coal'
                else 'Other'
            end as fuel,
            period_year as year,
            sum(nameplate_capacity_mw) as capacity_mw
        from staging.stg_eia_generators
        group by 1, 2
        order by 2, 1
    """
    return pd.read_sql(query, engine)


@st.cache_data(ttl=300)
def load_archetypes():
    engine = get_engine()
    return pd.read_sql("select * from analytics.ml_state_archetypes", engine)


@st.cache_data(ttl=300)
def load_feature_importance():
    engine = get_engine()
    return pd.read_sql(
        "select * from analytics.ml_facility_emissions_feature_importance order by importance desc",
        engine,
    )


@st.cache_data(ttl=300)
def load_anomalies():
    engine = get_engine()
    return pd.read_sql(
        "select * from analytics.ml_facility_emissions_anomalies",
        engine,
    )


def build_period_summary(df: pd.DataFrame) -> pd.DataFrame:
    """First-year vs. last-year capacity growth and emissions change per state."""
    first_year, last_year = df["year"].min(), df["year"].max()
    rows = []
    for state, g in df.groupby("state_code"):
        g = g.sort_values("year")
        if g["year"].min() != first_year or g["year"].max() != last_year:
            continue
        first, last = g.iloc[0], g.iloc[-1]
        if not first["clean_capacity_mw"] or not first["total_ghg_emissions_metric_tons"]:
            continue
        capacity_growth = (last["clean_capacity_mw"] - first["clean_capacity_mw"]) / first["clean_capacity_mw"]
        emissions_change = (
            (last["total_ghg_emissions_metric_tons"] - first["total_ghg_emissions_metric_tons"])
            / first["total_ghg_emissions_metric_tons"]
        )
        rows.append({
            "state_code": state,
            "clean_capacity_growth_pct": capacity_growth,
            "emissions_change_pct": emissions_change,
            # Positive = capacity grew faster than emissions fell (or emissions rose).
            "divergence_gap": capacity_growth + emissions_change,
            "clean_mw_added": last["clean_capacity_mw"] - first["clean_capacity_mw"],
            "total_capacity_mw_latest": last["total_capacity_mw"],
        })
    return pd.DataFrame(rows)


def stat_tile(label, value, delta=None, delta_good=True, sublabel=None):
    delta_html = ""
    if delta:
        arrow = "▲" if delta.startswith("+") else ("▼" if delta.startswith("-") else "")
        is_up = delta.startswith("+")
        good = is_up if delta_good else (not is_up)
        color = GOOD if good else BAD
        delta_html = f'<div style="color:{color};font-size:13px;font-weight:600;margin-top:4px;">{arrow} {delta.lstrip("+-")}</div>'
    sub_html = f'<div style="color:{INK_MUTED};font-size:11px;margin-top:6px;">{sublabel}</div>' if sublabel else ""
    # Deliberately a single line (no embedded newlines/indentation) — Streamlit's
    # markdown renderer treats indented multi-line HTML as a code block.
    return (
        f'<div style="background:{SURFACE};border:1px solid {BORDER};border-radius:12px;'
        f'padding:18px 20px;height:118px;display:flex;flex-direction:column;justify-content:space-between;">'
        f'<div style="color:{INK_SECONDARY};font-size:12.5px;font-weight:500;letter-spacing:.02em;">{label}</div>'
        f'<div><div style="color:{INK_PRIMARY};font-size:28px;font-weight:600;line-height:1.1;">{value}</div>{delta_html}</div>'
        f'{sub_html}</div>'
    )


# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
    .stApp {{ background-color: {PAGE}; }}
    section[data-testid="stSidebar"] {{ background-color: {SURFACE}; border-right: 1px solid {BORDER}; }}
    div[data-testid="stExpander"] {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
    .block-container {{ padding-top: 2rem; max-width: 1200px; }}
    h1, h2, h3 {{ color: {INK_PRIMARY} !important; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{ background-color: {SURFACE}; border-radius: 8px 8px 0 0; color: {INK_SECONDARY}; }}
    .stTabs [aria-selected="true"] {{ color: {INK_PRIMARY} !important; }}
    .hero-callout {{
        background: linear-gradient(135deg, {SURFACE} 0%, #14202e 100%);
        border: 1px solid {BORDER}; border-radius: 14px; padding: 22px 26px; margin-bottom: 22px;
    }}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
df = load_trend()

if df.empty:
    st.warning("No data in marts.mart_decarbonization_trend yet — run the dbt pipeline first.")
    st.stop()

fuel_df = load_fuel_mix()
summary_df = build_period_summary(df)
first_year, last_year = int(df["year"].min()), int(df["year"].max())

national = df.groupby("year").agg(
    clean_mw=("clean_capacity_mw", "sum"),
    total_mw=("total_capacity_mw", "sum"),
    ghg=("total_ghg_emissions_metric_tons", "sum"),
).reset_index()
national["clean_share"] = national["clean_mw"] / national["total_mw"]

share_first = national.loc[national.year == first_year, "clean_share"].iloc[0]
share_last = national.loc[national.year == last_year, "clean_share"].iloc[0]
ghg_first = national.loc[national.year == first_year, "ghg"].iloc[0]
ghg_last = national.loc[national.year == last_year, "ghg"].iloc[0]
mw_added = national.loc[national.year == last_year, "clean_mw"].iloc[0] - national.loc[national.year == first_year, "clean_mw"].iloc[0]

divergent_states = df[(df.year == last_year) & (df.capacity_emissions_divergence_flag)]["state_code"].nunique()
total_states = df["state_code"].nunique()

# Spotlight: biggest divergence gap among states with real grid scale (excludes noisy tiny grids).
major = summary_df[summary_df.total_capacity_mw_latest > 5000]
spotlight = major.sort_values("divergence_gap", ascending=False).iloc[0]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("## ⚡ State Decarbonization Tracker")
st.markdown(
    f'<div style="color:{INK_SECONDARY};font-size:15px;margin-top:-10px;margin-bottom:22px;">'
    f"Clean-energy capacity growth (EIA generator capacity) vs. real facility GHG emissions "
    f"(EPA GHGRP) — do capacity additions actually show up as measured decarbonization?</div>",
    unsafe_allow_html=True,
)

hero_text = (
    f"Nationally, clean capacity grew <b>{share_first:.0%} → {share_last:.0%}</b> of total generation "
    f"capacity while power-sector emissions fell <b>{(ghg_last/ghg_first - 1):.0%}</b> — a reasonable pace. "
    f"But <b>{spotlight['state_code']}</b>, one of the largest grids in the country, grew clean capacity "
    f"<b>+{spotlight['clean_capacity_growth_pct']:.0%}</b> while its own emissions fell only "
    f"<b>{spotlight['emissions_change_pct']:.0%}</b> — installed capacity isn't the same as generation "
    f"actually displacing fossil output."
)
st.markdown(
    f'<div class="hero-callout">'
    f'<div style="color:{INK_MUTED};font-size:12.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;">The finding</div>'
    f'<div style="color:{INK_PRIMARY};font-size:19px;font-weight:500;margin-top:8px;line-height:1.5;">{hero_text}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(stat_tile(
        "National clean capacity share", f"{share_last:.1%}",
        f"+{(share_last-share_first)*100:.1f}pp", delta_good=True,
        sublabel=f"vs {share_first:.1%} in {first_year}",
    ), unsafe_allow_html=True)
with c2:
    st.markdown(stat_tile(
        "Power-sector GHG emissions", f"{ghg_last/1e9:.2f}B tons",
        f"{(ghg_last/ghg_first - 1):+.1%}", delta_good=False,
        sublabel=f"vs {ghg_first/1e9:.2f}B tons in {first_year}",
    ), unsafe_allow_html=True)
with c3:
    st.markdown(stat_tile(
        "Clean capacity added", f"+{mw_added/1000:.1f} GW",
        None, sublabel=f"{first_year}–{last_year}, nationwide",
    ), unsafe_allow_html=True)
with c4:
    st.markdown(stat_tile(
        "States in divergence", f"{divergent_states} / {total_states}",
        None, sublabel=f"capacity growing, emissions flat/up ({last_year})",
    ), unsafe_allow_html=True)
with c5:
    st.markdown(stat_tile(
        "Biggest gap (major grid)", spotlight["state_code"],
        f"+{spotlight['divergence_gap']:.0%}", delta_good=False,
        sublabel="capacity growth − emissions decline",
    ), unsafe_allow_html=True)

st.write("")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Filters")
    all_states = sorted(df["state_code"].unique().tolist())
    default_states = [s for s in ["TX", "CA", "FL", "NY", "WA", "IL"] if s in all_states]
    selected_states = st.multiselect("Compare states", all_states, default=default_states)

    st.markdown("---")
    st.markdown("### How this was built")
    st.caption(
        "EIA 860M generator capacity + EPA GHGRP facility emissions, 2019–2023, "
        "joined at the state/year grain. Loaded via Python → Postgres, modeled with "
        "dbt (medallion architecture), orchestrated with Dagster."
    )
    with st.expander("Data quirks handled"):
        st.markdown("""
- EPA's API moved from `efservice` to `dmapservice` mid-project
- The facts table mixes direct-emitter and supplier "potential emissions" —
  filtered to power-sector direct emitters only (was inflating totals ~4-5x)
- A broken IPv6 path was silently hanging NOAA ingestion
- dbt's default schema naming needed a `generate_schema_name` override
        """)

if not selected_states:
    selected_states = default_states

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_map, tab_trends, tab_ml, tab_explorer = st.tabs(
    ["📊 Overview", "🗺️ State Map", "📈 State Comparison", "🤖 ML Insights", "🔍 Data Explorer"]
)

with tab_overview:
    left, right = st.columns([3, 2])

    with left:
        st.markdown("#### National Capacity Mix")
        fuel_pivot = fuel_df.copy()
        fig_fuel = go.Figure()
        for fuel in ["Coal", "Natural Gas", "Nuclear", "Hydro", "Wind", "Solar"]:
            d = fuel_pivot[fuel_pivot.fuel == fuel]
            if d.empty:
                continue
            fig_fuel.add_trace(go.Scatter(
                x=d.year, y=d.capacity_mw, name=fuel, mode="lines",
                stackgroup="one", line=dict(width=0.5, color=FUEL_COLORS.get(fuel, "#888")),
                fillcolor=FUEL_COLORS.get(fuel, "#888"),
            ))
        fig_fuel.update_xaxes(dtick=1, tickformat="d", title="Year")
        fig_fuel.update_yaxes(title="Nameplate capacity (MW)")
        fig_fuel = style_fig(fig_fuel, height=420)
        st.plotly_chart(fig_fuel, use_container_width=True, theme=None)

    with right:
        st.markdown("#### Emissions vs. Capacity Index")
        idx = national.copy()
        idx["capacity_idx"] = idx.clean_mw / idx.clean_mw.iloc[0] * 100
        idx["ghg_idx"] = idx.ghg / idx.ghg.iloc[0] * 100
        fig_idx = go.Figure()
        fig_idx.add_trace(go.Scatter(x=idx.year, y=idx.capacity_idx, name="Clean capacity",
                                      line=dict(color=CATEGORICAL[0], width=3), mode="lines+markers"))
        fig_idx.add_trace(go.Scatter(x=idx.year, y=idx.ghg_idx, name="GHG emissions",
                                      line=dict(color=CATEGORICAL[7], width=3), mode="lines+markers"))
        fig_idx.add_hline(y=100, line_dash="dot", line_color=GRIDLINE)
        fig_idx.update_xaxes(dtick=1, tickformat="d", title="Year")
        fig_idx.update_yaxes(title=f"Index ({first_year} = 100)")
        fig_idx = style_fig(fig_idx, height=420)
        st.plotly_chart(fig_idx, use_container_width=True, theme=None)
        st.caption("Clean capacity is climbing faster than emissions are falling — the gap between the two lines is the national version of the same story told state by state on the Map and Comparison tabs.")

with tab_map:
    st.markdown(f"#### Decarbonization Gap by State, {first_year}–{last_year}")
    st.caption("Clean-capacity growth % + emissions change % over the full window. Positive (red) = capacity grew faster than emissions fell. Negative (blue) = emissions fell as fast or faster than capacity grew.")
    fig_map = px.choropleth(
        summary_df, locations="state_code", locationmode="USA-states",
        color="divergence_gap", scope="usa",
        color_continuous_scale=DIVERGING_SCALE, range_color=[-1, 2],
        hover_data={"state_code": True, "clean_capacity_growth_pct": ":.0%", "emissions_change_pct": ":.0%", "divergence_gap": ":.0%"},
    )
    fig_map.update_layout(
        geo=dict(bgcolor=SURFACE, lakecolor=SURFACE, landcolor="#2a2a28"),
        coloraxis_colorbar=dict(title="Gap", tickformat=".0%", tickfont=dict(color=INK_SECONDARY)),
    )
    fig_map = style_fig(fig_map, height=520)
    st.plotly_chart(fig_map, use_container_width=True, theme=None)

with tab_trends:
    st.markdown(f"#### Clean Capacity Share Over Time — {', '.join(selected_states)}")
    trend_df = df[df["state_code"].isin(selected_states)]
    fig1 = go.Figure()
    for i, state in enumerate(selected_states):
        d = trend_df[trend_df.state_code == state]
        fig1.add_trace(go.Scatter(
            x=d.year, y=d.clean_capacity_share, name=state, mode="lines+markers",
            line=dict(color=CATEGORICAL[i % len(CATEGORICAL)], width=2.5),
            marker=dict(size=8),
        ))
    fig1.update_yaxes(tickformat=".0%", title="Clean capacity share")
    fig1.update_xaxes(dtick=1, tickformat="d", title="Year")
    fig1 = style_fig(fig1, height=420)
    st.plotly_chart(fig1, use_container_width=True, theme=None)

    st.markdown(f"#### Capacity Growth vs. Emissions Change, {first_year}–{last_year}")
    fig2 = px.scatter(
        summary_df, x="clean_capacity_growth_pct", y="emissions_change_pct", text="state_code",
        size="total_capacity_mw_latest", color="divergence_gap",
        color_continuous_scale=DIVERGING_SCALE, range_color=[-1, 2],
    )
    fig2.update_traces(textposition="top center", textfont=dict(color=INK_SECONDARY, size=10),
                        marker=dict(line=dict(width=1, color=SURFACE)))
    fig2.update_xaxes(tickformat=".0%", title="Clean capacity growth")
    fig2.update_yaxes(tickformat=".0%", title="Emissions change")
    fig2.add_hline(y=0, line_dash="dot", line_color=GRIDLINE)
    fig2.add_vline(x=0, line_dash="dot", line_color=GRIDLINE)
    fig2.update_layout(coloraxis_colorbar=dict(title="Gap", tickformat=".0%"))
    fig2 = style_fig(fig2, height=460)
    st.plotly_chart(fig2, use_container_width=True, theme=None)
    st.caption("Bottom-left = capacity shrank and emissions fell. Top-right = capacity grew and emissions also rose. States above the diagonal grew capacity faster than emissions fell.")

    st.markdown("#### Decarbonization Gap — Ranked")
    ranked = summary_df.sort_values("divergence_gap", ascending=False).head(15)
    fig3 = px.bar(
        ranked, x="divergence_gap", y="state_code", orientation="h",
        color="divergence_gap", color_continuous_scale=DIVERGING_SCALE, range_color=[-1, 2],
    )
    fig3.update_yaxes(categoryorder="total ascending", title="")
    fig3.update_xaxes(tickformat=".0%", title="Capacity growth + emissions change")
    fig3.update_layout(coloraxis_showscale=False)
    fig3 = style_fig(fig3, height=440)
    st.plotly_chart(fig3, use_container_width=True, theme=None)

with tab_ml:
    archetypes_df = load_archetypes()
    importance_df = load_feature_importance()
    anomalies_df = load_anomalies()

    ARCHETYPE_COLORS = {
        "Aggressive Decarbonizers": "#008300",
        "Capacity Theater": "#e66767",
        "Fossil Holdouts": "#d95926",
        "Steady Movers": "#3987e5",
    }

    st.markdown("#### State Decarbonization Archetypes")
    st.caption(
        "K-Means clustering (k chosen by silhouette score) over each state's clean-capacity "
        "share, capacity growth, emissions change, and divergence gap. Small grids (<5,000 MW) "
        "are excluded from training — their tiny installed base turns small absolute changes "
        "into huge % swings that would dominate the clustering — and are instead assigned to "
        "their nearest archetype by distance."
    )

    left, right = st.columns([3, 2])
    with left:
        fig_cluster = px.scatter(
            archetypes_df, x="pca_x", y="pca_y", color="archetype", text="state_code",
            color_discrete_map=ARCHETYPE_COLORS,
            labels={"pca_x": "PCA component 1", "pca_y": "PCA component 2"},
        )
        fig_cluster.update_traces(textposition="top center", textfont=dict(color=INK_SECONDARY, size=9),
                                   marker=dict(size=10, line=dict(width=1, color=SURFACE)))
        fig_cluster = style_fig(fig_cluster, height=440)
        st.plotly_chart(fig_cluster, use_container_width=True, theme=None)

    with right:
        st.markdown("##### States by archetype")
        for name, color in ARCHETYPE_COLORS.items():
            states = sorted(archetypes_df.loc[archetypes_df.archetype == name, "state_code"].tolist())
            if not states:
                continue
            st.markdown(
                f'<div style="border-left:3px solid {color};padding:6px 12px;margin-bottom:10px;background:{SURFACE};border-radius:0 8px 8px 0;">'
                f'<div style="color:{INK_PRIMARY};font-weight:600;font-size:13.5px;">{name} ({len(states)})</div>'
                f'<div style="color:{INK_SECONDARY};font-size:12px;margin-top:2px;">{", ".join(states)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()
    st.markdown("#### Facility Emissions Model")
    st.caption(
        "Random Forest predicting a natural-gas plant's facility GHG emissions from its own "
        "capacity, generator count, state, and year — trained on ~12,000 matched plant-facility "
        "pairs. Residuals (actual minus predicted) flag facilities emitting far more or less "
        "than their size would suggest."
    )

    model_r2 = float(anomalies_df["model_r2"].iloc[0])
    model_mae = float(anomalies_df["model_mae"].iloc[0])
    n_confident = int(anomalies_df["high_confidence_match"].sum())

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(stat_tile("Held-out R²", f"{model_r2:.2f}", sublabel="test set, 80/20 split"), unsafe_allow_html=True)
    with m2:
        st.markdown(stat_tile("Held-out MAE", f"{model_mae/1000:.0f}K tons", sublabel="mean absolute error"), unsafe_allow_html=True)
    with m3:
        st.markdown(stat_tile("Training rows", f"{len(anomalies_df):,}", sublabel=f"{n_confident:,} high-confidence matches"), unsafe_allow_html=True)

    st.write("")
    left2, right2 = st.columns([2, 3])
    with left2:
        fig_imp = px.bar(
            importance_df, x="importance", y="group", orientation="h",
            color_discrete_sequence=[CATEGORICAL[0]],
        )
        fig_imp.update_yaxes(categoryorder="total ascending", title="")
        fig_imp.update_xaxes(title="Feature importance", tickformat=".0%")
        fig_imp = style_fig(fig_imp, height=320)
        st.plotly_chart(fig_imp, use_container_width=True, theme=None)
        st.caption("Capacity alone drives most of the prediction — physically expected. The remaining ~30% is where state/year/generator-count add real signal.")

    with right2:
        fig_resid = px.histogram(anomalies_df, x="residual_ratio", nbins=60, color_discrete_sequence=[CATEGORICAL[0]])
        fig_resid.update_xaxes(range=[-1.2, 5], title="Residual ratio (actual − predicted) / predicted", tickformat=".0%")
        fig_resid.update_yaxes(title="Plant-years")
        fig_resid.add_vline(x=0, line_dash="dot", line_color=GRIDLINE)
        fig_resid = style_fig(fig_resid, height=320)
        st.plotly_chart(fig_resid, use_container_width=True, theme=None)
        st.caption("Most plants cluster near 0% (emissions in line with capacity). The long right tail is real — some gas plants run far dirtier per MW than peers of the same size.")

    st.markdown("##### Facility-level outliers")
    st.info(
        "⚠️ The plant-to-facility match is an approximate geographic join (see README), so even "
        "the confident matches below can occasionally attribute a multi-unit site's full emissions "
        "to one fuel-type subset of its generators. Treat these as **leads worth checking**, not "
        "confirmed findings.",
        icon="⚠️",
    )
    confident_df = anomalies_df[anomalies_df["high_confidence_match"]].copy()
    outlier_cols = ["plant_name", "state_code", "year", "total_capacity_mw", "nearby_facility_ghg_emissions", "predicted_emissions", "residual_ratio"]
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**Emitting far more than expected**")
        over = confident_df.nlargest(8, "residual_ratio")[outlier_cols].copy()
        over["residual_ratio"] = over["residual_ratio"].map(lambda v: f"{v:+.0%}")
        st.dataframe(over, use_container_width=True, hide_index=True)
    with oc2:
        st.markdown("**Emitting far less than expected**")
        under = confident_df.nsmallest(8, "residual_ratio")[outlier_cols].copy()
        under["residual_ratio"] = under["residual_ratio"].map(lambda v: f"{v:+.0%}")
        st.dataframe(under, use_container_width=True, hide_index=True)

with tab_explorer:
    st.markdown("#### State × Year Data")
    display_df = df.copy()
    for col in ["clean_capacity_share", "yoy_clean_capacity_growth", "yoy_emissions_change"]:
        display_df[col] = display_df[col].map(lambda v: f"{v:.1%}" if pd.notnull(v) else "—")
    for col in ["total_capacity_mw", "clean_capacity_mw", "fossil_capacity_mw", "total_ghg_emissions_metric_tons"]:
        display_df[col] = display_df[col].round(0)
    st.dataframe(display_df, use_container_width=True, height=500)
    st.download_button(
        "Download full dataset (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        "decarbonization_trend.csv",
        "text/csv",
    )
