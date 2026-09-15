-- =============================================================================
-- anomaly_sql.sql — Flink SQL pipeline: sensor-readings → PostgreSQL
--
-- Run this inside the Flink SQL client:
--     ./flink/install-flink-podman.sh sql     (if using the existing Podman setup)
--     OR open http://localhost:8081 SQL Gateway
--
-- Steps executed top-to-bottom:
--   1. Source table  — reads from Kafka sensor-readings topic
--   2. Sink tables   — writes aggregates + alerts to PostgreSQL
--   3. Aggregate job — tumbling 1-min window → sensor_aggregates
--   4. Alert job     — anomaly threshold filter → equipment_alerts
-- =============================================================================

SET 'sql-client.execution.result-mode' = 'tableau';

-- ---------------------------------------------------------------------------
-- 1. Source — raw sensor events from local Kafka
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_readings (
    facility     STRING,
    machine_id   STRING,
    sensor_type  STRING,
    `timestamp`  STRING,
    unit         STRING,
    `value`      DOUBLE,
    proc_time    AS PROCTIME()          -- processing-time watermark (no late data gaps)
) WITH (
    'connector'                    = 'kafka',
    'topic'                        = 'sensor-readings',
    'properties.bootstrap.servers' = 'kafka:29092',    -- internal Docker network address
    'properties.group.id'          = 'flink-sql-reader',
    'scan.startup.mode'            = 'earliest-offset',
    'format'                       = 'json'
);

-- ---------------------------------------------------------------------------
-- 2a. Sink — rolling 1-minute aggregates → PostgreSQL sensor_aggregates table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_aggregates (
    machine_id   STRING,
    sensor_type  STRING,
    facility     STRING,
    window_start TIMESTAMP(3),
    window_end   TIMESTAMP(3),
    avg_value    DOUBLE,
    min_value    DOUBLE,
    max_value    DOUBLE,
    event_count  BIGINT,
    unit         STRING
) WITH (
    'connector'  = 'jdbc',
    'url'        = 'jdbc:postgresql://postgres:5432/streaming',
    'table-name' = 'sensor_aggregates',
    'username'   = 'flink',
    'password'   = 'flink',
    'driver'     = 'org.postgresql.Driver'
);

-- ---------------------------------------------------------------------------
-- 2b. Sink — anomaly alerts → PostgreSQL equipment_alerts table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equipment_alerts (
    machine_id    STRING,
    sensor_type   STRING,
    facility      STRING,
    window_start  TIMESTAMP(3),
    window_end    TIMESTAMP(3),
    avg_value     DOUBLE,
    min_value     DOUBLE,
    max_value     DOUBLE,
    anomaly_score DOUBLE,
    severity      STRING,
    unit          STRING
) WITH (
    'connector'  = 'jdbc',
    'url'        = 'jdbc:postgresql://postgres:5432/streaming',
    'table-name' = 'equipment_alerts',
    'username'   = 'flink',
    'password'   = 'flink',
    'driver'     = 'org.postgresql.Driver'
);

-- ---------------------------------------------------------------------------
-- 3. Aggregate job — tumbling 1-minute window per machine+sensor
--    Runs as a persistent background job.
--    Check status: SHOW JOBS;
-- ---------------------------------------------------------------------------
INSERT INTO sensor_aggregates
SELECT
    machine_id,
    sensor_type,
    MAX(facility)                          AS facility,
    TUMBLE_START(proc_time, INTERVAL '1' MINUTE) AS window_start,
    TUMBLE_END  (proc_time, INTERVAL '1' MINUTE) AS window_end,
    AVG(`value`)                           AS avg_value,
    MIN(`value`)                           AS min_value,
    MAX(`value`)                           AS max_value,
    COUNT(*)                               AS event_count,
    MAX(unit)                              AS unit
FROM sensor_readings
GROUP BY
    machine_id,
    sensor_type,
    TUMBLE(proc_time, INTERVAL '1' MINUTE);

-- ---------------------------------------------------------------------------
-- 4. Alert job — anomaly detection via range/spread score
--
-- Anomaly score = (max - min) / (avg + 0.0001)
-- A high spread relative to the average indicates an unstable sensor.
--
-- Thresholds (tuned to match sensor baselines in sensor_producer.py):
--   critical : score >= 2.0  (e.g. vibration spike on turbine-1)
--   warning  : score >= 0.8
--
-- Runs as a second persistent background job alongside the aggregate job.
-- ---------------------------------------------------------------------------
INSERT INTO equipment_alerts
SELECT
    machine_id,
    sensor_type,
    MAX(facility)                          AS facility,
    TUMBLE_START(proc_time, INTERVAL '1' MINUTE) AS window_start,
    TUMBLE_END  (proc_time, INTERVAL '1' MINUTE) AS window_end,
    AVG(`value`)                           AS avg_value,
    MIN(`value`)                           AS min_value,
    MAX(`value`)                           AS max_value,
    (MAX(`value`) - MIN(`value`)) / (AVG(`value`) + 0.0001) AS anomaly_score,
    CASE
        WHEN (MAX(`value`) - MIN(`value`)) / (AVG(`value`) + 0.0001) >= 2.0 THEN 'critical'
        WHEN (MAX(`value`) - MIN(`value`)) / (AVG(`value`) + 0.0001) >= 0.8 THEN 'warning'
        ELSE 'info'
    END                                    AS severity,
    MAX(unit)                              AS unit
FROM sensor_readings
GROUP BY
    machine_id,
    sensor_type,
    TUMBLE(proc_time, INTERVAL '1' MINUTE)
HAVING
    (MAX(`value`) - MIN(`value`)) / (AVG(`value`) + 0.0001) >= 0.8;
