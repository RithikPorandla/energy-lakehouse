-- Dimension: plant details — one row per plant_id.
--
-- int_plant_emissions is grained at plant x fuel x year (a plant's entity
-- owner or dominant fuel can shift across years — ownership changes,
-- re-classification), so a naive `select distinct` over all history can
-- produce more than one row per plant_id, which fans out anything joining
-- on plant_id alone downstream. Pick each plant's most recent year, and
-- within that year its largest-capacity fuel, as the representative row.

with plants as (
    select * from {{ ref('int_plant_emissions') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by plant_id
            order by year desc, total_capacity_mw desc
        ) as rn
    from plants
    where plant_id is not null
)

select
    plant_id,
    plant_name,
    entity_name,
    energy_source_code,
    energy_source_desc,
    case
        when energy_source_code = 'SUN' then 'Solar'
        when energy_source_code = 'WND' then 'Wind'
        when energy_source_code = 'WAT' then 'Hydro'
        when energy_source_code = 'NG' then 'Natural Gas'
        when energy_source_code = 'NUC' then 'Nuclear'
        when energy_source_code in ('BIT', 'SUB', 'LIG', 'WC', 'RC', 'SGC', 'ANT') then 'Coal'
        else 'Other'
    end as energy_type,
    case
        when energy_source_code in ('SUN', 'WND', 'WAT', 'NUC') then true
        else false
    end as is_clean_energy
from ranked
where rn = 1
