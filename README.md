# Energy Data Lakehouse — State Decarbonization Tracker

A data lakehouse that ingests US energy data from three public APIs (EIA, EPA, NOAA), transforms it through a dbt medallion architecture, orchestrates the pipeline with Dagster, and surfaces a real finding through an interactive dashboard: **is clean-energy capacity growth actually translating into falling measured emissions, state by state?**

## The finding

Nationally, the picture looks reasonable: from 2019 to 2023, total US power-sector clean generation capacity (solar/wind/hydro/nuclear) grew **39.1% → 43.8%** of total capacity (+28% in absolute MW), while total power-sector GHG emissions reported to EPA's GHGRP fell **~12%** (1.66B → 1.47B metric tons CO2e).

But that aggregate hides a wide split at the state level. **Texas** grew clean capacity **+68%** over the same window while its power-sector emissions fell only **~5%**. **Florida** grew clean capacity **+95%** while its emissions fell **~4.5%**. Ohio, Indiana, Wyoming, and New Mexico show the same pattern: large, real capacity buildouts that haven't yet shown up as proportional drops in measured facility emissions — installed capacity isn't the same as generation actually displacing fossil output. (Small-grid states like Rhode Island, DC, and Maine show even larger percentage swings, but off tiny bases — treat those as noisy, not as the headline.)

Explore it yourself in the dashboard (`streamlit run dashboard/app.py`) or query `marts.mart_decarbonization_trend` directly.

## Dashboard

Five tabs, backed live by the warehouse (`dashboard/app.py`), styled with a validated colorblind-safe dark palette (`scripts/validate_palette.js` — see `dataviz` methodology):

- **Overview** — KPI row (national clean share, GHG total, capacity added, states in divergence, biggest-gap spotlight), a national fuel-mix stacked area chart, and a clean-capacity-vs-emissions index chart
- **State Map** — a US choropleth of the decarbonization gap by state (diverging blue→red)
- **State Comparison** — clean-capacity-share trend for a sidebar-selectable set of states, the capacity-growth-vs-emissions-change scatter, and the ranked gap bar chart
- **ML Insights** — the two models below: archetype clusters and the facility emissions model
- **Data Explorer** — the full `mart_decarbonization_trend` table with CSV export

## Machine learning

Two models, both written by `ml/` scripts as Dagster assets (`ml_state_archetypes`, `ml_facility_emissions_anomalies`) into a new `analytics` schema. Chosen deliberately for what the data can actually support — we have 51 states of panel data (too few rows for a supervised model to generalize) and ~50,000 plant-year records (plenty for a real regression):

**State Decarbonization Archetypes** (K-Means, `ml/archetypes.py`) — unsupervised clustering of states by clean-capacity share, capacity growth, emissions change, and divergence gap, the same technique used in published power-sector transition research (clustering countries/states into named archetypes). States under 5,000 MW of total capacity are excluded from *fitting* the model — their tiny installed base turns small absolute changes into huge % swings that would otherwise dominate the clustering — and are instead assigned to their nearest archetype by distance. k=4 was chosen by silhouette score. Result:

- **Capacity Theater** (14 states: TX, FL, OH, IN, NM, WY, NV, CO, OK, WI, SD, RI, DE, DC) — this cluster **independently rediscovered, via unsupervised learning, the same states flagged manually in "The finding" above** — real cross-validation that the divergence pattern is structural, not cherry-picked.
- **Fossil Holdouts** (19 states) — low clean share, low growth: AL, AR, GA, KY, LA, WV, MI, MO, NC, VA, PA, and others.
- **Aggressive Decarbonizers** (11 states) — WA, IA, KS, ND, NE, MT, OR and other wind-belt/hydro states with real capacity growth *and* falling emissions.
- **Steady Movers** (6 states) — CA, NY, CT, ID, ME, MS: large, already-established programs without dramatic YoY swings.

**Facility Emissions Model** (Random Forest, `ml/anomaly_detection.py`) — predicts a natural-gas plant's own GHG emissions from its capacity, generator count, state, and year, trained on ~12,000 matched plant-facility pairs, held-out R² ≈ 0.42 (MAE ≈ 460K tons). Restricted to natural gas only: `fact_plant_operations`'s plant-to-facility join is an approximate lat/long match, which is only physically meaningful for combustion facilities (a solar plant "matched" to a nearby emitter is coincidence, not its own emissions). Capacity dominates feature importance (~69%, physically expected — bigger plants emit more), with state/generator-count/year explaining the rest. Residuals (out-of-fold, 5-fold CV, not in-sample) flag facilities that emit far more or less than their size predicts.

