"""
Facility Emissions Anomaly Detection — Random Forest regression.

Predicts a natural-gas plant's associated facility GHG emissions from its own
generator characteristics (capacity, generator count, state, year), then
flags facilities whose actual emissions deviate sharply from what a plant of
that size would normally produce.

Restricted to Natural Gas: fact_plant_operations' plant-to-facility match is
either a real ID join via EPA's official CAMD-EIA-FRS crosswalk
('crosswalk_exact') or, where that's not available, an approximate
state + rounded-lat/long match ('geo_approximate') — see
int_plant_emissions.sql. Either way it's only physically meaningful for
combustion facilities: a solar or wind plant sharing a plant_id (or grid
cell) with a gas unit isn't itself the source of that facility's emissions.
Gas is the fuel type EIA and EPA both track at the same physical facility
with the best crosswalk coverage, so the prediction task is meaningful there.

Writes: analytics.ml_facility_emissions_anomalies
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import cross_val_predict, train_test_split
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

from src.utils.db import get_engine

NUMERIC_FEATURES = ["total_capacity_mw", "generator_count"]
CATEGORICAL_FEATURES = ["state_code", "year"]
TARGET = "nearby_facility_ghg_emissions"


def load_training_data(engine) -> pd.DataFrame:
    # match_type = 'crosswalk_exact' means this plant<->facility pairing
    # came from EPA's official CAMD-EIA-FRS identifier crosswalk (a real ID
    # join), not the approximate rounded-lat/long grid-cell fallback — see
    # int_plant_emissions.sql. Both are fine to train on (more data, and the
    # geo-approximate noise mostly averages out), but only exact matches are
    # trustworthy enough to showcase as a single plant's confirmed anomaly.
    query = """
        select
            f.plant_id, f.state_code, f.year, f.total_capacity_mw,
            f.generator_count, f.nearby_facility_ghg_emissions, f.epa_facility_id,
            f.match_type, p.plant_name
        from marts.fact_plant_operations f
        join marts.dim_plant p on p.plant_id = f.plant_id
        where f.energy_type = 'Natural Gas'
          and f.nearby_facility_ghg_emissions is not null
    """
    return pd.read_sql(query, engine)


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer([
        ("num", "passthrough", NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    model = RandomForestRegressor(n_estimators=300, max_depth=10, random_state=42, n_jobs=-1)
    return Pipeline([("preprocess", preprocessor), ("model", model)])


def run_anomaly_detection():
    engine = get_engine()
    df = load_training_data(engine)
    print(f"Loaded {len(df)} natural-gas plant-year rows with matched facility emissions")

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X, y = df[feature_cols], df[TARGET]

    # Held-out test split to report an honest generalization metric.
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)
    y_pred_test = pipeline.predict(X_test)
    r2 = r2_score(y_test, y_pred_test)
    mae = mean_absolute_error(y_test, y_pred_test)
    print(f"Held-out test set: R² = {r2:.3f}, MAE = {mae:,.0f} metric tons CO2e")

    # Feature importance from a model fit on the full dataset.
    full_pipeline = build_pipeline()
    full_pipeline.fit(X, y)
    ohe = full_pipeline.named_steps["preprocess"].named_transformers_["cat"]
    feature_names = NUMERIC_FEATURES + list(ohe.get_feature_names_out(CATEGORICAL_FEATURES))
    importances = full_pipeline.named_steps["model"].feature_importances_
    top_importances = sorted(zip(feature_names, importances), key=lambda t: -t[1])[:10]
    print("\nTop feature importances:")
    for name, imp in top_importances:
        print(f"  {name}: {imp:.3f}")

    # Roll the one-hot state/year columns up to their parent feature for a
    # readable top-level chart (52 individual state dummies isn't a chart).
    importance_df = pd.DataFrame({"feature": feature_names, "importance": importances})
    importance_df["group"] = importance_df["feature"].apply(
        lambda f: "state_code" if f.startswith("state_code_") else ("year" if f.startswith("year_") else f)
    )
    grouped_importance = (
        importance_df.groupby("group", as_index=False)["importance"].sum()
        .sort_values("importance", ascending=False)
    )
    grouped_importance["model_r2"] = r2
    grouped_importance["model_mae"] = mae
    grouped_importance.to_sql(
        "ml_facility_emissions_feature_importance", engine, schema="analytics",
        if_exists="replace", index=False,
    )

    # Out-of-fold predictions (5-fold CV) for every row — using in-sample
    # predictions here would understate residuals for rows the model
    # memorized, making "anomaly" size meaningless.
    y_pred_oof = cross_val_predict(build_pipeline(), X, y, cv=5, n_jobs=-1)
    df["predicted_emissions"] = y_pred_oof
    df["residual"] = df[TARGET] - df["predicted_emissions"]
    df["residual_ratio"] = df["residual"] / df["predicted_emissions"]

    df["model_r2"] = r2
    df["model_mae"] = mae
    df["high_confidence_match"] = df["match_type"] == "crosswalk_exact"

    confident = df[df["high_confidence_match"]]
    print(f"\n{len(confident)} / {len(df)} rows are high-confidence (real crosswalk ID match, not "
          f"geo-approximate) — anomaly showcase below is restricted to those")

    cols = ["plant_name", "state_code", "year", "total_capacity_mw", TARGET, "predicted_emissions", "residual_ratio", "match_type"]
    print("\nTop over-emitters (actual >> predicted for their size):")
    print(confident.nlargest(5, "residual_ratio")[cols].to_string(index=False))
    print("\nTop under-emitters (actual << predicted for their size):")
    print(confident.nsmallest(5, "residual_ratio")[cols].to_string(index=False))

    df.to_sql(
        "ml_facility_emissions_anomalies", engine, schema="analytics",
        if_exists="replace", index=False,
    )
    print(f"\n✓ Wrote {len(df)} rows to analytics.ml_facility_emissions_anomalies")
    return df


if __name__ == "__main__":
    run_anomaly_detection()
