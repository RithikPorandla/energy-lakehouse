-- Staging model: clean and type-cast raw EIA generator data
-- 1:1 with source, minimal transformation

with source as (
    select * from raw.eia_generators
),

renamed as (
    select
        -- IDs
        "plantid"::varchar                            as plant_id,
        "generatorid"::varchar                        as generator_id,

        -- Plant info
        "plantName"::varchar                          as plant_name,
        "entityName"::varchar                         as entity_name,
        "sector"::varchar                              as sector,
        "technology"::varchar                          as technology,

        -- Location
        "stateid"::varchar                             as state_code,
        "county"::varchar                              as county,
        nullif("latitude", '')::float                  as latitude,
        nullif("longitude", '')::float                 as longitude,

        -- Capacity
        nullif("nameplate-capacity-mw", '')::float      as nameplate_capacity_mw,

        -- Energy source
        "energy_source_code"::varchar                  as energy_source_code,
        "energy-source-desc"::varchar                  as energy_source_desc,

        -- Operating status (raw is already filtered to 'OP' at ingestion time)
        "status"::varchar                               as operating_status,

        -- Time — one December snapshot per year
        "period"::varchar                               as period,
        left("period", 4)::int                          as period_year,

        -- Metadata
        "_ingested_at"::timestamp                       as ingested_at,
        "_source"::varchar                              as source_system
    from source
)

select * from renamed
where plant_id is not null
  and nameplate_capacity_mw is not null
  and nameplate_capacity_mw > 0
