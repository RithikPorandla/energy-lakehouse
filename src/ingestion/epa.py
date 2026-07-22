"""
EPA Greenhouse Gas Reporting Program (GHGRP)
Source: https://data.epa.gov/dmapservice/
Data: Facility-level GHG emissions from large industrial/power facilities.

Note: EPA's old `data.epa.gov/efservice` API has been replaced by
`data.epa.gov/dmapservice`. It also matters WHICH table you hit — the
facility table (`PUB_DIM_FACILITY`) is metadata only (name, address,
NAICS code); it has no emissions quantities. The actual annual CO2e
totals live in `PUB_FACTS_SECTOR_GHG_EMISSION` (facility_id x year x
sector x subsector x gas -> co2e_emission), which we sum per facility
per year and join back onto the facility dimension for location/name.

That facts table mixes two incompatible kinds of rows: direct-emitter
sectors (sector_type='E' — Power Plants, Refineries, Chemicals, ...)
report a facility's own on-site combustion emissions, while supplier
sectors (sector_type='S' — Petroleum/NG/Coal suppliers) report the
*potential* emissions embedded in fuel products sold downstream for
someone else to burn. Summing both for a facility double-counts the
same carbon twice (once as a supplier's product, once as whoever
combusts it). We filter to sector_id=3 (Power Plants) only, both to
avoid that double-count and because it's the sector that's actually
comparable to EIA generator capacity — verified against the known
~1.6-1.7B metric ton nationwide power-sector GHGRP total for 2019.
No API key required.
"""
import time
import requests
import pandas as pd
from src.utils.db import load_to_raw

DMAP_BASE_URL = "https://data.epa.gov/dmapservice"

# Matches the EIA capacity years (see eia.py) — this is also the latest
# year PUB_FACTS_SECTOR_GHG_EMISSION has published data for as of this build.
DEFAULT_YEARS = range(2019, 2024)

# GHGRP sector_id for "Power Plants" direct emitters (see PUB_DIM_SECTOR) —
# excludes supplier sectors, which report embedded product emissions, not
# a facility's own emissions (see module docstring).
POWER_SECTOR_ID = 3


def _get_json_with_retry(url, retries=4):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=90)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.HTTPError, requests.exceptions.Timeout) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"⚠ EPA request failed ({e}), retrying in {wait}s...")
            time.sleep(wait)


def _fetch_facility_dim(year: int) -> pd.DataFrame:
    """Facility metadata (name, address, lat/long, NAICS) for a given reporting year."""
    url = f"{DMAP_BASE_URL}/PUB_DIM_FACILITY/year/{year}/JSON"
    records = _get_json_with_retry(url)
    return pd.DataFrame(records)


def _fetch_facility_emissions(year: int) -> pd.DataFrame:
    """Power-sector facility x subsector x gas CO2e rows, summed to one total per facility."""
    url = f"{DMAP_BASE_URL}/PUB_FACTS_SECTOR_GHG_EMISSION/year/{year}/sector_id/{POWER_SECTOR_ID}/JSON"
    records = _get_json_with_retry(url)
    df = pd.DataFrame(records)
    if df.empty:
        return df
    totals = (
        df.groupby(["facility_id", "year"], as_index=False)["co2e_emission"]
        .sum()
        .rename(columns={"co2e_emission": "total_co2e_emissions_metric_tons"})
    )
    return totals


def fetch_epa_emissions(years=None) -> pd.DataFrame:
    """
    Fetch real facility-level annual GHG emissions totals (not just facility
    metadata) for each requested reporting year.
    """
    if years is None:
        years = list(DEFAULT_YEARS)

    frames = []
    for year in years:
        print(f"Fetching EPA GHGRP facility emissions for {year}...")
        dim = _fetch_facility_dim(year)
        facts = _fetch_facility_emissions(year)

        if dim.empty or facts.empty:
            print(f"⚠ No EPA records returned for {year}")
            continue

        dim_cols = [
            "facility_id", "facility_name", "city", "state", "state_name",
            "zip", "county", "latitude", "longitude", "naics_code", "facility_types",
            "frs_id",  # bridges to EPA's official CAMD-EIA-FRS crosswalk (see int_plant_emissions.sql)
        ]
        merged = facts.merge(dim[dim_cols], on="facility_id", how="left")
        print(f"✓ Fetched {len(merged)} facility emissions records for {year}")
        frames.append(merged)

    if not frames:
        print("⚠ No EPA records fetched for any requested year")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # Add metadata
    df["_ingested_at"] = pd.Timestamp.now()
    df["_source"] = "epa_ghgrp"

    print(f"✓ Fetched {len(df)} total facility emissions records from EPA across {len(frames)} year(s)")
    return df


def ingest_epa():
    """Main ingestion function."""
    df = fetch_epa_emissions()
    if not df.empty:
        load_to_raw(df, "epa_emissions")
    return df


if __name__ == "__main__":
    ingest_epa()
