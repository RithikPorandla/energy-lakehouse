"""Dagster definitions — entry point."""
from dagster import Definitions

from dagster_project.assets import (
    raw_eia_generators,
    raw_epa_emissions,
    raw_noaa_weather,
    raw_eia_generation,
    dbt_transforms,
    dbt_tests,
    ml_state_archetypes,
    ml_facility_emissions_anomalies,
)
from dagster_project.schedules import daily_schedule, daily_pipeline_job
from dagster_project.sensors import new_data_sensor, refresh_job

defs = Definitions(
    assets=[
        raw_eia_generators,
        raw_epa_emissions,
        raw_noaa_weather,
        raw_eia_generation,
        dbt_transforms,
        dbt_tests,
        ml_state_archetypes,
        ml_facility_emissions_anomalies,
    ],
    schedules=[daily_schedule],
    sensors=[new_data_sensor],
    jobs=[daily_pipeline_job, refresh_job],
)
