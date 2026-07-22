-- Intermediate: join generators with nearby EPA-reporting facilities, by
-- state + year + rounded lat/long (EIA plant coordinates and EPA facility
-- coordinates rarely match exactly, so this is an approximate nearest-cell
-- match rather than a real plant-to-facility ID join — no shared key exists
-- between the two sources).

with generators as (
    select
        plant_id,
        plant_name,
        entity_name,
        state_code,
        county,
        latitude,
        longitude,
        energy_source_code,
        energy_source_desc,
        period_year as year,
        sum(nameplate_capacity_mw) as total_capacity_mw,
        count(distinct generator_id) as generator_count
    from {{ ref('stg_eia_generators') }}
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
),

emissions as (
    select
        facility_id,
        facility_name,
        state_code,
        latitude,
        longitude,
        facility_types,
        reporting_year,
        total_co2e_emissions_metric_tons
    from {{ ref('stg_epa_emissions') }}
)

select
    g.plant_id,
    g.plant_name,
    g.entity_name,
    g.state_code,
    g.county,
    g.latitude,
    g.longitude,
    g.energy_source_code,
    g.energy_source_desc,
    g.year,
    g.total_capacity_mw,
    g.generator_count,
    e.facility_id as epa_facility_id,
    e.facility_types,
    e.total_co2e_emissions_metric_tons as nearby_facility_ghg_emissions
from generators g
left join emissions e
    on g.state_code = e.state_code
    and g.year = e.reporting_year
    and round(g.latitude::numeric, 1) = round(e.latitude::numeric, 1)
    and round(g.longitude::numeric, 1) = round(e.longitude::numeric, 1)