**Being honest about the anomaly list's limits**: even restricted to gas plants and low-multiplicity geo-matches, individual "outlier" facilities can still reflect a data-join artifact rather than a real anomaly — a multi-unit industrial site can have its *entire* emissions total attributed to just the natural-gas subset of its generators when a coal or other-fuel unit at the same site isn't in the match. The dashboard surfaces the outlier list with that caveat front and center; treat it as leads worth checking, not confirmed findings. The R² and feature-importance results are robust regardless (they're aggregate statistics, not dependent on any single match being clean).

## Architecture

```
[EIA 860M API]  ──┐  (generator capacity, 2019-2023 Dec snapshots)
[EPA GHGRP API] ──┼──→ [Dagster Pipeline] ──→ [PostgreSQL]
[NOAA Weather]  ──┘         │                     │
                             │                     ▼
                      orchestrates          [dbt Transforms]
                      schedules             raw → staging → intermediate → marts
                      monitors                    │
                                                   ▼
                                       marts.mart_decarbonization_trend
                                       (the headline insight)
                                              +
                                       star schema: fact_plant_operations,
                                       dim_plant, dim_location, dim_time
                                              │
                                              ▼
                                    [ml/ — scikit-learn, Dagster assets]
                                    K-Means archetypes + Random Forest
                                    facility emissions model
                                              │
                                              ▼
                                       analytics.ml_state_archetypes
                                       analytics.ml_facility_emissions_anomalies
                                              │
                                              ▼
                                   Streamlit + Plotly dashboard
```

## Data sources

| Source | Data | Years | API key |
|---|---|---|---|
| EIA 860M | Generator nameplate capacity, fuel type, location | 2019-2023 (Dec snapshots) | Yes (free) |
| EPA GHGRP | Real facility-level annual GHG emissions (power sector only) | 2019-2023 | No |
| NOAA CDO | Daily weather (5 stations near major renewable installations) | 2019-2023 | No |

Two things about these sources that aren't obvious from the original tutorial this project started from, and matter for correctness:

- **EPA's API moved.** `data.epa.gov/efservice` is being superseded by `data.epa.gov/dmapservice`. More importantly, the facility table (`PUB_DIM_FACILITY`) is metadata only — no emissions numbers. Real annual CO2e totals live in `PUB_FACTS_SECTOR_GHG_EMISSION`, joined by `facility_id` + `year`. See [src/ingestion/epa.py](src/ingestion/epa.py).
- **That facts table mixes two incompatible measures.** Direct-emitter sectors (`sector_type='E'`, e.g. Power Plants) report a facility's own on-site emissions. Supplier sectors (`sector_type='S'`, e.g. Petroleum Suppliers) report the *potential* emissions embedded in fuel sold downstream for someone else to burn. Summing both double-counts the same carbon. This build filters to `sector_id=3` (Power Plants) only — verified against the known ~1.6-1.7B ton nationwide power-sector total for 2019.

## Star schema

- `mart_decarbonization_trend` — **the headline mart.** State × year: clean capacity share, real GHG totals, YoY deltas, divergence flag.
- `fact_plant_operations` — plant-level operational detail (capacity, nearby facility emissions where geographically matched)
- `dim_plant`, `dim_location`, `dim_time` — supporting dimensions

## Quick start

```bash
# 1. Start Postgres
docker compose up -d

# 2. Python env (3.10+ required)
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Ingest (needs a free EIA key in .env — https://www.eia.gov/opendata/register.php)
python -m src.ingestion.eia
python -m src.ingestion.epa
python -m src.ingestion.noaa

# 4. Transform
cd dbt_project && dbt deps && dbt run && dbt test && dbt docs generate && cd ..

# 5. ML (state archetypes + facility emissions model)
python -m ml.archetypes
python -m ml.anomaly_detection

# 6. Orchestrate (optional — runs the whole pipeline, including ML, as Dagster assets)
export PYTHONPATH=$(pwd)
dagster dev -m dagster_project.definitions
# open http://localhost:3000, materialize all assets

# 7. Dashboard
streamlit run dashboard/app.py
```

## Tech stack

Python, dbt, Dagster, PostgreSQL, Docker, scikit-learn, Streamlit/Plotly, GitHub Actions

## What this demonstrates

1. **dbt** — staging → intermediate → marts, schema tests, docs, packages (`dbt_utils`)
2. **Dagster** — software-defined assets with real dependencies (ingestion → transform → test → ML), schedules, sensors
3. **Dimensional modeling** — star schema (facts + dimensions) alongside a purpose-built analytical mart
4. **Medallion architecture** — raw → staging → intermediate → marts → analytics, all schema-separated in Postgres
5. **Machine learning matched to what the data supports** — unsupervised clustering for a 51-row population (too small for supervised learning), a real regression for a 50,000-row population, both with honestly reported metrics and limitations rather than overclaimed accuracy
6. **Data quality** — dbt tests, plus real-world data validation (catching a nationwide GHGRP emissions total that was 4-5x too high before it reached any model, and a clustering run that degenerated until outlier states were properly handled)
7. **API integration under real-world conditions** — an API that moved endpoints mid-project, a metrics table that silently mixed two incompatible measures, pagination limits, and a broken IPv6 path that had to be diagnosed and worked around
8. **CI/CD for data** — GitHub Actions running dbt tests on every PR
9. **Docker** — containerized PostgreSQL with medallion schemas
10. **Analytics presentation** — actual findings, not just tables, shown through an interactive dashboard
