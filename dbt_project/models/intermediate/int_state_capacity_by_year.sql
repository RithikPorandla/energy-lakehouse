-- Intermediate: EIA generator capacity aggregated to state x year x clean/fossil

with generators as (
    select
        state_code,
        period_year as year,
        nameplate_capacity_mw,
        case
            when energy_source_code in ('SUN', 'WND', 'WAT', 'NUC') then true
            else false
        end as is_clean_energy
    from {{ ref('stg_eia_generators') }}
    where state_code is not null
),

aggregated as (
    select
        state_code,
        year,
        sum(nameplate_capacity_mw) as total_capacity_mw,
        sum(case when is_clean_energy then nameplate_capacity_mw else 0 end) as clean_capacity_mw,
        sum(case when not is_clean_energy then nameplate_capacity_mw else 0 end) as fossil_capacity_mw
    from generators
    group by 1, 2
)

select
    state_code,
    year,
    total_capacity_mw,
    clean_capacity_mw,
    fossil_capacity_mw,
    case
        when total_capacity_mw > 0 then clean_capacity_mw / total_capacity_mw
        else null
    end as clean_capacity_share
from aggregated
