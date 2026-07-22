-- Dimension: geographic location

with plants as (
    select * from {{ ref('int_plant_emissions') }}
)

select distinct
    state_code,
    county,
    latitude,
    longitude,
    -- Region mapping
    case
        when state_code in ('ME','NH','VT','MA','RI','CT','NY','NJ','PA') then 'Northeast'
        when state_code in ('OH','IN','IL','MI','WI','MN','IA','MO','ND','SD','NE','KS') then 'Midwest'
        when state_code in ('DE','MD','DC','VA','WV','NC','SC','GA','FL','KY','TN','AL','MS','AR','LA','OK','TX') then 'South'
        when state_code in ('MT','ID','WY','CO','NM','AZ','UT','NV','WA','OR','CA','AK','HI') then 'West'
        else 'Other'
    end as region
from plants
where state_code is not null
