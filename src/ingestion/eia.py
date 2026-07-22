"""
EIA 860M - Monthly Electric Generator Inventory
Source: https://www.eia.gov/opendata/
Data: Operating generators, nameplate capacity, fuel type, location.

Pulls a December snapshot for each of the last several years (not just the
latest month) so downstream models can compute year-over-year state-level
capacity trends.
"""
import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv
from src.utils.db import load_to_raw

load_dotenv()

EIA_BASE_URL = "https://api.eia.gov/v2"
API_KEY = os.getenv("EIA_API_KEY")

# SUN/WND/WAT/NUC = clean per dim_plant.is_clean_energy; NG + coal = fossil.
# This endpoint (operating-generator-capacity, Form 860) uses granular coal
# codes (BIT/SUB/LIG/WC/RC/SGC/ANT), NOT the aggregated "COL" fuelType used
# by the facility-fuel/EIA-923 generation endpoint (see eia_generation.py) —
# using "COL" here silently matches zero rows instead of erroring, which is
# how this went unnoticed: coal capacity was missing from the fossil
# denominator entirely until this was caught.
ENERGY_SOURCE_CODES = [
    "SUN", "WND", "WAT", "NG", "NUC",
    "BIT", "SUB", "LIG", "WC", "RC", "SGC", "ANT",
]
PAGE_SIZE = 5000


def _get_with_retry(url, params, retries=4):
    """EIA's API occasionally 502s under load — retry with backoff before giving up."""
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"⚠ EIA request failed ({e}), retrying in {wait}s...")
            time.sleep(wait)


def _fetch_period(period: str) -> pd.DataFrame:
    """Fetch every operating generator row for a single YYYY-MM period, paginating as needed."""
    url = f"{EIA_BASE_URL}/electricity/operating-generator-capacity/data/"
    all_records = []
    offset = 0

    while True:
        params = {
            "api_key": API_KEY,
            "frequency": "monthly",
            "data[0]": "nameplate-capacity-mw",
            "data[1]": "latitude",
            "data[2]": "longitude",
            "data[3]": "county",
            "facets[energy_source_code][]": ENERGY_SOURCE_CODES,
            "facets[status][]": "OP",  # operating only
            "start": period,
            "end": period,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": offset,
            "length": PAGE_SIZE,
        }
        response = _get_with_retry(url, params)
        payload = response.json().get("response", {})
        records = payload.get("data", [])
        all_records.extend(records)

        total = int(payload.get("total", len(all_records)))
        offset += PAGE_SIZE
        if offset >= total or not records:
            break

    return pd.DataFrame(all_records)


# EPA's GHGRP facility-emissions facts table (see epa.py) only has published
# data through 2023 as of this build — align the EIA capacity years to match
# so the decarbonization mart has a real year-over-year overlap on both sides.
DEFAULT_YEARS = range(2019, 2024)


def fetch_eia_generators(years=None) -> pd.DataFrame:
    """
    Fetch a December snapshot of operating generator capacity for each requested year.
    Returns: DataFrame with plant/generator-level capacity data across years.
    """
    if years is None:
        years = list(DEFAULT_YEARS)

    frames = []
    for year in years:
        period = f"{year}-12"
        print(f"Fetching EIA generator data for {period}...")
        df = _fetch_period(period)
        if df.empty:
            print(f"⚠ No records returned from EIA API for {period}")
            continue
        print(f"✓ Fetched {len(df)} generator records for {period}")
        frames.append(df)

    if not frames:
        print("⚠ No EIA records fetched for any requested year")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # Add metadata
    df["_ingested_at"] = pd.Timestamp.now()
    df["_source"] = "eia_860m"

    print(f"✓ Fetched {len(df)} total generator records from EIA across {len(frames)} year(s)")
    return df


def ingest_eia():
    """Main ingestion function — fetch and load to raw."""
    df = fetch_eia_generators()
    if not df.empty:
        load_to_raw(df, "eia_generators")
    return df


if __name__ == "__main__":
    ingest_eia()
