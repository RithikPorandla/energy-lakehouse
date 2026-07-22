-- CI fixture data: a small real slice (Alabama, 2019-2020) exported from the
-- live pipeline, standing in for the ingestion scripts so dbt's tests run
-- fast and deterministically without depending on live third-party APIs or
-- an EIA_API_KEY secret. Run from the repo root: psql ... -f tests/fixtures/load_fixtures.sql

create table raw.eia_generators (
    period text, stateid text, "stateName" text, sector text, "sectorName" text,
    entityid text, "entityName" text, plantid text, "plantName" text, generatorid text,
    technology text, energy_source_code text, "energy-source-desc" text, prime_mover_code text,
    balancing_authority_code text, "balancing-authority-name" text, status text,
    "statusDescription" text, "nameplate-capacity-mw" text, latitude text, longitude text,
    county text, unit text, "nameplate-capacity-mw-units" text,
    _ingested_at timestamp, _source text
);
\copy raw.eia_generators from 'tests/fixtures/fixture_eia_generators.csv' with csv header

create table raw.epa_emissions (
    facility_id bigint, year bigint, total_co2e_emissions_metric_tons double precision,
    facility_name text, city text, state text, state_name text, zip text, county text,
    latitude double precision, longitude double precision, naics_code text, facility_types text,
    frs_id text, _ingested_at timestamp, _source text
);
\copy raw.epa_emissions from 'tests/fixtures/fixture_epa_emissions.csv' with csv header

create table raw.noaa_weather (
    "WSF2" text, "DATE" text, "AWND" text, "STATION" text, "WSF5" text,
    "TMAX" text, "TMIN" text, "PRCP" text, _ingested_at timestamp, _source text
);
\copy raw.noaa_weather from 'tests/fixtures/fixture_noaa_weather.csv' with csv header

create table raw.eia_generation (
    period text, "plantCode" text, "plantName" text, fuel2002 text,
    "fuel2002TypeDescription" text, "fuelType" text, "fuelTypeDescription" text,
    state text, "stateDescription" text, "primeMover" text, generation text,
    "generation-units" text, _ingested_at timestamp, _source text
);
\copy raw.eia_generation from 'tests/fixtures/fixture_eia_generation.csv' with csv header
