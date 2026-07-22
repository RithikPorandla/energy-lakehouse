-- Intermediate: EPA GHGRP facility emissions aggregated to state x year totals

with emissions as (
    select
        state_code,
        reporting_year as year,
        total_co2e_emissions_metric_tons
    from {{ ref('stg_epa_emissions') }}
    where state_code is not null
)

select
    state_code,
    year,
    sum(total_co2e_emissions_metric_tons) as total_ghg_emissions_metric_tons,
    count(*) as reporting_facility_count
from emissions
group by 1, 2
