-- Staging model: clean and type-cast raw EIA-923 net generation data
-- 1:1 with source, minimal transformation

with source as (
    select * from raw.eia_generation
),

renamed as (
    select
        -- IDs (plantCode is the same ID space as plantid in eia_generators)
        "plantCode"::varchar                       as plant_id,
        "plantName"::varchar                       as plant_name,

        -- Location
        "state"::varchar                           as state_code,

        -- Fuel
        "fuelType"::varchar                        as energy_source_code,
        "fuelTypeDescription"::varchar             as energy_source_desc,

        -- Measure (negative values are real — net pumped-storage consumption)
        nullif("generation", '')::float            as net_generation_mwh,

        -- Time
        "period"::varchar                          as period,
        "period"::int                              as period_year,

        -- Metadata
        "_ingested_at"::timestamp                  as ingested_at,
        "_source"::varchar                         as source_system
    from source
)

select * from renamed
where plant_id is not null
  and net_generation_mwh is not null
  -- plant_id 99999 is EIA's synthetic "State-Fuel Level Increment" plug row
  -- (a statistical reconciliation adjustment, not a real reporting plant) —
  -- it also carries a null state_code, which is how it originally surfaced.
  and plant_id != '99999'
