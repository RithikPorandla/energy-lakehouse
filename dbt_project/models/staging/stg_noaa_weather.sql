-- Staging model: clean and pivot raw NOAA weather data

with source as (
    select * from raw.noaa_weather
),

renamed as (
    select
        "STATION"::varchar                    as station_id,
        "DATE"::date                          as observation_date,
        nullif("TMAX", '')::float             as temp_max_c,
        nullif("TMIN", '')::float             as temp_min_c,
        -- None of the default stations report NOAA's native TAVG field, so
        -- it's derived from max/min rather than a direct measurement.
        (nullif("TMAX", '')::float + nullif("TMIN", '')::float) / 2 as temp_avg_c,
        nullif("AWND", '')::float             as avg_wind_speed_mps,
        nullif("PRCP", '')::float             as precipitation_mm,
        nullif("WSF2", '')::float             as max_wind_speed_2min_mps,
        nullif("WSF5", '')::float             as max_wind_speed_5sec_mps,

        -- Metadata
        "_ingested_at"::timestamp             as ingested_at,
        "_source"::varchar                    as source_system
    from source
)

select * from renamed
where station_id is not null
  and observation_date is not null
