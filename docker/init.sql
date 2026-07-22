-- Create schemas for medallion architecture
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS analytics;

-- Raw tables are created by ingestion scripts.
-- dbt creates staging, intermediate, and marts tables.
-- ML scripts (ml/) write their outputs into analytics.
