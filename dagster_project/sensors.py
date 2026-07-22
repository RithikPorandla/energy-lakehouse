"""Dagster sensors for event-driven pipeline triggers."""
import os

from dagster import sensor, RunRequest, SensorEvaluationContext, define_asset_job

refresh_job = define_asset_job(
    name="refresh_on_new_data",
    selection="*",
)


@sensor(job=refresh_job, minimum_interval_seconds=300)
def new_data_sensor(context: SensorEvaluationContext):
    """Check for new raw data files and trigger pipeline."""
    raw_dir = "data/raw"
    if not os.path.exists(raw_dir):
        return

    for filename in os.listdir(raw_dir):
        filepath = os.path.join(raw_dir, filename)
        mod_time = os.path.getmtime(filepath)

        last_check = float(context.cursor) if context.cursor else 0

        if mod_time > last_check:
            context.update_cursor(str(mod_time))
            yield RunRequest(
                run_key=f"new_data_{filename}_{mod_time}",
            )
