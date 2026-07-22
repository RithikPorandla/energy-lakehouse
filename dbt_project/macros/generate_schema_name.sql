{#
  dbt's default generate_schema_name concatenates the target schema with any
  custom +schema config (e.g. "public_marts"). We want models to land in the
  plain raw/staging/intermediate/marts schemas created by docker/init.sql, so
  use the custom schema name as-is when one is configured.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
