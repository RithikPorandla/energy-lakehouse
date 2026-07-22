"""
NOAA Climate Data Online (CDO) — daily summaries
Source: https://www.ncei.noaa.gov/access/services/data/v1
Data: Weather station observations (temp, wind, precip).

Public endpoint, no API key required. Provides plant-level weather context
in fact_plant_operations; not part of the headline decarbonization mart
(GHGRP emissions are annual/facility-level, so daily weather can't be
causally tied to them at that grain).
"""
import socket
import time
import requests
import urllib3.util.connection as urllib3_connection
import pandas as pd
from src.utils.db import load_to_raw

# NOAA's endpoint is reachable over IPv6 from some networks, but the path can
# be silently broken (connection wedges in SYN_SENT and never times out
# cleanly). Force IPv4 for this client to avoid hanging ingestion runs.
urllib3_connection.allowed_gai_family = lambda: socket.AF_INET

NOAA_BASE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

# Matches the EIA/EPA ingestion window (see eia.py / epa.py).
START_DATE = "2019-01-01"
END_DATE = "2023-12-31"

# Stations near major renewable energy installations
DEFAULT_STATION_IDS = [
    "USW00014739",  # Boston (near Vineyard Wind interconnection)
    "USW00023174",  # Los Angeles (solar)
    "USW00013874",  # Houston (wind corridor)
    "USW00024233",  # Portland OR (hydro)
    "USW00003927",  # Amarillo TX (wind belt)
]


def _get_with_retry(params, retries=4):
    for attempt in range(retries):
        try:
            response = requests.get(NOAA_BASE_URL, params=params, timeout=(10, 60))
            response.raise_for_status()
            return response
        except (requests.exceptions.HTTPError, requests.exceptions.Timeout) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"⚠ NOAA request failed ({e}), retrying in {wait}s...")
            time.sleep(wait)


def fetch_noaa_weather(dataset="daily-summaries", station_ids=None,
                        start_date=START_DATE, end_date=END_DATE):
    """
    Fetch daily weather summaries from NOAA, one station at a time (the
    service can silently truncate multi-station multi-year requests).
    """
    if station_ids is None:
        station_ids = DEFAULT_STATION_IDS

    frames = []
    for station_id in station_ids:
        print(f"Fetching NOAA weather data for {station_id} ({start_date} to {end_date})...")
        params = {
            "dataset": dataset,
            "stations": station_id,
            "startDate": start_date,
            "endDate": end_date,
            "dataTypes": "TMAX,TMIN,TAVG,AWND,PRCP,WSF2,WSF5",
            "units": "metric",
            "format": "json",
        }
        response = _get_with_retry(params)
        records = response.json()
        if not records:
            print(f"⚠ No records returned from NOAA for {station_id}")
            continue
        print(f"✓ Fetched {len(records)} weather records for {station_id}")
        frames.append(pd.DataFrame(records))

    if not frames:
        print("⚠ No records returned from NOAA")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # Add metadata
    df["_ingested_at"] = pd.Timestamp.now()
    df["_source"] = "noaa_daily_summaries"

    print(f"✓ Fetched {len(df)} total weather records from NOAA")
    return df


def ingest_noaa():
    """Main ingestion function."""
    df = fetch_noaa_weather()
    if not df.empty:
        load_to_raw(df, "noaa_weather")
    return df


if __name__ == "__main__":
    ingest_noaa()
