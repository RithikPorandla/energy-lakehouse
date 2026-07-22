"""Dagster software-defined assets for the energy lakehouse."""
import subprocess

from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue


@asset(group_name="ingestion", description="Ingest EIA 860M generator capacity data (2019-2023)")
def raw_eia_generators(context: AssetExecutionContext):
    """Pull multi-year December-snapshot generator data from EIA API into raw schema."""
    from src.ingestion.eia import ingest_eia
    df = ingest_eia()
    return MaterializeResult(
        metadata={
            "row_count": MetadataValue.int(len(df)),
            "columns": MetadataValue.text(str(list(df.columns))),
        }
    )


@asset(group_name="ingestion", description="Ingest EPA GHGRP facility emissions data (2019-2023)")
def raw_epa_emissions(context: AssetExecutionContext):
    """Pull real facility-level annual GHG emissions totals from EPA GHGRP into raw schema."""
    from src.ingestion.epa import ingest_epa
    df = ingest_epa()
    return MaterializeResult(
        metadata={
            "row_count": MetadataValue.int(len(df)),
        }
    )


@asset(group_name="ingestion", description="Ingest NOAA weather data (2019-2023)")
def raw_noaa_weather(context: AssetExecutionContext):
    """Pull daily weather summaries from NOAA into raw schema."""
    from src.ingestion.noaa import ingest_noaa
    df = ingest_noaa()
    return MaterializeResult(
        metadata={
            "row_count": MetadataValue.int(len(df)),
        }
    )


@asset(
    group_name="transform",
    deps=[raw_eia_generators, raw_epa_emissions, raw_noaa_weather],
    description="Run dbt transformations: staging → intermediate → marts",
)
def dbt_transforms(context: AssetExecutionContext):
    """Run dbt to transform raw data through medallion layers."""
    result = subprocess.run(
        ["dbt", "run", "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"],
        capture_output=True,
        text=True,
    )
    context.log.info(result.stdout)
    if result.returncode != 0:
        context.log.error(result.stderr)
        raise Exception(f"dbt run failed: {result.stderr}")

    return MaterializeResult(
        metadata={
            "dbt_output": MetadataValue.text(result.stdout[-500:]),
        }
    )


@asset(
    group_name="quality",
    deps=[dbt_transforms],
    description="Run dbt tests for data quality validation",
)
def dbt_tests(context: AssetExecutionContext):
    """Run dbt tests to validate data quality."""
    result = subprocess.run(
        ["dbt", "test", "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"],
        capture_output=True,
        text=True,
    )
    context.log.info(result.stdout)
    if result.returncode != 0:
        context.log.error(result.stderr)
        raise Exception(f"dbt tests failed: {result.stderr}")

    return MaterializeResult(
        metadata={
            "test_output": MetadataValue.text(result.stdout[-500:]),
        }
    )


@asset(
    group_name="ml",
    deps=[dbt_transforms],
    description="K-Means clustering of states into decarbonization archetypes",
)
def ml_state_archetypes(context: AssetExecutionContext):
    """Cluster states by capacity-growth/emissions-change profile into labeled archetypes."""
    from ml.archetypes import run_archetypes
    df = run_archetypes()
    counts = df["archetype"].value_counts().to_dict()
    return MaterializeResult(
        metadata={
            "row_count": MetadataValue.int(len(df)),
            "archetype_counts": MetadataValue.json(counts),
        }
    )


@asset(
    group_name="ml",
    deps=[dbt_transforms],
    description="Random Forest model predicting facility emissions from plant capacity; flags anomalies",
)
def ml_facility_emissions_anomalies(context: AssetExecutionContext):
    """Train the facility emissions regression and write residual-based anomaly flags."""
    from ml.anomaly_detection import run_anomaly_detection
    df = run_anomaly_detection()
    return MaterializeResult(
        metadata={
            "row_count": MetadataValue.int(len(df)),
            "model_r2": MetadataValue.float(float(df["model_r2"].iloc[0])),
            "model_mae": MetadataValue.float(float(df["model_mae"].iloc[0])),
            "high_confidence_matches": MetadataValue.int(int(df["high_confidence_match"].sum())),
        }
    )
