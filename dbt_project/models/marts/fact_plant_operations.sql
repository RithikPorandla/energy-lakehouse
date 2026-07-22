-- Fact table: plant operations with capacity and (where matched) nearby facility emissions

with plant_emissions as (
    select * from {{ ref('int_plant_emissions') }}
)

select
    -- Surrogate key
    {{ dbt_utils.generate_surrogate_key(['pe.plant_id', 'pe.year']) }} as operation_id,

    -- Foreign keys
    pe.plant_id,
    pe.state_code,
    pe.year,

    -- Measures
    pe.total_capacity_mw,
    pe.generator_count,

    -- Derived metrics
    case
        when pe.energy_source_code = 'SUN' then 'Solar'
        when pe.energy_source_code = 'WND' then 'Wind'
        when pe.energy_source_code = 'WAT' then 'Hydro'
        when pe.energy_source_code = 'NG' then 'Natural Gas'
        when pe.energy_source_code = 'NUC' then 'Nuclear'
        when pe.energy_source_code in ('BIT', 'SUB', 'LIG', 'WC', 'RC', 'SGC', 'ANT') then 'Coal'
        else 'Other'
    end as energy_type,

    -- EPA linkage
    pe.epa_facility_id,
    pe.facility_types,
    pe.nearby_facility_ghg_emissions,
    pe.match_type,

    -- Metadata
    current_timestamp as dbt_updated_at

from plant_emissions pe
