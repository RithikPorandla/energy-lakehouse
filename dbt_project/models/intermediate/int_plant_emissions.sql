-- Intermediate: join generators to the EPA-reporting facility that is
-- actually theirs, using EPA's official CAMD-EIA-FRS crosswalk where
-- possible ('crosswalk_exact') — a real identifier join, not a guess — and
-- falling back to the old approximate state + rounded-lat/long match
-- ('geo_approximate') only for plant/years the crosswalk doesn't cover
-- (renewables aren't CAMD-regulated, so they never get a crosswalk match
-- and always fall back).

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
        total_co2e_emissions_metric_tons,
        frs_id
    from {{ ref('stg_epa_emissions') }}
),

-- EPA's crosswalk is keyed by CAMD_PLANT_ID, which is the same ORISPL
-- numbering as EIA plant_id for the vast majority of plants (this is a
-- generator/boiler-level crosswalk upstream; at the plant level the IDs
-- are shared, not translated).
emissions_with_crosswalk_plant_id as (
    select
        e.*,
        x."CAMD_PLANT_ID" as crosswalk_plant_id
    from emissions e
    inner join {{ ref('epa_frs_crosswalk') }} x
        on e.frs_id = x."FRS_ID"
),

-- A small minority of plants (~6%) have more than one GHGRP facility
-- registration at the same site (e.g. co-owned units registered
-- separately) — sum to one row per plant/year rather than fanning out,
-- since "this plant's total associated emissions" is the physically
-- meaningful quantity, not an arbitrary pick of one registration.
exact_matches_raw as (
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
    inner join emissions_with_crosswalk_plant_id e
        on g.plant_id = e.crosswalk_plant_id
        and g.year = e.reporting_year
),

exact_matches as (
    select
        plant_id,
        max(plant_name) as plant_name,
        max(entity_name) as entity_name,
        max(state_code) as state_code,
        max(county) as county,
        max(latitude) as latitude,
        max(longitude) as longitude,
        max(energy_source_code) as energy_source_code,
        max(energy_source_desc) as energy_source_desc,
        year,
        max(total_capacity_mw) as total_capacity_mw,
        max(generator_count) as generator_count,
        string_agg(distinct epa_facility_id, ',') as epa_facility_id,
        max(facility_types) as facility_types,
        sum(nearby_facility_ghg_emissions) as nearby_facility_ghg_emissions,
        'crosswalk_exact' as match_type
    from exact_matches_raw
    group by plant_id, year
),

geo_matches as (
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
        e.total_co2e_emissions_metric_tons as nearby_facility_ghg_emissions,
        case when e.facility_id is not null then 'geo_approximate' else null end as match_type
    from generators g
    left join emissions e
        on g.state_code = e.state_code
        and g.year = e.reporting_year
        and round(g.latitude::numeric, 1) = round(e.latitude::numeric, 1)
        and round(g.longitude::numeric, 1) = round(e.longitude::numeric, 1)
    where not exists (
        select 1 from exact_matches x
        where x.plant_id = g.plant_id and x.year = g.year
    )
)

select * from exact_matches
union all
select * from geo_matches
