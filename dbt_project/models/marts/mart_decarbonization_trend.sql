-- Mart: the headline insight. For each state x year, tracks clean-energy
-- capacity share (EIA) against real facility GHG emissions (EPA) and flags
-- years where clean capacity grew meaningfully but emissions didn't fall —
-- i.e. capacity additions that aren't translating into measured decarbonization.

with capacity as (
    select * from {{ ref('int_state_capacity_by_year') }}
),

emissions as (
    select * from {{ ref('int_state_emissions_by_year') }}
),

generation as (
    select * from {{ ref('int_state_generation_by_year') }}
),

joined as (
    select
        c.state_code,
        c.year,
        c.total_capacity_mw,
        c.clean_capacity_mw,
        c.fossil_capacity_mw,
        c.clean_capacity_share,
        e.total_ghg_emissions_metric_tons,
        e.reporting_facility_count,
        g.total_generation_mwh,
        g.clean_generation_mwh,
        g.clean_generation_share,
        -- annual hours in the reporting year (accounts for leap years)
        case when c.year % 4 = 0 then 8784.0 else 8760.0 end as hours_in_year
    from capacity c
    inner join emissions e
        on c.state_code = e.state_code
        and c.year = e.year
    left join generation g
        on c.state_code = g.state_code
        and c.year = g.year
),

with_lags as (
    select
        *,
        lag(clean_capacity_mw) over (partition by state_code order by year) as prev_clean_capacity_mw,
        lag(total_ghg_emissions_metric_tons) over (partition by state_code order by year) as prev_ghg_emissions
    from joined
),

with_deltas as (
    select
        *,
        case
            when prev_clean_capacity_mw > 0
            then (clean_capacity_mw - prev_clean_capacity_mw) / prev_clean_capacity_mw
        end as yoy_clean_capacity_growth,
        case
            when prev_ghg_emissions > 0
            then (total_ghg_emissions_metric_tons - prev_ghg_emissions) / prev_ghg_emissions
        end as yoy_emissions_change
    from with_lags
)

select
    state_code,
    year,
    total_capacity_mw,
    clean_capacity_mw,
    fossil_capacity_mw,
    clean_capacity_share,
    total_ghg_emissions_metric_tons,
    reporting_facility_count,
    total_generation_mwh,
    clean_generation_mwh,
    clean_generation_share,
    -- Capacity factor: actual output vs. theoretical max (nameplate MW x
    -- hours in year). This is what actually explains a divergence — clean
    -- capacity can grow on paper while running at a low factor (curtailed,
    -- still ramping, poor siting) and not move the emissions needle.
    case
        when total_capacity_mw > 0
        then total_generation_mwh / (total_capacity_mw * hours_in_year)
    end as capacity_factor,
    case
        when clean_capacity_mw > 0
        then clean_generation_mwh / (clean_capacity_mw * hours_in_year)
    end as clean_capacity_factor,
    yoy_clean_capacity_growth,
    yoy_emissions_change,
    -- Divergence: clean capacity grew >3% YoY while emissions fell by less
    -- than 1% (flat or rising) — capacity growth outpacing decarbonization.
    case
        when yoy_clean_capacity_growth > 0.03
             and coalesce(yoy_emissions_change, 0) > -0.01
        then true
        else false
    end as capacity_emissions_divergence_flag
from with_deltas
