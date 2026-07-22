"""
State Decarbonization Archetypes — unsupervised K-Means clustering.

Groups states by their capacity-growth / emissions-change profile into
labeled archetypes (e.g. "Aggressive Decarbonizers", "Capacity Theater").
This mirrors the archetype-clustering approach used in published power-sector
transition research (e.g. Ansari & McCulloch-style global archetype papers) —
clustering is the right technique here because we only have 51 states worth
of rows: far too few for a supervised model to generalize, but plenty for
an unsupervised grouping of a fixed, small population.

Writes: analytics.ml_state_archetypes
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import RobustScaler

from src.utils.db import get_engine

FEATURES = [
    "clean_capacity_share_latest",
    "clean_capacity_growth_pct",
    "emissions_change_pct",
    "divergence_gap",
]

# Same "major grid" cutoff used for the dashboard's spotlight stat. Below this,
# a state's tiny installed base turns small absolute MW changes into huge %
# swings (Rhode Island's +200% capacity growth is a handful of solar farms,
# not a real grid transition) — those swings dominate the clustering variance
# and produce a degenerate "outliers vs. everyone else" split rather than a
# meaningful archetype grouping. Excluded states aren't erased: they inherit
# the nearest major-grid state's archetype by feature distance (see below).
MAJOR_GRID_MW_THRESHOLD = 5000


def build_state_features(df: pd.DataFrame) -> pd.DataFrame:
    """One row per state: latest clean share + full-period growth/emissions deltas."""
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
            "clean_capacity_share_latest": last["clean_capacity_share"],
            "clean_capacity_growth_pct": capacity_growth,
            "emissions_change_pct": emissions_change,
            "divergence_gap": capacity_growth + emissions_change,
            "total_capacity_mw_latest": last["total_capacity_mw"],
        })
    return pd.DataFrame(rows)


def pick_k(X_scaled, k_range=range(2, 7)):
    """Choose k by silhouette score, breaking ties toward k=4 (matches the
    four narrative archetypes: aggressive / theater / holdout / steady)."""
    scores = {}
    for k in k_range:
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X_scaled)
        scores[k] = silhouette_score(X_scaled, labels)
    best_k = max(scores, key=scores.get)
    print(f"Silhouette scores by k: { {k: round(v, 3) for k, v in scores.items()} }")
    # If k=4 is within 0.02 of the best score, prefer it for interpretability.
    if abs(scores.get(4, -1) - scores[best_k]) <= 0.02:
        return 4, scores
    return best_k, scores


def name_archetypes(centroids: pd.DataFrame) -> dict:
    """Map cluster_id -> human-readable archetype name from centroid stats
    (in original units, not scaled)."""
    remaining = set(centroids.index)
    names = {}

    theater = centroids.loc[list(remaining), "divergence_gap"].idxmax()
    names[theater] = "Capacity Theater"
    remaining.discard(theater)

    holdout = centroids.loc[list(remaining), "clean_capacity_share_latest"].idxmin()
    names[holdout] = "Fossil Holdouts"
    remaining.discard(holdout)

    if remaining:
        aggressive = centroids.loc[list(remaining), "emissions_change_pct"].idxmin()
        names[aggressive] = "Aggressive Decarbonizers"
        remaining.discard(aggressive)

    for cid in remaining:
        names[cid] = "Steady Movers"

    return names


def run_archetypes():
    engine = get_engine()
    df = pd.read_sql("select * from marts.mart_decarbonization_trend", engine)

    state_features = build_state_features(df)
    print(f"Built features for {len(state_features)} states")

    is_major = state_features["total_capacity_mw_latest"] >= MAJOR_GRID_MW_THRESHOLD
    major, minor = state_features[is_major].copy(), state_features[~is_major].copy()
    print(f"Clustering on {len(major)} major-grid states (>= {MAJOR_GRID_MW_THRESHOLD} MW); "
          f"{len(minor)} small grids will be assigned to their nearest archetype")

    scaler = RobustScaler()
    X_major = scaler.fit_transform(major[FEATURES].values)

    k, silhouette_scores = pick_k(X_major)
    print(f"Using k={k}")

    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    major["cluster_id"] = kmeans.fit_predict(X_major)

    centroids = major.groupby("cluster_id")[FEATURES].mean()
    archetype_map = name_archetypes(centroids)
    major["archetype"] = major["cluster_id"].map(archetype_map)

    # Small grids didn't train the model (their outlier % swings would have
    # dominated it) but still get a label: nearest centroid by distance in
    # the same scaled feature space the model was fit on.
    if len(minor):
        X_minor = scaler.transform(minor[FEATURES].values)
        minor["cluster_id"] = kmeans.predict(X_minor)
        minor["archetype"] = minor["cluster_id"].map(archetype_map)

    state_features = pd.concat([major, minor], ignore_index=True)

    pca = PCA(n_components=2, random_state=42)
    X_all_scaled = scaler.transform(state_features[FEATURES].values)
    coords = pca.fit_transform(X_all_scaled)
    state_features["pca_x"] = coords[:, 0]
    state_features["pca_y"] = coords[:, 1]
    print(f"PCA explained variance: {pca.explained_variance_ratio_.sum():.1%}")

    print("\nArchetype summary:")
    for cid, name in archetype_map.items():
        states = state_features.loc[state_features.cluster_id == cid, "state_code"].tolist()
        print(f"  {name} ({len(states)}): {', '.join(sorted(states))}")

    state_features.to_sql(
        "ml_state_archetypes", engine, schema="analytics", if_exists="replace", index=False
    )
    print(f"\n✓ Wrote {len(state_features)} rows to analytics.ml_state_archetypes")
    return state_features


if __name__ == "__main__":
    run_archetypes()
