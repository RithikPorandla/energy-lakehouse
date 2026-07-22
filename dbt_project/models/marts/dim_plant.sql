-- Dimension: plant details

with plants as (
    select * from {{ ref('int_plant_emissions') }}
)

select distinct
    plant_id,
    plant_name,
    entity_name,
    energy_source_code,
    energy_source_desc,
    case energy_source_code
        when 'SUN' then 'Solar'
        when 'WND' then 'Wind'
        when 'WAT' then 'Hydro'
        when 'NG' then 'Natural Gas'
        when 'NUC' then 'Nuclear'
        when 'COL' then 'Coal'
        else 'Other'
    end as energy_type,
    case
        when energy_source_code in ('SUN', 'WND', 'WAT', 'NUC') then true
        else false
    end as is_clean_energy
from plants
where plant_id is not null
