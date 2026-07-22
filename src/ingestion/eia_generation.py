"""
EIA-923 - Electric Power Operations for Individual Power Plants
Source: https://www.eia.gov/opendata/ (electricity/facility-fuel route)
Data: Actual annual net generation (MWh) by plant x fuel type.

eia.py ingests *nameplate* capacity — the theoretical max. This ingests what
a plant actually generated, so downstream models can compute real capacity
factors instead of assuming installed MW translates into output. `plantCode`
here is the same ID space as `plantid` in operating-generator-capacity (both
are EIA plant IDs), so this joins directly — no crosswalk needed.
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

# Matches eia.py / epa.py's ENERGY_SOURCE_CODES / years.
FUEL_TYPES = ["SUN", "WND", "WAT", "NG", "NUC", "COL"]
DEFAULT_YEARS = range(2019, 2024)
PAGE_SIZE = 5000


def _get_with_retry(url, params, retries=4):
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


def _fetch_year(year: int) -> pd.DataFrame:
    """Fetch annual net generation for every plant x fuel type in a given year."""
    url = f"{EIA_BASE_URL}/electricity/facility-fuel/data/"
    all_records = []
    offset = 0

    while True:
        params = {
            "api_key": API_KEY,
            "frequency": "annual",
            "data[0]": "generation",
            "facets[fuelType][]": FUEL_TYPES,
            "facets[primeMover][]": "ALL",  # pre-aggregated across prime movers
            "start": str(year),
            "end": str(year),
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


def fetch_eia_generation(years=None) -> pd.DataFrame:
    """Fetch annual net generation (MWh) by plant x fuel type for each requested year."""
    if years is None:
        years = list(DEFAULT_YEARS)

    frames = []
    for year in years:
        print(f"Fetching EIA generation data for {year}...")
        df = _fetch_year(year)
        if df.empty:
            print(f"⚠ No records returned from EIA API for {year}")
            continue
        print(f"✓ Fetched {len(df)} generation records for {year}")
        frames.append(df)

    if not frames:
        print("⚠ No EIA generation records fetched for any requested year")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    df["_ingested_at"] = pd.Timestamp.now()
    df["_source"] = "eia_923_facility_fuel"

    print(f"✓ Fetched {len(df)} total generation records from EIA across {len(frames)} year(s)")
    return df


def ingest_eia_generation():
    """Main ingestion function — fetch and load to raw."""
    df = fetch_eia_generation()
    if not df.empty:
        load_to_raw(df, "eia_generation")
    return df


if __name__ == "__main__":
    ingest_eia_generation()
