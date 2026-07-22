-- Intermediate: EIA-923 actual net generation aggregated to state x year x clean/fossil

with generation as (
    select
        state_code,
        period_year as year,
        net_generation_mwh,
        case
            when energy_source_code in ('SUN', 'WND', 'WAT', 'NUC') then true
            else false
        end as is_clean_energy
    from {{ ref('stg_eia_generation') }}
    where state_code is not null
),

aggregated as (
    select
        state_code,
        year,
        sum(net_generation_mwh) as total_generation_mwh,
        sum(case when is_clean_energy then net_generation_mwh else 0 end) as clean_generation_mwh,
        sum(case when not is_clean_energy then net_generation_mwh else 0 end) as fossil_generation_mwh
    from generation
    group by 1, 2
)

select
    state_code,
    year,
    total_generation_mwh,
    clean_generation_mwh,
    fossil_generation_mwh,
    case
        when total_generation_mwh > 0 then clean_generation_mwh / total_generation_mwh
        else null
    end as clean_generation_share
from aggregated
