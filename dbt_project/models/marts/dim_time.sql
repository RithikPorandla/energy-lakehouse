-- Dimension: calendar year. fact_plant_operations and mart_decarbonization_trend
-- are both annual grain (December-snapshot capacity vs. annual GHGRP reporting),
-- so this is a year spine rather than the finer month/day grain the raw sources
-- don't actually support at a joinable level.

with year_spine as (
    select generate_series(2019, 2023) as year
)

select
    year,
    (year / 10) * 10 as decade,
    case
        when year % 4 = 0 and (year % 100 != 0 or year % 400 = 0) then true
        else false
    end as is_leap_year
from year_spine
