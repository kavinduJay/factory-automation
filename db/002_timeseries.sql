-- Compression and continuous aggregates for telemetry.
-- Kept apart from 001 because continuous aggregates cannot be created inside
-- a transaction block.

ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'sensor_id, key',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('telemetry', interval '7 days');

-- Per minute. Real-time: queries include not-yet-materialized recent data.
CREATE MATERIALIZED VIEW telemetry_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(interval '1 minute', ts) AS bucket,
       sensor_id, key,
       avg(value) AS avg, min(value) AS min, max(value) AS max, count(*) AS n
FROM telemetry
GROUP BY bucket, sensor_id, key
WITH NO DATA;

SELECT add_continuous_aggregate_policy('telemetry_1m',
    start_offset => interval '2 hours',
    end_offset => interval '1 minute',
    schedule_interval => interval '1 minute');

-- Per hour, built on the per-minute aggregate.
CREATE MATERIALIZED VIEW telemetry_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(interval '1 hour', bucket) AS bucket,
       sensor_id, key,
       sum(avg * n) / sum(n) AS avg, min(min) AS min, max(max) AS max, sum(n) AS n
FROM telemetry_1m
GROUP BY 1, sensor_id, key
WITH NO DATA;

SELECT add_continuous_aggregate_policy('telemetry_1h',
    start_offset => interval '3 days',
    end_offset => interval '1 hour',
    schedule_interval => interval '30 minutes');

-- Raw readings are kept (compressed) indefinitely for now. When disk matters,
-- add: SELECT add_retention_policy('telemetry', interval '1 year');
