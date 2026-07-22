-- Staging model: clean and type-cast raw EPA GHGRP facility emissions data
-- Real annual CO2e totals per facility (from PUB_FACTS_SECTOR_GHG_EMISSION),
-- joined to facility metadata (from PUB_DIM_FACILITY) at ingestion time.

with source as (
    select * from raw.epa_emissions
),

renamed as (
    select
        "facility_id"::varchar                          as facility_id,
        "facility_name"::varchar                        as facility_name,
        "year"::integer                                  as reporting_year,
        "city"::varchar                                  as city,
        "state"::varchar                                 as state_code,
        "zip"::varchar                                    as zip_code,
        "latitude"::float                                 as latitude,
        "longitude"::float                                as longitude,
        "naics_code"::varchar                             as naics_code,
        "facility_types"::varchar                         as facility_types,
        "total_co2e_emissions_metric_tons"::float          as total_co2e_emissions_metric_tons,
        "frs_id"::varchar                                  as frs_id,

        -- Metadata
        "_ingested_at"::timestamp                          as ingested_at,
        "_source"::varchar                                 as source_system
    from source
)

select * from renamed
where facility_id is not null
  and total_co2e_emissions_metric_tons is not null
