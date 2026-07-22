"""Dagster schedules for automated pipeline runs."""
from dagster import ScheduleDefinition, define_asset_job

# Daily ingestion + transform job
daily_pipeline_job = define_asset_job(
    name="daily_energy_pipeline",
    selection="*",  # All assets
)

# Run every day at 6 AM UTC
daily_schedule = ScheduleDefinition(
    job=daily_pipeline_job,
    cron_schedule="0 6 * * *",
    name="daily_energy_pipeline_schedule",
)
